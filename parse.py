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
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
import openpyxl

# --- Ваши импорты ---
from constants import JSON_KEY_EXECUTOR, JSON_KEY_LOTS
from helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from helpers.read_headers import read_headers
from helpers.read_lots_and_boundaries import read_lots_and_boundaries
from helpers.read_executer_block import read_executer_block
from markdown_utils.json_to_markdown import json_to_markdown
from markdown_to_chunks.tender_chunker import create_chunks_from_markdown_text
from json_to_server.send_json_to_go_server import send_json_to_go_server

load_dotenv() # Загружаем переменные окружения из .env файла

def parse_file(xlsx_path: str) -> None:
    """
    Оркестрирует полный цикл обработки одного XLSX файла.

    Процесс включает следующие шаги:
    1.  Парсинг данных из XLSX.
    2.  Постобработка данных (нормализация, очистка).
    3.  Сохранение финальных данных в JSON-файл.
    4.  Отправка JSON на внешний сервер (если настроен).
    5.  Генерация и сохранение Markdown-отчета.
    6.  Создание и сохранение текстовых чанков из Markdown в отдельный JSON-файл.
    7.  Перемещение исходного XLSX и всех сгенерированных артефактов
        в соответствующие директории (`tenders_xlsx/`, `tenders_json/` и т.д.).

    Args:
        xlsx_path (str): Абсолютный или относительный путь к входному XLSX файлу.

    Returns:
        None: Функция ничего не возвращает, но выполняет операции с файлами и выводит
              информацию о ходе выполнения в консоль.

    Side effects:
        - Создает следующие файлы в директории исходного XLSX файла (перед перемещением):
            - `<имя_файла>.json`: Финальный обработанный JSON.
            - `<имя_файла>.md`: Markdown-отчет.
            - `<имя_файла>_chunks.json`: JSON-файл со списком текстовых чанков.
        - Перемещает исходный XLSX и все созданные файлы в целевые директории.
        - Отправляет HTTP POST запрос на Go сервер, если задан GO_SERVER_API_ENDPOINT.
        - Выводит в консоль подробную информацию о статусе каждого шага.
    """
    print(f"--- Начало обработки файла: {xlsx_path} ---")

    # --- Шаг 0: Определение всех путей ---
    source_path = Path(xlsx_path).resolve()
    base_name = source_path.stem
    output_dir = source_path.parent

    output_json_path = output_dir / f"{base_name}.json"
    output_md_path = output_dir / f"{base_name}.md"
    # ИЗМЕНЕНИЕ: output_chunks_path теперь указывает на файл, а не на директорию
    output_chunks_json_path = output_dir / f"{base_name}_chunks.json"
    
    print(f"Имя для выходных файлов: {base_name}")

    try:
        wb = openpyxl.load_workbook(source_path, data_only=True)
        ws = wb.active
    except Exception as e:
        print(f"ОШИБКА на Шаге 0 (Загрузка XLSX): Не удалось загрузить файл '{source_path}'.\nДетали: {e}")
        return

    # --- Шаг 1 & 2: Первичный парсинг и Постобработка ---
    try:
        print("1. Извлечение и постобработка данных...")
        parsed_data: Dict[str, Any] = {
            **read_headers(ws),
            JSON_KEY_EXECUTOR: read_executer_block(ws),
            JSON_KEY_LOTS: read_lots_and_boundaries(ws),
        }
        processed_data = normalize_lots_json_structure(parsed_data)
        processed_data = replace_div0_with_null(processed_data)
        print("   -> Данные успешно извлечены и обработаны.")
    except (KeyError, ValueError, AttributeError) as e:
        print(f"ОШИБКА на Шаге 1/2 (Парсинг/Постобработка): {e}")
        return
    except Exception as e:
        print(f"НЕОЖИДАННАЯ ОШИБКА на Шаге 1/2 (Парсинг/Постобработка): {e}")
        return

    # --- Шаг 3: Сохранение основного JSON ---
    print("3. Сохранение основного JSON...")
    try:
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4)
        print(f"   -> JSON успешно сохранен: {output_json_path}")
    except IOError as e:
        print(f"ОШИБКА на Шаге 3 (Сохранение JSON): {e}")
        return

    # --- Шаг 4: Отправка JSON на Go сервер (опционально) ---
    go_server_url = os.getenv("GO_SERVER_API_ENDPOINT")
    if go_server_url:
        print(f"4. Отправка данных на Go сервер...")
        go_server_api_key = os.getenv("GO_SERVER_API_KEY")
        send_success = send_json_to_go_server(processed_data, go_server_url, go_server_api_key)
        if send_success:
            print("   -> Данные успешно отправлены на Go сервер.")
        else:
            print("   -> ПРЕДУПРЕЖДЕНИЕ: Не удалось отправить данные на Go сервер.")
    else:
        print("4. Пропуск отправки данных на сервер (GO_SERVER_API_ENDPOINT не задан).")

    # --- Шаг 5: Генерация и сохранение Markdown-отчета ---
    print("5. Генерация и сохранение Markdown-отчета...")
    markdown_content_str = "" # Инициализируем на случай ошибки
    try:
        markdown_lines, initial_tender_metadata = json_to_markdown(processed_data)
        # Убрано дублирование join
        markdown_content_str = "\n".join(markdown_lines) 
        with open(output_md_path, "w", encoding="utf-8") as f_md:
            f_md.write(markdown_content_str)
        print(f"   -> Markdown-отчет успешно сохранен: {output_md_path}")
    except (KeyError, ValueError, TypeError) as e:
        print(f"ОШИБКА на Шаге 5 (Генерация/сохранение Markdown): {e}")
    except Exception as e:
        print(f"НЕОЖИДАННАЯ ОШИБКА на Шаге 5 (Генерация/сохранение Markdown): {e}")

    # --- Шаг 6: Создание и сохранение чанков ---
    if markdown_content_str: # Выполняем чанкинг, только если MD был успешно сгенерирован
        print("6. Создание и сохранение текстовых чанков...")
        try:
            tender_chunks = create_chunks_from_markdown_text(
                markdown_content_str,
                global_initial_metadata=initial_tender_metadata
            )
            with open(output_chunks_json_path, "w", encoding="utf-8") as f_chunks:
                json.dump(tender_chunks, f_chunks, ensure_ascii=False, indent=2)
            print(f"   -> Текстовые чанки ({len(tender_chunks)} шт.) сохранены в JSON-файл: {output_chunks_json_path}")
        except (KeyError, ValueError, TypeError, IOError) as e:
            print(f"ОШИБКА на Шаге 6 (Создание/сохранение чанков): {e}")
        except Exception as e:
            print(f"НЕОЖИДАННАЯ ОШИБКА на Шаге 6 (Создание/сохранение чанков): {e}")

    # --- Шаг 7: Перемещение всех файлов в целевые директории ---
    print("7. Перемещение обработанных файлов...")
    try:
        # Определяем корневую директорию проекта, где будет запущен скрипт
        project_root = Path.cwd()
        target_dirs = {
            "xlsx": project_root / "tenders_xlsx",
            "json": project_root / "tenders_json",
            "md": project_root / "tenders_md",
            "chunks": project_root / "tenders_chunks"
        }

        for dir_path in target_dirs.values():
            try:
                os.makedirs(dir_path, exist_ok=True)
            except PermissionError:
                print(f"ОШИБКА: Недостаточно прав для создания директории {dir_path}")
                return
            except OSError as e:
                print(f"ОШИБКА: Не удалось создать директорию {dir_path}: {e}")
                return
            
        # Используем str() для shutil.move для лучшей совместимости
        shutil.move(str(source_path), str(target_dirs["xlsx"] / source_path.name))
        print(f"   -> XLSX перемещен в: {target_dirs['xlsx']}")

        # Перемещаем только существующие файлы, чтобы избежать ошибок
        if output_json_path.exists():
            shutil.move(str(output_json_path), str(target_dirs["json"] / output_json_path.name))
            print(f"   -> JSON перемещен в: {target_dirs['json']}")

        if output_md_path.exists():
            shutil.move(str(output_md_path), str(target_dirs["md"] / output_md_path.name))
            print(f"   -> MD перемещен в: {target_dirs['md']}")

        if output_chunks_json_path.exists():
            shutil.move(str(output_chunks_json_path), str(target_dirs["chunks"] / output_chunks_json_path.name))
            print(f"   -> Файл с чанками перемещен в: {target_dirs['chunks']}")
    
    except Exception as e:
        print(f"ОШИБКА на Шаге 7 (Перемещение файлов): {e}")

    print(f"--- Обработка файла {xlsx_path} полностью завершена. ---\n")


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
        print(f"ОШИБКА: Входной XLSX файл не найден: {input_file.resolve()}")
    else:
        parse_file(args.xlsx_path)