"""
parse.py: Полный цикл обработки тендерных данных из XLSX.

Этот скрипт является основной точкой входа для парсинга тендерной документации
из XLSX файлов, последующей постобработки извлеченных данных, сохранения
финального результата в структурированный JSON-файл, генерации Markdown-отчета,
и последующего разделения этого отчета на чанки для AI-приложений.

Процесс работы:
1.  Принимает два аргумента командной строки: путь к входному XLSX файлу и
    путь для сохранения основного выходного JSON файла.
2.  Загружает XLSX файл с помощью `openpyxl`.
3.  Последовательно вызывает функции из пакета `helpers` для извлечения
    различных блоков данных.
4.  Агрегирует эти данные в единую JSON-подобную структуру.
5.  Применяет функции постобработки из `helpers.postprocess`.
6.  Сохраняет итоговую обработанную JSON-структуру в указанный файл (например, `output.json`).
7.  Генерирует Markdown-отчет (список строк) и словарь с основной метаинформацией
    о тендере, используя модуль из `markdown_utils.json_to_markdown`.
    Markdown-отчет сохраняется в файл (например, `output.md`).
8.  Сгенерированный Markdown-текст (из памяти) и извлеченная основная метаинформация
    передаются в модуль `markdown_to_chunks.tender_chunker` для разделения на
    смысловые чанки, обогащенные этой метаинформацией.
9.  Эти чанки сохраняются в отдельный JSON-файл (например, `output_chunks.json`).

Предполагаемая структура проекта для корректной работы импортов:
-   `parse.py` (данный файл)
-   `constants.py`
-   `helpers/` (пакет с модулями парсинга и постобработки)
-   `markdown_utils/` (пакет с `json_to_markdown.py`)
-   `markdown_to_chunks/` (пакет с `tender_chunker.py`)

Запуск из командной строки:
    python parse.py <путь_к_xlsx_файлу> <путь_к_основному_json_файлу>

Пример:
    python parse.py ./data/tender.xlsx ./output/tender_data.json
    Будут созданы:
    - ./output/tender_data.json (основной обработанный JSON)
    - ./output/tender_data.md (Markdown-отчет)
    - ./output/tender_data_chunks.json (JSON с чанками из Markdown)
"""
import openpyxl
import json
import argparse
import os
from pathlib import Path
from typing import Dict, Any

# Импорт констант
from constants import JSON_KEY_EXECUTOR, JSON_KEY_LOTS

# Импорт вспомогательных модулей
from helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from helpers.read_headers import read_headers
# from helpers.read_contractors import read_contractors # Для отладки
from helpers.read_lots_and_boundaries import read_lots_and_boundaries
from helpers.read_executer_block import read_executer_block
from markdown_utils.json_to_markdown import json_to_markdown

# Импорт модуля для создания чанков
from markdown_to_chunks.tender_chunker import create_chunks_from_markdown_text


