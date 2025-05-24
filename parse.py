"""
parse.py: Полный цикл обработки тендерных данных из XLSX.

Этот скрипт является основной точкой входа для парсинга тендерной документации
из XLSX файлов, последующей постобработки извлеченных данных, сохранения
финального результата в структурированный JSON-файл и генерации
Markdown-отчета на его основе.

Процесс работы:
1.  Принимает два аргумента командной строки: путь к входному XLSX файлу и
    путь для сохранения выходного JSON файла.
2.  Загружает XLSX файл с помощью `openpyxl`.
3.  Последовательно вызывает функции из пакета `helpers` для извлечения
    различных блоков данных: заголовков тендера, информации об исполнителе,
    данных о лотах и предложениях подрядчиков.
4.  Агрегирует эти данные в единую JSON-подобную структуру.
5.  Применяет функции постобработки из `helpers.postprocess` для нормализации
    структуры (например, обработка "Расчетной стоимости", аннотация разделов)
    и очистки данных (например, замена ошибок деления на ноль).
6.  Сохраняет итоговую обработанную JSON-структуру в указанный файл.
7.  Генерирует Markdown-отчет на основе этой JSON-структуры, используя модуль
    из `markdown_utils.json_to_markdown`, и сохраняет его рядом с JSON-файлом.

Предполагаемая структура проекта для корректной работы импортов:
-   `parse.py` (данный файл)
-   `constants.py` (в той же директории или в PYTHONPATH)
-   `helpers/` (пакет с вспомогательными модулями):
    -   `postprocess.py`
    -   `read_headers.py`
    -   `read_contractors.py`
    -   `read_lots_and_boundaries.py`
    -   `read_executer_block.py`
    -   ... (другие модули парсинга из helpers)
-   `markdown_utils/` (пакет с утилитами для Markdown):
    -   `json_to_markdown.py`

Запуск из командной строки:
    python parse.py <путь_к_xlsx_файлу> <путь_к_выходному_json_файлу>

Пример:
    python parse.py ./data/tender.xlsx ./output/tender_data.json
    (Markdown-файл будет сохранен как ./output/tender_data.md)
"""

import openpyxl
import json
import argparse
import os
from pathlib import Path # Для более удобной работы с путями
from typing import Dict, Any # Для аннотаций типов

# Импорт констант и вспомогательных модулей
# Предполагается, что constants.py находится в том же каталоге или доступен через PYTHONPATH
from constants import JSON_KEY_EXECUTOR, JSON_KEY_LOTS

# Предполагается, что пакеты helpers и markdown_utils находятся относительно parse.py
from helpers.postprocess import normalize_lots_json_structure, replace_div0_with_null
from helpers.read_headers import read_headers
# from helpers.read_contractors import read_contractors # Закомментировано, если отладочный print не нужен постоянно
from helpers.read_lots_and_boundaries import read_lots_and_boundaries
from helpers.read_executer_block import read_executer_block
from markdown_utils.json_to_markdown import json_to_markdown


