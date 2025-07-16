"""
Модуль для парсинга данных одной строки подрядчика из листа Excel.

Предоставляет функцию, которая извлекает все значения, относящиеся к конкретному
подрядчику, из указанной строки. Функция учитывает количество колонок (colspan),
занимаемых подрядчиком, и на основе этого определяет, какие поля данных
ожидаются. Поддерживается создание вложенной структуры в результирующем словаре
для таких полей, как стоимость (например, "стоимость за единицу.материалы").
"""

from typing import List, Dict, Any
from openpyxl.worksheet.worksheet import Worksheet
from openpyxl.cell import Cell # Для аннотации типа списка ячеек

# Импорт необходимых констант для ключей JSON
from ..constants import (
    JSON_KEY_SUGGESTED_QUANTITY,
    JSON_KEY_UNIT_COST,
    JSON_KEY_MATERIALS,
    JSON_KEY_WORKS,
    JSON_KEY_INDIRECT_COSTS,
    JSON_KEY_TOTAL,
    JSON_KEY_TOTAL_COST,
    JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
    JSON_KEY_COMMENT_CONTRACTOR,
    JSON_KEY_DEVIATION_FROM_CALCULATED_COST
)

def parse_contractor_row(
    ws: Worksheet,
    row_index: int,
    contractor: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Извлекает значения, относящиеся к подрядчику, из одной строки листа Excel
    и возвращает их в виде словаря, поддерживающего вложенную структуру.

    На основе информации о начальной колонке подрядчика (`contractor["column_start"]`)
    и количестве занимаемых им колонок (`contractor["merged_shape"]["colspan"]`),
    функция определяет набор ожидаемых полей данных с помощью вложенной
    функции `get_column_keys`. Значения извлекаются из ячеек соответствующего
    диапазона в указанной строке. Затем функция `map_to_nested_dict`
    сопоставляет эти значения с ключами, создавая вложенный словарь,
    если это определено структурой ключей (через точку).

    Args:
        ws (Worksheet): Рабочий лист openpyxl (объект Worksheet),
            из которого считываются данные.
        row_index (int): Номер строки (1-индексация), из которой извлекаются значения.
        contractor (Dict[str, Any]): Словарь с метаданными подрядчика. Должен содержать:
            - "column_start" (int): Номер начальной колонки данных для этого подрядчика.
            - "merged_shape" (Dict[str, int]): Словарь, содержащий ключ "colspan" (int),
              указывающий количество колонок, занимаемых данными подрядчика.

    Returns:
        Dict[str, Any]: Словарь с данными подрядчика для указанной строки.
            Ключи словаря соответствуют полям данных (например,
            `JSON_KEY_SUGGESTED_QUANTITY`, `JSON_KEY_COMMENT_CONTRACTOR`).
            Некоторые ключи могут быть вложенными, например, ключ
            f"{JSON_KEY_UNIT_COST}.{JSON_KEY_MATERIALS}" приведет к структуре:
            `{JSON_KEY_UNIT_COST: {JSON_KEY_MATERIALS: <значение>}}`.
            Значениями являются данные из соответствующих ячеек листа.

    Raises:
        ValueError: Если значение `contractor["merged_shape"]["colspan"]`
            не поддерживается (не равно 8, 9, 10, 11 или 12), исключение
            будет возбуждено из вложенной функции `get_column_keys`.
    """

    def get_column_keys(colspan: int) -> List[str]:
        """
        Возвращает упорядоченный список строковых ключей для полей данных подрядчика
        в зависимости от ширины блока (`colspan`), занимаемого подрядчиком.

        Ключи могут быть составными (разделенными точкой, например, "unit_cost.materials"),
        что указывает на необходимость создания вложенной структуры в результирующем словаре.
        Поддерживаемые значения `colspan`: 12, 11, 10, 9, 8. Порядок ключей в списке
        соответствует ожидаемому порядку колонок данных подрядчика.

        Args:
            colspan (int): Количество колонок, занимаемых данными подрядчика.

        Returns:
            List[str]: Список ключей.

        Raises:
            ValueError: Если переданное значение `colspan` не поддерживается
                (не входит в диапазон 8-12).
        """
        # Ключи формируются с использованием f-строк для создания вложенной структуры
        # там, где это необходимо (например, для unit_cost и total_cost).
        uc_mat = f"{JSON_KEY_UNIT_COST}.{JSON_KEY_MATERIALS}"
        uc_wrk = f"{JSON_KEY_UNIT_COST}.{JSON_KEY_WORKS}"
        uc_ind = f"{JSON_KEY_UNIT_COST}.{JSON_KEY_INDIRECT_COSTS}"
        uc_tot = f"{JSON_KEY_UNIT_COST}.{JSON_KEY_TOTAL}"
        
        tc_mat = f"{JSON_KEY_TOTAL_COST}.{JSON_KEY_MATERIALS}"
        tc_wrk = f"{JSON_KEY_TOTAL_COST}.{JSON_KEY_WORKS}"
        tc_ind = f"{JSON_KEY_TOTAL_COST}.{JSON_KEY_INDIRECT_COSTS}"
        tc_tot = f"{JSON_KEY_TOTAL_COST}.{JSON_KEY_TOTAL}"

        if colspan == 12:
            return [
                JSON_KEY_SUGGESTED_QUANTITY,
                uc_mat, uc_wrk, uc_ind, uc_tot,
                tc_mat, tc_wrk, tc_ind, tc_tot,
                JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
                JSON_KEY_COMMENT_CONTRACTOR,
                JSON_KEY_DEVIATION_FROM_CALCULATED_COST
            ]
        elif colspan == 11:
            return [
                JSON_KEY_SUGGESTED_QUANTITY,
                uc_mat, uc_wrk, uc_ind, uc_tot,
                tc_mat, tc_wrk, tc_ind, tc_tot,
                JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
                # JSON_KEY_COMMENT_CONTRACTOR - отсутствует для colspan 11
                JSON_KEY_DEVIATION_FROM_CALCULATED_COST
            ]
        elif colspan == 10:
            return [
                uc_mat, uc_wrk, uc_ind, uc_tot,
                tc_mat, tc_wrk, tc_ind, tc_tot,
                JSON_KEY_COMMENT_CONTRACTOR,
                JSON_KEY_DEVIATION_FROM_CALCULATED_COST
            ]
        elif colspan == 9:
            return [
                uc_mat, uc_wrk, uc_ind, uc_tot,
                tc_mat, tc_wrk, tc_ind, tc_tot,
                JSON_KEY_DEVIATION_FROM_CALCULATED_COST
            ]
        elif colspan == 8:
            return [
                uc_mat, uc_wrk, uc_ind, uc_tot,
                tc_mat, tc_wrk, tc_ind, tc_tot
            ]
        else:
            raise ValueError(
                f"Неподдерживаемый colspan подрядчика: {colspan}. Ожидались значения 8, 9, 10, 11 или 12."
            )

    def map_to_nested_dict(cells: List[Cell], keys: List[str]) -> Dict[str, Any]:
        """
        Сопоставляет список объектов ячеек (`cells`) со списком ключей (`keys`)
        и создает вложенный словарь на основе значений этих ячеек.

        Если ключ в списке `keys` содержит точку (например, "a.b.c"),
        создается соответствующая вложенная структура словарей. Значения
        извлекаются из атрибута `.value` каждого объекта ячейки.

        Args:
            cells (List[Cell]): Список объектов ячеек (openpyxl.cell.Cell),
                значения которых будут использоваться. Длина списка должна
                совпадать с длиной списка `keys`.
            keys (List[str]): Список строковых ключей, соответствующий ячейкам.

        Returns:
            Dict[str, Any]: Вложенный словарь, где значения из `cells` сопоставлены
                ключам из `keys`.
        """
        result_dict: Dict[str, Any] = {}
        for key_str, cell_obj in zip(keys, cells):
            key_parts = key_str.split(".")
            current_level_dict = result_dict
            # Проходим по частям ключа, создавая вложенные словари при необходимости
            for part in key_parts[:-1]:
                # setdefault создает ключ с пустым словарем, если его нет, и возвращает его
                current_level_dict = current_level_dict.setdefault(part, {})
            # Присваиваем значение ячейки последней части ключа на текущем уровне вложенности
            current_level_dict[key_parts[-1]] = cell_obj.value
        return result_dict

    # ----- Основная логика функции parse_contractor_row -----
    contractor_col_start: int = contractor["column_start"]
    contractor_colspan: int = contractor["merged_shape"]["colspan"]
    
    # Получаем список ключей JSON, соответствующий colspan данного подрядчика
    list_of_keys = get_column_keys(contractor_colspan)

    # Извлекаем объекты ячеек (Cell) подрядчика из указанной строки
    # Диапазон колонок: от contractor_col_start до contractor_col_start + contractor_colspan - 1
    cells_to_parse: List[Cell] = [
        ws.cell(row=row_index, column=col_idx)
        for col_idx in range(contractor_col_start, contractor_col_start + contractor_colspan)
    ]
    
    # Гарантируется, что get_column_keys вернет список ключей,
    # длина которого равна colspan, если colspan поддерживается.
    # Если colspan не поддерживается, get_column_keys вызовет ValueError.

    # Создаем вложенный словарь из значений ячеек и соответствующих ключей
    return map_to_nested_dict(cells_to_parse, list_of_keys)