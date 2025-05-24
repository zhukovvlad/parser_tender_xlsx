"""
postprocess.py

Модуль для постобработки JSON-данных, полученных после парсинга тендерной
документации из Excel. Включает функции для:
- Нормализации структуры лотов и предложений подрядчиков, включая обработку
  "Расчетной стоимости" и связанных с ней полей.
- Рекурсивной замены строковых представлений ошибок деления на ноль на `None`.
- Аннотации детализированных позиций полями для иерархического представления
  (например, указание на принадлежность к разделу).

Эти функции применяются к JSON-структуре после ее первоначального формирования
для очистки, стандартизации и обогащения данных перед их сохранением или
дальнейшим использованием.
"""

from typing import Dict, Any, List, Optional # Union можно добавить, если уточнять тип для replace_div0_with_null

# Импорт констант, используемых в модуле
from constants import (
    JSON_KEY_BASELINE_PROPOSAL,
    JSON_KEY_CHAPTER_NUMBER,             # Используется в annotate_structure_fields
    JSON_KEY_CONTRACTOR_ADDITIONAL_INFO, # Используется в normalize_lots_json_structure
    JSON_KEY_CONTRACTOR_INDEX,           # Используется в normalize_lots_json_structure
    JSON_KEY_CONTRACTOR_ITEMS,           # Используется в normalize_lots_json_structure
    JSON_KEY_CONTRACTOR_POSITIONS,       # Используется в normalize_lots_json_structure
    JSON_KEY_CONTRACTOR_SUMMARY,         # Используется в normalize_lots_json_structure
    JSON_KEY_CONTRACTOR_TITLE,           # Используется в normalize_lots_json_structure
    JSON_KEY_DEVIATION_FROM_CALCULATED_COST, # Используется в normalize_lots_json_structure
    JSON_KEY_LOTS,                       # Используется в normalize_lots_json_structure
    JSON_KEY_PROPOSALS,                  # Используется в normalize_lots_json_structure
    JSON_KEY_TOTAL_COST,                 # Используется в normalize_lots_json_structure (вместо JSON_FILL_TOTAL_COST)
    TABLE_PARSE_BASELINE_COST            # Используется в normalize_lots_json_structure
)
# JSON_FILL_TOTAL_COST больше не импортируется, так как normalize_lots_json_structure был обновлен.