def parse_file(xlsx_path: str, output_json_base_path: str) -> None:
    """
    Основная функция для полного цикла обработки XLSX файла: парсинг,
    постобработка, сохранение JSON, генерация Markdown и создание текстовых чанков.

    Args:
        xlsx_path (str): Путь к входному XLSX файлу.
        output_json_base_path (str): Базовый путь и имя для сохранения выходного
            (обработанного) JSON файла. Markdown-отчет и JSON с чанками
            будут сохранены рядом с этим файлом с соответствующими суффиксами/расширениями.

    Returns:
        None: Функция выполняет операции ввода-вывода и выводит сообщения о статусе.

    Side effects:
        - Загружает XLSX файл.
        - Создает или перезаписывает следующие файлы (в директории output_json_base_path):
            1.  `<output_json_base_name>.json` (основной обработанный JSON)
            2.  `<output_json_base_name>.md` (Markdown-отчет)
            3.  `<output_json_base_name>_chunks.json` (JSON с текстовыми чанками)
        - Печатает в консоль сообщения о ходе выполнения и ошибках.
    """
    print(f"Начало обработки файла: {xlsx_path}")
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active
    except FileNotFoundError:
        print(f"ОШИБКА: Входной XLSX файл не найден: {xlsx_path}")
        return
    except Exception as e:
        print(f"ОШИБКА при загрузке XLSX файла '{xlsx_path}': {e}")
        return

    # --- Шаг 1 & 2: Первичный парсинг и агрегация данных ---
    print("Извлечение данных из XLSX...")
    parsed_data: Dict[str, Any] = {
        **read_headers(ws),
        JSON_KEY_EXECUTOR: read_executer_block(ws),
        JSON_KEY_LOTS: read_lots_and_boundaries(ws),
    }

    # --- Шаг 3: Постобработка данных ---
    print("Постобработка извлеченных данных...")
    processed_data = normalize_lots_json_structure(parsed_data)
    processed_data = replace_div0_with_null(processed_data)

    # --- Шаг 4: Сохранение основного JSON ---
    output_json_resolved_path = Path(output_json_base_path).resolve()
    try:
        output_json_resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_resolved_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4)
        print(f"Обработанный JSON успешно сохранен: {output_json_resolved_path}")
    except IOError as e:
        print(f"ОШИБКА при сохранении JSON файла '{output_json_resolved_path}': {e}")
        return

    # --- Шаг 5: Генерация Markdown-отчета и извлечение основной метаинформации ---
    print("Генерация Markdown-отчета и основной метаинформации...")
    # json_to_markdown теперь возвращает кортеж: (список_строк_md, словарь_метаданных)
    markdown_lines, initial_tender_metadata = json_to_markdown(processed_data)

    # --- Шаг 5.1: Сохранение Markdown-отчета в файл ---
    md_file_name = output_json_resolved_path.stem + ".md"
    md_file_resolved_path = output_json_resolved_path.with_name(md_file_name)
    try:
        with open(md_file_resolved_path, "w", encoding="utf-8") as f_md:
            f_md.write("\n".join(markdown_lines))
        print(f"Markdown-отчет успешно сохранен: {md_file_resolved_path}")
    except IOError as e:
        print(f"ОШИБКА при сохранении Markdown файла '{md_file_resolved_path}': {e}")

    # --- Шаг 6: Создание чанков из Markdown-строк с использованием основной метаинформации ---
    print("Создание текстовых чанков из сгенерированного Markdown...")
    try:
        markdown_content_str = "\n".join(markdown_lines)
        # Передаем извлеченные ранее initial_tender_metadata в функцию создания чанков
        tender_chunks = create_chunks_from_markdown_text(
            markdown_content_str,
            global_initial_metadata=initial_tender_metadata
        )

        chunks_file_name = output_json_resolved_path.stem + "_chunks.json"
        chunks_file_resolved_path = output_json_resolved_path.with_name(chunks_file_name)

        chunks_file_resolved_path.parent.mkdir(parents=True, exist_ok=True) # Убедимся, что директория есть
        with open(chunks_file_resolved_path, "w", encoding="utf-8") as f_chunks:
            json.dump(tender_chunks, f_chunks, ensure_ascii=False, indent=2)
        print(f"Текстовые чанки ({len(tender_chunks)} шт.) сохранены: {chunks_file_resolved_path}")

        # Сюда можно добавить следующий шаг: вызов функции очистки чанков (из Файла 15),
        # передав tender_chunks и сохранив результат в ..._chunks_cleaned.json
        # Например:
        # from some_module.chunk_cleaner import clean_and_parse_chunk_metadata
        # cleaned_chunks = clean_and_parse_chunk_metadata(tender_chunks)
        # ... (код сохранения cleaned_chunks) ...

    except Exception as e:
        print(f"ОШИБКА при создании или сохранении текстовых чанков: {e}")

    print("Обработка файла полностью завершена.")


if __name__ == "__main__":
    cli_parser = argparse.ArgumentParser(
        description="Парсер тендерного XLSX файла: JSON -> Markdown -> Чанки.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    cli_parser.add_argument(
        "xlsx_path",
        type=str,
        help="Путь к входному XLSX файлу тендерной документации."
    )
    cli_parser.add_argument(
        "output_json_base_path",
        type=str,
        help="Базовый путь и имя для выходного JSON файла (например, './output/tender_data').\n"
             "Будут созданы:\n"
             "  - <базовое_имя>.json (основной JSON)\n"
             "  - <базовое_имя>.md (Markdown-отчет)\n"
             "  - <базовое_имя>_chunks.json (JSON с чанками из Markdown)"
    )
    
    parsed_args = cli_parser.parse_args()

    input_file_path = Path(parsed_args.xlsx_path)
    if not input_file_path.is_file():
        print(f"ОШИБКА: Входной XLSX файл не найден: {input_file_path.resolve()}")
    else:
        parse_file(parsed_args.xlsx_path, parsed_args.output_json_base_path)