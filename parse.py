"""
parse.py

Основной управляющий скрипт для полного цикла обработки тендерных XLSX файлов.
Выполняет парсинг, постобработку данных, сохранение результатов в JSON и Markdown,
создание текстовых чанков для эмбеддингов, опциональную отправку данных на внешний
сервер и финальную сортировку всех файлов по целевым директориям.

Скрипт запускается из командной строки и принимает один аргумент: путь к XLSX файлу.
"""

import argparse
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

# --- Ваши импорты ---
from constants import JSON_KEY_EXECUTOR, JSON_KEY_LOTS
from helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from helpers.read_headers import read_headers
from helpers.read_lots_and_boundaries import read_lots_and_boundaries
from helpers.read_executer_block import read_executer_block
from markdown_utils.json_to_markdown import json_to_markdown
from markdown_to_chunks.tender_chunker import create_chunks_from_markdown_text
from json_to_server.send_json_to_go_server import send_json_to_go_server
from markdown_utils.positions_report import generate_reports_for_all_lots

load_dotenv() # Загружаем переменные окружения из .env файла

# Настройка логирования для вывода в консоль и в файл
log_dir = Path("logs")
os.makedirs(log_dir, exist_ok=True) # Создаем директорию, если ее нет

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        # Записываем лог в файл внутри новой директории
        logging.FileHandler(log_dir / "parser.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

def parse_file(xlsx_path: str) -> None:
    """Оркестрирует полный цикл обработки одного XLSX файла."""
    logging.info(f"--- Начало обработки файла: {xlsx_path} ---")

    # --- Шаг 0: Определение всех путей ---
    source_path = Path(xlsx_path).resolve()
    base_name = source_path.stem
    output_dir = source_path.parent

    output_json_path = output_dir / f"{base_name}.json"
    output_md_path = output_dir / f"{base_name}.md"
    output_chunks_json_path = output_dir / f"{base_name}_chunks.json"

    logging.info(f"Имя для выходных файлов: {base_name}")

    try:
        wb = openpyxl.load_workbook(source_path, data_only=True)
        ws_raw = wb.active
        if not isinstance(ws_raw, Worksheet):
            logging.error(f"Активный лист не является Worksheet: {type(ws_raw)}")
            return
        ws: Worksheet = ws_raw
    except Exception:
        logging.exception(f"Не удалось загрузить или получить активный лист из файла '{source_path}'.")
        return

    # --- Шаг 1 & 2: Первичный парсинг и Постобработка ---
    try:
        logging.info("Шаг 1 и 2: Извлечение и постобработка данных...")
        parsed_data: Dict[str, Any] = {
            **read_headers(ws),
            JSON_KEY_EXECUTOR: read_executer_block(ws),
            JSON_KEY_LOTS: read_lots_and_boundaries(ws),
        }
        processed_data = normalize_lots_json_structure(parsed_data)
        processed_data = replace_div0_with_null(processed_data)
        logging.info("Данные успешно извлечены и обработаны.")
    except Exception:
        logging.exception("Произошла критическая ошибка на этапе парсинга и постобработки.")
        return

    # --- Шаг 3: Сохранение основного JSON ---
    logging.info("Шаг 3: Сохранение основного JSON...")
    try:
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4)
        logging.info(f"JSON успешно сохранен: {output_json_path}")
    except IOError:
        logging.exception(f"Не удалось сохранить JSON файл по пути {output_json_path}.")
        return

    # --- Шаг 4: Отправка JSON на Go сервер (опционально) ---
    go_server_url = os.getenv("GO_SERVER_API_ENDPOINT")
    if go_server_url:
        logging.info("Шаг 4: Отправка данных на Go сервер...")
        go_server_api_key = os.getenv("GO_SERVER_API_KEY", "")
        send_success = send_json_to_go_server(processed_data, go_server_url, go_server_api_key)
        if send_success:
            logging.info("Данные успешно отправлены на Go сервер.")
        else:
            logging.warning("Не удалось отправить данные на Go сервер.")
    else:
        logging.info("Шаг 4: Пропуск отправки данных на сервер (GO_SERVER_API_ENDPOINT не задан).")

    # --- Шаг 5: Генерация всех Markdown-отчетов ---
    logging.info("Шаг 5: Генерация Markdown-отчетов...")
    markdown_content_str = ""
    initial_tender_metadata = {}
    position_reports_paths = []

    # 5.1 Основной MD-отчет
    try:
        markdown_lines, initial_tender_metadata = json_to_markdown(processed_data)
        markdown_content_str = "\n".join(markdown_lines)
        with open(output_md_path, "w", encoding="utf-8") as f_md:
            f_md.write(markdown_content_str)
        logging.info(f"Основной MD-отчет успешно сохранен: {output_md_path.name}")
    except Exception:
        logging.exception("Ошибка при генерации основного Markdown-отчета.")

    # 5.2 Детализированные MD-отчеты по позициям для каждого лота
    try:
        position_reports_paths = generate_reports_for_all_lots(processed_data, output_dir, base_name)
    except Exception:
        logging.exception("Ошибка при генерации детализированных отчетов по лотам.")

    # --- Шаг 6: Создание и сохранение чанков (из основного MD) ---
    if markdown_content_str:
        logging.info("Шаг 6: Создание и сохранение текстовых чанков...")
        try:
            tender_chunks = create_chunks_from_markdown_text(
                markdown_content_str,
                global_initial_metadata=initial_tender_metadata
            )
            with open(output_chunks_json_path, "w", encoding="utf-8") as f_chunks:
                json.dump(tender_chunks, f_chunks, ensure_ascii=False, indent=2)
            logging.info(f"Текстовые чанки ({len(tender_chunks)} шт.) сохранены в: {output_chunks_json_path.name}")
        except Exception:
            logging.exception("Ошибка при создании и сохранении чанков.")

    # --- Шаг 7: Перемещение всех файлов в целевые директории ---
    logging.info("Шаг 7: Перемещение обработанных файлов...")
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

        move_if_exists(source_path, target_dirs["xlsx"])
        move_if_exists(output_json_path, target_dirs["json"])
        move_if_exists(output_chunks_json_path, target_dirs["chunks"])

        # Перемещаем основной MD-отчет
        move_if_exists(output_md_path, target_dirs["md"])

        # Перемещаем отчеты по позициям
        for pos_report_path in position_reports_paths:
            move_if_exists(pos_report_path, target_dirs["positions"])

    except Exception:
        logging.exception("Ошибка при перемещении файлов в целевые директории.")

    logging.info(f"--- Обработка файла {xlsx_path} полностью завершена. ---\n")


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(
        description="Полный цикл обработки тендерного XLSX файла.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    cli_parser.add_argument(
        "xlsx_path",
        type=str,
        help="Путь к входному XLSX файлу тендерной документации.\n"
             "Выходные файлы будут созданы, а затем перемещены в целевые\n"
             "директории (tenders_xlsx, tenders_json и т.д.) в текущей папке."
    )
    
    args = cli_parser.parse_args()

    input_file = Path(args.xlsx_path)
    if not input_file.is_file():
        logging.error(f"Входной XLSX файл не найден: {input_file.resolve()}")
    else:
        parse_file(args.xlsx_path)
