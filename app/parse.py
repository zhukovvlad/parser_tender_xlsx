"""
Основной модуль-оркестратор для обработки тендерных XLSX файлов.

Назначение:
Этот скрипт является точкой входа для обработки новых тендерных документов.
Он отвечает за извлечение данных, их первичную регистрацию в основной системе
через API и, в случае успеха, за генерацию всех производных артефактов для
локального архивирования.

Основная последовательность операций:
1.  Парсинг исходного XLSX-файла и его преобразование во внутренний JSON-формат.
    На этом этапе происходит очистка и структурирование данных.

2.  Регистрация тендера в системе. Сформированный JSON отправляется на Go-сервер.
    Этот шаг является критически важным, так как сервер в ответ возвращает
    уникальные идентификаторы (ID), сгенерированные в базе данных для самого
    тендера и для каждого из его лотов.

3.  Проверка успеха регистрации. Дальнейшие шаги выполняются ТОЛЬКО в том случае,
    если сервер успешно принял данные и вернул ID. Если регистрация не удалась,
    обработка файла прерывается, чтобы избежать создания "осиротевших" артефактов.

4.  Генерация локальных артефактов. На основе полученных из БД идентификаторов
    создаются все производные файлы. Использование ID из базы данных в именах
    файлов гарантирует их уникальность и прямую связь с записями в системе.
    Создаются следующие файлы:
    - Основной JSON-файл (`{tender_db_id}.json`).
    - MD-отчеты для каждого лота (`{tender_db_id}_{lot_db_id}.md`).
    - Файлы с чанками для каждого лота (`{tender_db_id}_{lot_db_id}_chunks.json`).
    - Детализированные MD-отчеты по позициям для каждого лота (`{tender_db_id}_{lot_db_id}_positions.md`).

5.  Архивация. Исходный XLSX-файл переименовывается в `{tender_db_id}.xlsx`,
    после чего он и все сгенерированные артефакты перемещаются в
    соответствующие директории для долгосрочного хранения.
"""

import argparse
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

# Используем относительные импорты
from .constants import JSON_KEY_EXECUTOR, JSON_KEY_LOTS
from .helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from .helpers.read_headers import read_headers
from .helpers.read_lots_and_boundaries import read_lots_and_boundaries
from .helpers.read_executer_block import read_executer_block
from .markdown_utils.json_to_markdown import generate_markdown_for_lots
from .markdown_to_chunks.tender_chunker import create_chunks_from_markdown_text
from .json_to_server.send_json_to_go_server import register_tender_in_go
from .markdown_utils.positions_report import generate_reports_for_all_lots

log = logging.getLogger(__name__)


def _extract_xlsx_data(source_path: Path) -> Dict[str, Any]:
    """
    Извлекает данные из XLSX файла и преобразует их в структурированный JSON.

    Args:
        source_path: Путь к XLSX файлу

    Returns:
        Словарь с извлеченными данными

    Raises:
        Exception: При ошибках чтения файла или парсинга данных
    """
    log.info("Этап 1: Извлечение данных из XLSX...")
    wb = openpyxl.load_workbook(source_path, data_only=True)
    ws: Worksheet = wb.active

    processed_data: Dict[str, Any] = {
        **read_headers(ws),
        JSON_KEY_EXECUTOR: read_executer_block(ws),
        JSON_KEY_LOTS: read_lots_and_boundaries(ws),
    }
    processed_data = normalize_lots_json_structure(processed_data)
    processed_data = replace_div0_with_null(processed_data)
    log.info("Данные успешно извлечены.")
    return processed_data