def normalize_lots_json_structure(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Нормализует структуру данных по лотам в JSON-объекте, обрабатывая
    специальное предложение "Расчетная стоимость" и корректируя другие предложения.

    Основные операции для каждого лота в `data[JSON_KEY_LOTS]`:
    1.  Идентифицирует предложение "Расчетная стоимость" (далее `baseline`)
        среди всех предложений (`lot[JSON_KEY_PROPOSALS]`) по его имени,
        сравнивая с `TABLE_PARSE_BASELINE_COST` (без учета регистра и пробелов).
    2.  Если `baseline` найден:
        a.  Из него удаляется поле, указанное ключом `JSON_KEY_CONTRACTOR_ADDITIONAL_INFO`.
        b.  Проверяется валидность `baseline` на основе суммарных стоимостей в его
            `items[JSON_KEY_CONTRACTOR_SUMMARY][ключ_итога][JSON_KEY_TOTAL_COST]`.
            `baseline_is_valid = True`, если найдена хотя бы одна ненулевая стоимость.
    3.  Если `baseline_is_valid` истинно:
        -   `lot[JSON_KEY_BASELINE_PROPOSAL]` устанавливается в обработанный `baseline`.
    4.  Если `baseline_is_valid` ложно (т.е. `baseline` не найден, или "пуст" по стоимостям):
        -   `lot[JSON_KEY_BASELINE_PROPOSAL]` устанавливается в
            `{JSON_KEY_CONTRACTOR_TITLE: "Расчетная стоимость отсутствует"}`.
        -   У всех остальных ("реальных") подрядчиков в данном лоте:
            -   Из каждой их детализированной позиции (`items[JSON_KEY_CONTRACTOR_POSITIONS]`)
                удаляется поле, указанное ключом `JSON_KEY_DEVIATION_FROM_CALCULATED_COST`.
            -   Из словаря их итоговых строк (`items[JSON_KEY_CONTRACTOR_SUMMARY]`) удаляется
                запись с ключом `JSON_KEY_DEVIATION_FROM_CALCULATED_COST`.
    5.  Остальные предложения (не "Расчетная стоимость") копируются в новый
        словарь, и их ключи переиндексируются с использованием `JSON_KEY_CONTRACTOR_INDEX`
        (например, "contractor_1"). Этот новый словарь заменяет исходное
        содержимое `lot[JSON_KEY_PROPOSALS]`.
    6.  Ко всем детализированным позициям (`items[JSON_KEY_CONTRACTOR_POSITIONS]`) каждого
        "реального" подрядчика применяется функция `annotate_structure_fields`
        для добавления полей иерархии ("is_chapter", "chapter_ref").

    Функция модифицирует исходный словарь `data` на месте (in-place).

    Args:
        data (Dict[str, Any]): Входной словарь с данными. Ожидается, что он содержит
            ключ `JSON_KEY_LOTS`, значение которого - словарь лотов. Каждый лот
            должен содержать ключ `JSON_KEY_PROPOSALS`. Каждое предложение в
            `proposals` должно иметь ключ `JSON_KEY_CONTRACTOR_TITLE`.

    Returns:
        Dict[str, Any]: Модифицированный исходный словарь `data`.
    """
    lots_data = data.get(JSON_KEY_LOTS, {})

    for lot_key, lot_content in lots_data.items():
        proposals_in_lot = lot_content.get(JSON_KEY_PROPOSALS, {})
        actual_proposals: Dict[str, Any] = {} # Для "реальных" предложений подрядчиков
        baseline_proposal: Optional[Dict[str, Any]] = None 
        contractor_idx = 1 # Счетчик для переиндексации "реальных" подрядчиков

        # Разделение предложений на "baseline" и остальные
        for _, proposal_data in proposals_in_lot.items():
            name = str(proposal_data.get(JSON_KEY_CONTRACTOR_TITLE, "")).strip().lower()
            if name == TABLE_PARSE_BASELINE_COST:
                baseline_proposal = proposal_data
            else:
                actual_proposals[f"{JSON_KEY_CONTRACTOR_INDEX}{contractor_idx}"] = proposal_data
                contractor_idx += 1
        
        baseline_is_valid = False
        if baseline_proposal:
            # Удаляем дополнительную информацию из baseline, если она там есть
            baseline_proposal.pop(JSON_KEY_CONTRACTOR_ADDITIONAL_INFO, None)

            summary_data = baseline_proposal.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_SUMMARY, {})
            total_values_from_summary: List[Any] = []

            # Проверяем, есть ли непустые значения в итоговых стоимостях baseline
            for summary_item_block in summary_data.values():
                if isinstance(summary_item_block, dict): # Убедимся, что это словарь
                    # Используем JSON_KEY_TOTAL_COST согласно последнему обновлению
                    total_cost_detail = summary_item_block.get(JSON_KEY_TOTAL_COST, {})
                    if isinstance(total_cost_detail, dict):
                        current_block_total_values = total_cost_detail.values()
                        total_values_from_summary.extend(current_block_total_values)
            
            if total_values_from_summary: 
                baseline_is_valid = any(
                    val not in (None, 0, "0", "0.0", "", "0,0") and \
                    not (isinstance(val, str) and val.strip().lower() in {"0", "0.0", "0,0", "none"})
                    for val in total_values_from_summary
                )
        
        if baseline_is_valid and baseline_proposal is not None:
            lot_content[JSON_KEY_BASELINE_PROPOSAL] = baseline_proposal
        else: 
            lot_content[JSON_KEY_BASELINE_PROPOSAL] = {JSON_KEY_CONTRACTOR_TITLE: "Расчетная стоимость отсутствует"}
            # Если baseline невалиден, удаляем поля отклонений у других подрядчиков
            for contractor_proposal in actual_proposals.values():
                items_data = contractor_proposal.get(JSON_KEY_CONTRACTOR_ITEMS, {})
                
                positions_data = items_data.get(JSON_KEY_CONTRACTOR_POSITIONS, {})
                for pos_item in positions_data.values():
                    if isinstance(pos_item, dict):
                        pos_item.pop(JSON_KEY_DEVIATION_FROM_CALCULATED_COST, None)

                summary_for_contractor = items_data.get(JSON_KEY_CONTRACTOR_SUMMARY, {})
                if isinstance(summary_for_contractor, dict) : # Убедимся, что это словарь
                    summary_for_contractor.pop(JSON_KEY_DEVIATION_FROM_CALCULATED_COST, None)
        
        # Аннотируем позиции для всех "реальных" подрядчиков
        for contractor_proposal in actual_proposals.values():
            positions_to_annotate = contractor_proposal.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_POSITIONS, {})
            if positions_to_annotate and isinstance(positions_to_annotate, dict):
                annotate_structure_fields(positions_to_annotate)
        
        lot_content[JSON_KEY_PROPOSALS] = actual_proposals # Заменяем исходные предложения на переиндексированные "реальные"
    return data


def replace_div0_with_null(data: Any) -> Any:
    """
    Рекурсивно обходит вложенную структуру данных (словари, списки) и заменяет
    строковые значения, представляющие ошибки деления на ноль, на значение Python `None`.

    Обрабатывает строки без учета регистра и удаляет начальные/конечные пробелы
    перед сравнением.

    Args:
        data (Any): Входные данные для обработки. Это может быть словарь,
            список, строка или любой другой тип данных.

    Returns:
        Any: Новая структура данных того же типа, что и входная (если это
            словарь или список), где все строковые представления ошибок
            деления на ноль (например, 'DIV/0', '#DIV/0!', 'деление на 0')
            заменены на `None`. Строки, не являющиеся ошибками, и данные
            других типов возвращаются без изменений.
    """
    if isinstance(data, dict):
        return {k: replace_div0_with_null(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [replace_div0_with_null(item) for item in data]
    elif isinstance(data, str):
        normalized_data = data.strip().lower()
        # Список строк, считающихся ошибками деления на ноль.
        # Можно вынести в константы, если список часто меняется или используется в других местах.
        div_zero_error_strings = {"div/0", "#div/0!", "деление на 0"}
        if normalized_data in div_zero_error_strings:
            return None
        return data  # Возвращаем исходную строку, если это не ошибка
    else:
        return data # Возвращаем данные других типов без изменений


def annotate_structure_fields(positions: Dict[str, Dict[str, Any]]) -> None:
    """
    Добавляет поля "is_chapter" (bool) и "chapter_ref" (Optional[str]) в каждую
    позицию словаря `positions`. Модифицирует словарь `positions` на месте.

    "is_chapter" устанавливается в `True`, если у позиции (словаря `pos_item`)
    присутствует и заполнено поле, указанное ключом `JSON_KEY_CHAPTER_NUMBER`.
    "chapter_ref" содержит ссылку на номер родительского раздела (например, "1"
    для подраздела "1.1") или `None` для разделов верхнего уровня. Для позиций,
    не являющихся разделами, "chapter_ref" указывает на текущий активный раздел.

    Перед обработкой позиции сортируются по их числовым ключам (порядковым номерам,
    преобразованным в `int`) для корректного определения текущего раздела и
    ссылок на родительские разделы.

    Args:
        positions (Dict[str, Dict[str, Any]]): Словарь позиций, где ключи - это
            строковые представления порядковых номеров (например, "1", "2"),
            а значения - словари, описывающие позиции. Ожидается, что каждая
            позиция-словарь может содержать ключ `JSON_KEY_CHAPTER_NUMBER`.

    Returns:
        None: Функция модифицирует словарь `positions` на месте.

    Side effects:
        - Печатает предупреждение в консоль, если ключи позиций не могут быть
          преобразованы в `int` для сортировки, что может нарушить логику
          определения `chapter_ref`.
    """
    if not isinstance(positions, dict):
        # Если positions не словарь (например, None или пустой), ничего не делаем.
        return

    try:
        # Сортируем элементы (пары ключ-значение) по ключу, преобразованному в int.
        # Это важно для правильного отслеживания текущего раздела.
        sorted_items: List[tuple[str, Dict[str, Any]]] = sorted(
            positions.items(), key=lambda item_tuple: int(item_tuple[0])
        )
    except ValueError:
        # Обработка случая, если ключи не могут быть преобразованы в int.
        # В этом случае порядок обработки не гарантирован, что может повлиять на chapter_ref.
        print(
            f"ПРЕДУПРЕЖДЕНИЕ (annotate_structure_fields): Не удалось отсортировать позиции по числовым ключам: "
            f"{list(positions.keys())}. Логика 'chapter_ref' может быть нарушена."
        )
        sorted_items = list(positions.items()) # Обрабатываем в том порядке, какой есть

    current_chapter_number: Optional[str] = None # Хранит номер текущего активного раздела/главы

    for _, pos_item_dict in sorted_items: 
        if not isinstance(pos_item_dict, dict): 
            continue # Пропускаем, если элемент не является словарем

        section_num_val = pos_item_dict.get(JSON_KEY_CHAPTER_NUMBER)
        is_chapter_flag = bool(section_num_val) # True, если номер раздела есть и не пустой
        
        pos_item_dict["is_chapter"] = is_chapter_flag

        if is_chapter_flag:
            # Это строка раздела/главы
            current_chapter_number = str(section_num_val) # Обновляем текущий активный раздел
            if "." in current_chapter_number: # Проверяем, является ли это подразделом (например, "1.1")
                parent_chapter_parts = current_chapter_number.split(".")[:-1]
                pos_item_dict["chapter_ref"] = ".".join(parent_chapter_parts) # Ссылка на родительский раздел
            else:
                pos_item_dict["chapter_ref"] = None # Раздел верхнего уровня, нет родителя
        else:
            # Это обычная позиция, не раздел. Ссылается на текущий активный раздел.
            pos_item_dict["chapter_ref"] = current_chapter_number