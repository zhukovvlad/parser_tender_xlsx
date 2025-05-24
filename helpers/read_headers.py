"""
Модуль для извлечения заголовочной информации из листа Excel.

Этот модуль предоставляет функцию для считывания ключевых данных из
верхней части тендерного документа, таких как идентификатор и название тендера,
а также объект и адрес, к которым он относится. Поиск осуществляется
в предопределенном диапазоне строк по текстовым меткам.
"""

from typing import Dict, Optional, List
from openpyxl.worksheet.worksheet import Worksheet

# Импорт констант, используемых для ключей JSON и поиска текстовых маркеров
from constants import (
    JSON_KEY_TENDER_ADDRESS,
    JSON_KEY_TENDER_ID,
    JSON_KEY_TENDER_OBJECT,
    JSON_KEY_TENDER_TITLE,
    TABLE_PARSE_ADDRESS,
    TABLE_PARSE_OBJECT,
    TABLE_PARSE_TENDER_SUBJECT
)

def read_headers(ws: Worksheet) -> Dict[str, Optional[str]]:
    """
    Извлекает заголовочную информацию (ID тендера, название тендера,
    объект и адрес) из предопределенных строк (3-5 включительно) листа Excel.

    Функция сканирует строки с 3-й по 5-ю. В каждой строке она ищет
    текстовые метки (например, "Предмет тендера:", "Объект", "Адрес",
    определенные в константах `TABLE_PARSE_*`). Поиск меток регистрозависим.
    Соответствующие значения извлекаются из следующей непустой ячейки
    в той же строке.

    Предполагается следующая структура в строках 3-5:
    - Каждая часть заголовочной информации (предмет, объект, адрес) находится
      на отдельной строке.
    - Текстовая метка является первым непустым значением в строке.
    - Соответствующее искомое значение является вторым непустым значением в той же строке.

    Для "Предмета тендера", значение далее разбирается на ID и Название:
    - ID извлекается из начала строки значения (префикс "№" удаляется).
    - Название - это оставшаяся часть строки после ID и первого пробела.
    - Если пробела после ID нет, вся строка (после извлечения ID) считается Названием.

    Args:
        ws (Worksheet): Лист Excel (объект openpyxl.worksheet.worksheet.Worksheet),
            из которого считываются данные.

    Returns:
        Dict[str, Optional[str]]: Словарь, содержащий извлеченную заголовочную
            информацию. Ключи словаря соответствуют константам `JSON_KEY_*`:
            `JSON_KEY_TENDER_ID`, `JSON_KEY_TENDER_TITLE`,
            `JSON_KEY_TENDER_OBJECT`, `JSON_KEY_TENDER_ADDRESS`.
            Если какая-либо часть информации не найдена или пуста после очистки,
            соответствующее значение в словаре будет `None`.

    Пример возвращаемого значения:
        {
            "tender_id": "12345",
            "tender_title": "Закупка оборудования и ПО",
            "tender_object": "Здание административно-бытового корпуса",
            "tender_address": "г. Пример, ул. Тестовая, д. 1, стр. 2"
        }
    """
    header_data: Dict[str, Optional[str]] = {
        JSON_KEY_TENDER_ID: None,
        JSON_KEY_TENDER_TITLE: None,
        JSON_KEY_TENDER_OBJECT: None,
        JSON_KEY_TENDER_ADDRESS: None
    }

    # Сканируем строки с 3-й по 5-ю (1-индексация в Excel)
    for row_num in range(3, 6):
        # Собираем все непустые строковые значения из текущей строки
        current_row_non_empty_values: List[str] = []
        for cell in ws[row_num]: # ws[row_num] - это кортеж ячеек (Cell) строки
            if cell.value is not None:
                cell_str_value = str(cell.value).strip()
                if cell_str_value: # Добавляем, только если строка не пуста после strip()
                    current_row_non_empty_values.append(cell_str_value)
        
        if not current_row_non_empty_values:
            continue # Переходим к следующей строке, если текущая не содержит значащих данных

        first_cell_text = current_row_non_empty_values[0] # Текст из первой непустой ячейки

        # Обработка "Предмет тендера"
        if first_cell_text.startswith(TABLE_PARSE_TENDER_SUBJECT): # Например, "Предмет тендера:"
            if len(current_row_non_empty_values) > 1:
                tender_details_full_str = current_row_non_empty_values[1]
                parts = tender_details_full_str.split(" ", 1) # Разделяем по первому пробелу
                
                id_candidate = parts[0].replace("№", "").strip()
                header_data[JSON_KEY_TENDER_ID] = id_candidate if id_candidate else None

                if len(parts) > 1: # Есть и ID, и название
                    title_candidate = parts[1].strip()
                    header_data[JSON_KEY_TENDER_TITLE] = title_candidate if title_candidate else None
                elif id_candidate: # Только ID, без пробела после него; используем ID как название
                                   # (соответствует поведению оригинального кода пользователя, где
                                   # `if " " not in tender_details: title = tender_details` )
                    header_data[JSON_KEY_TENDER_TITLE] = id_candidate
        
        # Обработка "Объект"
        elif first_cell_text.startswith(TABLE_PARSE_OBJECT): # Например, "Объект"
            if len(current_row_non_empty_values) > 1:
                object_text = current_row_non_empty_values[1].strip()
                header_data[JSON_KEY_TENDER_OBJECT] = object_text if object_text else None
        
        # Обработка "Адрес"
        elif first_cell_text.startswith(TABLE_PARSE_ADDRESS): # Например, "Адрес"
            if len(current_row_non_empty_values) > 1:
                address_text = current_row_non_empty_values[1].strip()
                header_data[JSON_KEY_TENDER_ADDRESS] = address_text if address_text else None

    return header_data