def _register_tender(
    processed_data: Dict[str, Any],
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    Регистрирует тендер на сервере и получает ID из базы данных.

    Args:
        processed_data: Данные тендера для регистрации

    Returns:
        Кортеж (успех, ID тендера, карта ID лотов)
    """
    go_server_url = os.getenv("GO_SERVER_API_ENDPOINT")
    if not go_server_url:
        log.error(
            "Переменная окружения GO_SERVER_API_ENDPOINT не задана. Обработка прервана."
        )
        return False, "", {}

    fallback_mode = os.getenv("PARSER_FALLBACK_MODE", "false").lower() == "true"

    log.info("Этап 2: Регистрация тендера на Go сервере...")
    if fallback_mode:
        log.info(
            "Резервный режим включен - обработка продолжится даже при недоступности сервера"
        )

    go_server_api_key = os.getenv("GO_SERVER_API_KEY")

    return register_tender_in_go(
        processed_data, go_server_url, go_server_api_key, fallback_mode=fallback_mode
    )


def _generate_lot_artifacts(
    lot_markdowns: Dict[str, List[str]],
    lot_ids_map: Dict[str, Any],
    base_name: str,
    output_dir: Path,
    initial_tender_metadata: Dict[str, Any],
) -> Tuple[List[Path], List[Path]]:
    """
    Генерирует MD файлы и чанки для каждого лота.

    Args:
        lot_markdowns: Словарь с MD-контентом для каждого лота
        lot_ids_map: Карта ID лотов из базы данных
        base_name: Базовое имя для файлов
        output_dir: Директория для сохранения файлов
        initial_tender_metadata: Метаданные тендера

    Returns:
        Кортеж (список путей MD файлов, список путей файлов чанков)
    """
    generated_md_paths: List[Path] = []
    generated_chunks_paths: List[Path] = []

    if not lot_ids_map:
        log.warning(
            "От сервера не получена карта ID лотов. Пропускаем генерацию MD и чанков."
        )
        return generated_md_paths, generated_chunks_paths

    for lot_key, lot_db_id in lot_ids_map.items():
        log.info(f"--- Генерация для лота (ключ: {lot_key}, ID: {lot_db_id}) ---")

        markdown_lines = lot_markdowns.get(lot_key)
        if not markdown_lines:
            log.warning(f"Не найден MD-контент для ключа лота: {lot_key}. Пропускаем.")
            continue

        # Создаем и сохраняем MD-файл для лота
        markdown_content_str = "\n".join(markdown_lines)
        md_path = output_dir / f"{base_name}_{lot_db_id}.md"
        with open(md_path, "w", encoding="utf-8") as f_md:
            f_md.write(markdown_content_str)
        generated_md_paths.append(md_path)
        log.info(f"MD-отчет для лота сохранен в: {md_path.name}")

        # Создаем и сохраняем чанки для этого MD-файла
        tender_chunks = create_chunks_from_markdown_text(
            markdown_text=markdown_content_str,
            tender_metadata=initial_tender_metadata,
            lot_db_id=lot_db_id,
        )

        chunks_path = output_dir / f"{base_name}_{lot_db_id}_chunks.json"
        with open(chunks_path, "w", encoding="utf-8") as f_chunks:
            json.dump(tender_chunks, f_chunks, ensure_ascii=False, indent=2)
        generated_chunks_paths.append(chunks_path)
        log.info(
            f"Текстовые чанки ({len(tender_chunks)} шт.) для лота сохранены в: {chunks_path.name}"
        )

    return generated_md_paths, generated_chunks_paths


def _archive_generated_files(
    source_path: Path,
    output_json_path: Path,
    generated_md_paths: List[Path],
    generated_chunks_paths: List[Path],
    position_reports_paths: List[Path],
    base_name: str,
    is_temp_id: bool,
) -> None:
    """
    Архивирует все сгенерированные файлы в соответствующие директории.

    Args:
        source_path: Путь к исходному XLSX файлу
        output_json_path: Путь к основному JSON файлу
        generated_md_paths: Список путей MD файлов
        generated_chunks_paths: Список путей файлов чанков
        position_reports_paths: Список путей отчетов по позициям
        base_name: Базовое имя файлов
        is_temp_id: Флаг временного ID
    """
    log.info("Этап 4: Перемещение всех файлов в целевые директории...")

    project_root = Path.cwd()
    output_dir = source_path.parent

    target_dir_name = "pending_sync" if is_temp_id else "tenders"
    if is_temp_id:
        log.info(
            "Используются временные ID - файлы будут помещены в директорию pending_sync"
        )

    target_dirs = {
        "xlsx": project_root / f"{target_dir_name}_xlsx",
        "json": project_root / f"{target_dir_name}_json",
        "md": project_root / f"{target_dir_name}_md",
        "chunks": project_root / f"{target_dir_name}_chunks",
        "positions": project_root / f"{target_dir_name}_positions",
    }

    for dir_path in target_dirs.values():
        os.makedirs(dir_path, exist_ok=True)

    def move_if_exists(src_path: Path, dest_dir: Path) -> None:
        if src_path.exists():
            shutil.move(str(src_path), str(dest_dir / src_path.name))
            log.info(f"Файл '{src_path.name}' перемещен в: {dest_dir.name}")

    # Переименовываем и перемещаем XLSX
    renamed_xlsx_path = output_dir / f"{base_name}.xlsx"
    source_path.rename(renamed_xlsx_path)
    move_if_exists(renamed_xlsx_path, target_dirs["xlsx"])

    # Перемещаем основной JSON
    move_if_exists(output_json_path, target_dirs["json"])

    # Перемещаем все сгенерированные MD и файлы чанков
    for path in generated_md_paths:
        move_if_exists(path, target_dirs["md"])
    for path in generated_chunks_paths:
        move_if_exists(path, target_dirs["chunks"])

    # Перемещаем отчеты по позициям
    for path in position_reports_paths:
        move_if_exists(path, target_dirs["positions"])


def parse_file(xlsx_path: str) -> None:
    """
    Оркестрирует полный цикл обработки одного тендерного XLSX-файла.

    Args:
        xlsx_path: Путь к XLSX файлу тендерной документации
    """
    log.info(f"--- Начало обработки файла: {xlsx_path} ---")
    source_path = Path(xlsx_path).resolve()

    # --- Этап 1: Парсинг XLSX в JSON ---
    try:
        processed_data = _extract_xlsx_data(source_path)
    except Exception:
        log.exception(f"Критическая ошибка на этапе парсинга файла '{source_path}'.")
        return

    # --- Этап 2: Регистрация тендера и получение ID из БД ---
    success, db_id, lot_ids_map = _register_tender(processed_data)

    if not success:
        log.error(
            "Не удалось зарегистрировать тендер и резервный режим отключен. Обработка прервана."
        )
        return

    is_temp_id = str(db_id).startswith("temp_")
    if is_temp_id:
        log.warning(f"Работаем с временными ID. Тендер: {db_id}")
        log.warning(
            "Файлы будут созданы с временными именами и помещены в директорию pending_sync"
        )
    else:
        log.info(f"Тендер успешно зарегистрирован. ID из БД: {db_id}")

    log.info("Продолжаем генерацию артефактов.")

    # --- Этап 3: Генерация всех локальных артефактов ---
    base_name = str(db_id)
    output_dir = source_path.parent

    try:
        log.info("Этап 3: Генерация артефактов...")

        # 3.1 Сохраняем основной JSON
        output_json_path = output_dir / f"{base_name}.json"
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4)
        log.info(f"Основной JSON сохранен в: {output_json_path.name}")

        # 3.2 Генерируем словарь с MD-документами для каждого лота
        lot_markdowns, initial_tender_metadata = generate_markdown_for_lots(
            processed_data
        )

        # 3.3 Создаем MD и чанки для каждого лота
        generated_md_paths, generated_chunks_paths = _generate_lot_artifacts(
            lot_markdowns, lot_ids_map, base_name, output_dir, initial_tender_metadata
        )

        # 3.4 Генерация детализированных отчетов по позициям
        position_reports_paths: List[Path] = []
        if lot_ids_map:
            position_reports_paths = generate_reports_for_all_lots(
                processed_data, output_dir, base_name, lot_ids_map
            )
            log.info("Детализированные MD-отчеты по позициям сгенерированы.")

    except Exception:
        log.exception("Произошла ошибка во время генерации локальных артефактов.")
        return

    # --- Этап 4: Архивирование всех файлов ---
    try:
        _archive_generated_files(
            source_path,
            output_json_path,
            generated_md_paths,
            generated_chunks_paths,
            position_reports_paths,
            base_name,
            is_temp_id,
        )
    except Exception:
        log.exception("Ошибка при перемещении файлов в архив.")

    log.info(f"--- Обработка файла {xlsx_path} полностью завершена. ---\n")


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(
        description="Полный цикл обработки тендерного XLSX файла.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    cli_parser.add_argument(
        "xlsx_path", type=str, help="Путь к входному XLSX файлу тендерной документации."
    )

    args = cli_parser.parse_args()
    input_file = Path(args.xlsx_path)
    if not input_file.is_file():
        log.error(f"Входной XLSX файл не найден: {input_file.resolve()}")
    else:
        parse_file(args.xlsx_path)