def parse_file(xlsx_path: str, output_json_path: str) -> None:
    """
    Основная функция для парсинга XLSX файла, постобработки данных,
    сохранения результата в JSON и генерации Markdown-отчета.

    Выполняет следующие шаги:
    1.  Загрузка активного листа из XLSX файла (`data_only=True` для получения значений, а не формул).
    2.  Извлечение "сырых" данных: заголовков тендера, информации об исполнителе,
        данных по лотам (включая предложения подрядчиков).
    3.  Агрегация извлеченных данных в единую словарь Python.
    4.  Постобработка этого словаря:
        -   Нормализация структуры лотов и предложений (`normalize_lots_json_structure`).
        -   Замена строковых представлений ошибок деления на ноль на `None` (`replace_div0_with_null`).
    5.  Сохранение финальной, обработанной структуры в указанный JSON файл.
        При этом создается родительская директория для файла, если она не существует.
    6.  Генерация Markdown-отчета на основе этой финальной JSON-структуры с помощью
        `json_to_markdown` и сохранение его в .md файл (рядом с JSON-файлом).

    Args:
        xlsx_path (str): Путь к входному XLSX файлу.
        output_json_path (str): Путь для сохранения выходного (обработанного) JSON файла.
            Имя Markdown-файла будет автоматически сформировано на основе этого пути
            (то же имя, но с расширением .md, в той же директории).
    
    Returns:
        None: Функция не возвращает значений, но выполняет операции ввода-вывода
            (чтение XLSX, запись JSON и Markdown файлов) и выводит сообщения
            о статусе в консоль.

    Side effects:
        -   Загружает XLSX файл.
        -   Выполняет множество операций чтения с листа Excel.
        -   (Опционально) Может печатать отладочную информацию, если раскомментировать
            соответствующие строки (например, `print(read_contractors(ws))`).
        -   Создает или перезаписывает JSON файл по пути `output_json_path`.
        -   Создает или перезаписывает Markdown-файл в той же директории, что и
            `output_json_path`, с тем же базовым именем, но расширением .md.
        -   Печатает в консоль сообщения о пути сохранения файлов или об ошибках.
    """
    print(f"Начало обработки файла: {xlsx_path}")
    try:
        wb = openpyxl.load_workbook(xlsx_path, data_only=True)
        ws = wb.active # Работаем с активным листом
    except FileNotFoundError:
        print(f"Ошибка: Входной XLSX файл не найден по пути: {xlsx_path}")
        return
    except Exception as e:
        print(f"Ошибка при загрузке XLSX файла '{xlsx_path}': {e}")
        return
    
    # Отладочный вывод списка контрагентов (можно раскомментировать при необходимости)
    # from helpers.read_contractors import read_contractors # Импорт здесь, если используется только для отладки
    # print("Обнаруженные заголовки контрагентов (отладка):")
    # print(read_contractors(ws))
    
    # --- Шаг 1 & 2: Первичный парсинг и агрегация данных ---
    print("Извлечение данных из XLSX...")
    parsed_data: Dict[str, Any] = {
        # Объединение словаря из read_headers с остальными данными
        **read_headers(ws), 
        JSON_KEY_EXECUTOR: read_executer_block(ws),
        JSON_KEY_LOTS: read_lots_and_boundaries(ws),
    }
    
    # --- Шаг 3: Постобработка данных ---
    print("Постобработка извлеченных данных...")
    processed_data = normalize_lots_json_structure(parsed_data) # Модифицирует parsed_data "на месте"
    processed_data = replace_div0_with_null(processed_data)   # Возвращает новый или измененный объект
    
    # --- Шаг 4: Сохранение финального JSON ---
    output_json_resolved_path = Path(output_json_path).resolve()
    try:
        # Убедимся, что директория для сохранения существует
        output_json_resolved_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_json_resolved_path, "w", encoding="utf-8") as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=4) # Увеличен indent для лучшей читаемости JSON
        print(f"Обработанный JSON успешно сохранен: {output_json_resolved_path}")
    except IOError as e:
        print(f"Ошибка при сохранении JSON файла '{output_json_resolved_path}': {e}")
        return # Прерываем выполнение, если не удалось сохранить JSON

    # --- Шаг 5: Генерация и сохранение Markdown-отчета ---
    print("Генерация Markdown-отчета...")
    # Имя Markdown-файла формируется на основе пути к JSON-файлу
    md_file_path_str = os.path.splitext(str(output_json_resolved_path))[0] + ".md"
    md_file_resolved_path = Path(md_file_path_str).resolve()
    
    markdown_lines = json_to_markdown(processed_data) # json_to_markdown возвращает список строк

    try:
        # Директория для Markdown уже должна быть создана на шаге сохранения JSON,
        # но для надежности можно добавить md_file_resolved_path.parent.mkdir(...)
        with open(md_file_resolved_path, "w", encoding="utf-8") as f:
            f.write("\n".join(markdown_lines))
        print(f"Markdown-отчет успешно сохранен: {md_file_resolved_path}")
    except IOError as e:
        print(f"Ошибка при сохранении Markdown файла '{md_file_resolved_path}': {e}")
    
    print("Обработка завершена.")

# --- Блок выполнения скрипта при прямом запуске ---
if __name__ == "__main__":
    # Настройка парсера аргументов командной строки
    cli_parser = argparse.ArgumentParser(
        description="Парсер тендерного файла XLSX в JSON с последующей постобработкой и генерацией Markdown-отчета.",
        formatter_class=argparse.RawTextHelpFormatter # Для лучшего отображения help
    )
    cli_parser.add_argument(
        "xlsx_path",
        type=str,
        help="Путь к входному XLSX файлу тендерной документации."
    )
    cli_parser.add_argument(
        "output_json_path",
        type=str,
        help="Путь для сохранения итогового JSON файла. "
             "Markdown-отчет будет сохранен в той же директории с тем же именем (расширение .md)."
    )
    
    parsed_args = cli_parser.parse_args()

    # Проверка существования входного XLSX файла перед вызовом основной функции
    input_file = Path(parsed_args.xlsx_path)
    if not input_file.is_file():
        print(f"Ошибка: Входной XLSX файл не найден по указанному пути: {input_file.resolve()}")
    else:
        # Вызов основной функции обработки с переданными путями
        parse_file(parsed_args.xlsx_path, parsed_args.output_json_path)