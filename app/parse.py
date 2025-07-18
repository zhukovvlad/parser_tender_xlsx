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
    - Основной MD-отчет (`{tender_db_id}.md`).
    - Файл с чанками для RAG (`{tender_db_id}_chunks.json`).
    - Детализированные MD-отчеты по позициям для каждого лота
      (`{tender_db_id}_{lot_db_id}_positions.md`).

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
from typing import Any, Dict, List

from dotenv import load_dotenv
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

# Используем относительные импорты
from .constants import JSON_KEY_EXECUTOR, JSON_KEY_LOTS
from .helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from .helpers.read_headers import read_headers
from .helpers.read_lots_and_boundaries import read_lots_and_boundaries
from .helpers.read_executer_block import read_executer_block
from .markdown_utils.json_to_markdown import json_to_markdown
from .markdown_to_chunks.tender_chunker import create_chunks_from_markdown_text
from .json_to_server.send_json_to_go_server import register_tender_in_go
from .markdown_utils.positions_report import generate_reports_for_all_lots

load_dotenv()

# Настройка логирования
log_dir = Path("logs")
os.makedirs(log_dir, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / "parser.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)


def parse_file(xlsx_path: str) -> None:
    """
    Оркестрирует полный цикл обработки одного тендерного XLSX-файла.

    Функция является основной точкой входа для конвейера обработки. Она
    выполняет последовательность шагов: извлекает данные из файла,
    регистрирует их в основной системе через вызов API, и в случае успеха
    генерирует все локальные артефакты (JSON, MD-отчеты, чанки) и
    перемещает их вместе с исходным файлом в архивные директории.

    Процесс прерывается, если на каком-либо из критических этапов
    (парсинг, регистрация в API) происходит ошибка.

    Args:
        xlsx_path (str): Абсолютный или относительный путь к входному
                         XLSX-файлу, который необходимо обработать.

    Returns:
        None: Функция ничего не возвращает. Результатом её работы являются
              созданные и перемещенные файлы, а также записи в логах.

    Side Effects:
        - Создает в файловой системе несколько файлов-артефактов.
        - Перемещает исходный XLSX-файл и созданные артефакты в другие директории.
        - Выполняет HTTP-запрос к внешнему API-серверу.
        - Записывает подробную информацию о ходе выполнения в лог-файл и консоль.
    """
    logging.info(f"--- Начало обработки файла: {xlsx_path} ---")
    source_path = Path(xlsx_path).resolve()

    # --- Этап 1: Парсинг XLSX в JSON ---
    try:
        logging.info("Этап 1: Извлечение данных из XLSX...")
        wb = openpyxl.load_workbook(source_path, data_only=True)
        ws: Worksheet = wb.active
        
        processed_data: Dict[str, Any] = {
            **read_headers(ws),
            JSON_KEY_EXECUTOR: read_executer_block(ws),
            JSON_KEY_LOTS: read_lots_and_boundaries(ws),
        }
        processed_data = normalize_lots_json_structure(processed_data)
        processed_data = replace_div0_with_null(processed_data)
        logging.info("Данные успешно извлечены.")
    except Exception:
        logging.exception(f"Критическая ошибка на этапе парсинга файла '{source_path}'.")
        return

    # --- Этап 2: Регистрация тендера и получение ID из БД ---
    go_server_url = os.getenv("GO_SERVER_API_ENDPOINT")
    if not go_server_url:
        logging.error("Переменная окружения GO_SERVER_API_ENDPOINT не задана. Обработка прервана.")
        return

    logging.info("Этап 2: Регистрация тендера на Go сервере...")
    go_server_api_key = os.getenv("GO_SERVER_API_KEY")
    
    # --- ИЗМЕНЕНИЕ: Получаем ID тендера и словарь с ID лотов ---
    success, db_id, lot_ids_map = register_tender_in_go(processed_data, go_server_url, go_server_api_key)

    if not success:
        logging.error("Не удалось зарегистрировать тендер. Генерация артефактов и архивация отменены.")
        return
        
    logging.info(f"Тендер успешно зарегистрирован. ID из БД: {db_id}. Продолжаем генерацию артефактов.")
    
    # --- Этап 3: Генерация всех локальных артефактов ---
    base_name = str(db_id)
    output_dir = source_path.parent
    
    output_json_path = output_dir / f"{base_name}.json"
    output_md_path = output_dir / f"{base_name}.md"
    output_chunks_json_path = output_dir / f"{base_name}_chunks.json"
    position_reports_paths: List[Path] = []

    try:
        logging.info(f"Этап 3: Генерация артефактов с базовым именем '{base_name}'...")
        
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4)
        logging.info(f"Основной JSON сохранен в: {output_json_path.name}")

        markdown_lines, initial_tender_metadata = json_to_markdown(processed_data)
        markdown_content_str = "\n".join(markdown_lines)
        with open(output_md_path, "w", encoding="utf-8") as f_md:
            f_md.write(markdown_content_str)
        logging.info(f"Основной MD-отчет сохранен в: {output_md_path.name}")

        # --- ИЗМЕНЕНИЕ: Передаем словарь с ID лотов в генератор отчетов ---
        position_reports_paths = generate_reports_for_all_lots(
            processed_data, 
            output_dir, 
            base_name, # ID тендера
            lot_ids_map  # Словарь с ID лотов
        )
        logging.info("Детализированные MD-отчеты по позициям сгенерированы.")

        if markdown_content_str:
            tender_chunks = create_chunks_from_markdown_text(
                markdown_content_str,
                global_initial_metadata=initial_tender_metadata
            )
            with open(output_chunks_json_path, "w", encoding="utf-8") as f_chunks:
                json.dump(tender_chunks, f_chunks, ensure_ascii=False, indent=2)
            logging.info(f"Текстовые чанки ({len(tender_chunks)} шт.) сохранены в: {output_chunks_json_path.name}")

    except Exception:
        logging.exception("Произошла ошибка во время генерации локальных артефактов.")
        return

    # --- Этап 4: Архивирование всех файлов ---
    logging.info("Этап 4: Перемещение всех файлов в целевые директории...")
    try:
        project_root = Path.cwd()
        target_dirs = {
            "xlsx": project_root / "tenders_xlsx",
            "json": project_root / "tenders_json",
            "md": project_root / "tenders_md",
            "chunks": project_root / "tenders_chunks",
            "positions": project_root / "tenders_positions"
        }
        for dir_path in target_dirs.values():
            os.makedirs(dir_path, exist_ok=True)

        def move_if_exists(src_path: Path, dest_dir: Path):
            if src_path.exists():
                shutil.move(str(src_path), str(dest_dir / src_path.name))
                logging.info(f"Файл '{src_path.name}' перемещен в: {dest_dir.name}")

        renamed_xlsx_path = output_dir / f"{base_name}.xlsx"
        source_path.rename(renamed_xlsx_path)
        
        move_if_exists(renamed_xlsx_path, target_dirs["xlsx"])
        move_if_exists(output_json_path, target_dirs["json"])
        move_if_exists(output_chunks_json_path, target_dirs["chunks"])
        move_if_exists(output_md_path, target_dirs["md"])
        for pos_report_path in position_reports_paths:
            move_if_exists(pos_report_path, target_dirs["positions"])

    except Exception:
        logging.exception("Ошибка при перемещении файлов в архив.")

    logging.info(f"--- Обработка файла {xlsx_path} полностью завершена. ---\n")


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(
        description="Полный цикл обработки тендерного XLSX файла.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    cli_parser.add_argument(
        "xlsx_path",
        type=str,
        help="Путь к входному XLSX файлу тендерной документации."
    )
    
    args = cli_parser.parse_args()
    input_file = Path(args.xlsx_path)
    if not input_file.is_file():
        logging.error(f"Входной XLSX файл не найден: {input_file.resolve()}")
    else:
        parse_file(args.xlsx_path)
