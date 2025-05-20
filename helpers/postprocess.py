"""
postprocess.py

Модуль для постобработки JSON-данных, полученных после парсинга тендерной
документации. Включает функции для нормализации структуры лотов и предложений,
замены строковых ошибок на None и аннотации структурных полей в позициях.
"""

def normalize_lots_json_structure(data):
    """
    Нормализует структуру данных по лотам в JSON-объекте, обрабатывая
    специальное предложение "Расчетная стоимость" и корректируя другие предложения.

    Основные операции для каждого лота в `data['lots']`:
    1. Идентифицирует предложение "Расчетная стоимость" (далее `baseline`)
       среди всех предложений (`lot['proposals']`) по ключу 'name'
       (без учета регистра и пробелов).
    2. Если `baseline` найден:
       a. Из него удаляется поле "Дополнительная информация" (ключ на русском языке).
       b. Проверяется содержимое `baseline['items']['summary']`:
          - Собираются все значения из всех блоков "стоимость всего" внутри
            каждой строки `summary`.
          - Устанавливается флаг `baseline_is_valid = True`, если найден хотя бы
            один ненулевой/не-None элемент стоимости. Если все элементы нулевые/None
            или `summary` не содержит данных о стоимости, `baseline_is_valid = False`.
    3. Если `baseline_is_valid` истинно (т.е. `baseline` найден и содержит значимые стоимости):
       - `lot['baseline_proposal']` устанавливается в обработанный `baseline` (который
         содержит "items", но без "Дополнительная информация").
    4. Если `baseline_is_valid` ложно (т.е. `baseline` не найден, или найден, но
       признан "пустым" по стоимостям):
       - `lot['baseline_proposal']` устанавливается в
         `{"name": "Расчетная стоимость отсутствует"}`.
       - У всех остальных ("реальных") подрядчиков в данном лоте:
           - Из каждой их детализированной позиции (в `items['positions']`)
             удаляется поле `"отклонение от расчетной стоимости"` (ключ с маленькой "о").
           - Из словаря их итоговых строк (`items['summary']`) удаляется
             целиком запись (строка-ключ) с ключом `"Отклонение от расчетной стоимости"`
             (ключ с большой "О"), если такая запись существует.
    5. Остальные предложения (не "Расчетная стоимость") копируются в новый
       словарь, и их ключи переиндексируются в формат "contractor_1",
       "contractor_2" и т.д. Этот новый словарь заменяет исходное
       содержимое `lot['proposals']`.
    6. Ко всем детализированным позициям (`items['positions']`) каждого "реального"
       подрядчика (из `new_proposals`) применяется функция `annotate_structure_fields`
       для добавления полей иерархии.

    Функция модифицирует исходный словарь `data` на месте (in-place).

    Args:
        data (dict): Входной словарь с данными, предположительно содержащий
                     ключ "lots". Каждый лот в `data["lots"]` должен содержать
                     ключ "proposals". Каждое предложение в `proposals`
                     должно иметь ключ "name" и может содержать ключ "items",
                     который в свою очередь содержит словари "positions" и "summary".
                     Позиции могут содержать ключ "отклонение от расчетной стоимости"
                     (с маленькой "о"). Словарь `summary` у подрядчиков может
                     содержать ключ "Отклонение от расчетной стоимости" (с большой "О"),
                     значением которого является целая итоговая строка.


    Returns:
        dict: Модифицированный исходный словарь `data`.

    Примечания:
    - Если в одном лоте найдено несколько предложений с именем "расчетная стоимость",
      в качестве кандидата на `baseline` будет использовано последнее из них.
    """
    lots = data.get("lots", {})

    for lot_key, lot in lots.items():
        proposals = lot.get("proposals", {})
        new_proposals = {}
        baseline = None 
        index = 1

        for key, contractor_data_loop in proposals.items():
            name = contractor_data_loop.get("name", "").strip().lower()
            if name == "расчетная стоимость":
                baseline = contractor_data_loop
            else:
                new_proposals[f"contractor_{index}"] = contractor_data_loop
                index += 1

        baseline_is_valid = False

        if baseline:
            baseline.pop("Дополнительная информация", None)
            
            summary_data = baseline.get("items", {}).get("summary", {})
            total_values_from_summary = []

            for summary_item_block in summary_data.values():
                total_cost_data = summary_item_block.get("стоимость всего", {})
                current_block_total_values = total_cost_data.values() if isinstance(total_cost_data, dict) else []
                total_values_from_summary.extend(current_block_total_values)
            
            if total_values_from_summary: 
                baseline_is_valid = any(
                    val not in (None, 0, "0", "0.0", "", "0,0") and \
                    not (isinstance(val, str) and val.strip().lower() in {"0", "0.0", "0,0", "none"})
                    for val in total_values_from_summary
                )
        
        if baseline_is_valid: 
            lot["baseline_proposal"] = baseline
        else: 
            lot["baseline_proposal"] = {"name": "Расчетная стоимость отсутствует"}
            
            for actual_contractor_proposal in new_proposals.values():
                contractor_items = actual_contractor_proposal.get("items", {})

                positions_data = contractor_items.get("positions", {})
                for pos_item in positions_data.values():
                    if isinstance(pos_item, dict):
                        pos_item.pop("отклонение от расчетной стоимости", None)

                summary_data_contractor = contractor_items.get("summary", {})
                # Удаляем всю СТРОКУ "Отклонение от расчетной стоимости" (с большой "О")
                # из summary подрядчика, если она там есть как ключ.
                summary_data_contractor.pop("Отклонение от расчетной стоимости", None)
                                     
        # Применяем аннотацию ко всем "реальным" подрядчикам, независимо от статуса baseline
        for contractor_proposal_to_annotate in new_proposals.values():
            positions_to_annotate = contractor_proposal_to_annotate.get("items", {}).get("positions", {})
            if positions_to_annotate: 
                 annotate_structure_fields(positions_to_annotate)
                            
        lot["proposals"] = new_proposals
    return data

def replace_div0_with_null(data):
    """
    Рекурсивно обходит вложенную структуру данных (словари, списки) и заменяет
    строковые значения, представляющие ошибки деления на ноль (например,
    'DIV/0', '#DIV/0!', 'деление на 0'), на значение Python `None`.

    Функция не изменяет исходную структуру данных, а возвращает новую
    структуру с выполненными заменами.

    Args:
        data (any): Входные данные для обработки. Это может быть словарь,
                    список, строка или любой другой тип данных.

    Returns:
        any: Новая структура данных того же типа, что и входная (если это
             словарь или список), где все строковые представления ошибок
             деления на ноль заменены на `None`. Строки, не являющиеся
             ошибками, и данные других типов возвращаются без изменений.

    Примеры обрабатываемых строк (без учета регистра и пробелов):
    - "div/0"
    - "#div/0!"
    - "деление на 0"
    """
    if isinstance(data, dict):
        return {k: replace_div0_with_null(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [replace_div0_with_null(item) for item in data]
    elif isinstance(data, str):
        normalized_data = data.strip().lower()
        # DIV_ZERO_ERROR_STRINGS = {"div/0", "#div/0!", "деление на 0"} # Можно вынести в константу модуля
        if normalized_data in ("div/0", "#div/0!", "деление на 0"):
            return None
        return data
    else:
        return data

def annotate_structure_fields(positions):
    """
    Добавляет поля "is_chapter" (bool) и "chapter_ref" (str | None) в каждую
    позицию словаря `positions`. Модифицирует словарь `positions` на месте.

    "is_chapter" устанавливается в True, если у позиции есть поле "номер раздела".
    "chapter_ref" содержит ссылку на номер родительского раздела (например, "1"
    для раздела "1.1") или None для разделов верхнего уровня. Для позиций,
    не являющихся разделами, "chapter_ref" указывает на текущий активный раздел.

    Сортирует позиции по числовому ключу перед обработкой для корректного
    определения текущего раздела.

    Args:
        positions (dict): Словарь позиций, где ключи - это строковые
                          представления порядковых номеров (например, "1", "2"),
                          а значения - словари, описывающие позиции. Ожидается,
                          что каждая позиция-словарь может содержать ключ
                          "номер раздела".

    Returns:
        None: Функция модифицирует словарь `positions` на месте.
    """
    if not isinstance(positions, dict):
        # Можно добавить логирование или возврат ошибки, если это критично
        return

    try:
        # Сортируем элементы по ключу, преобразованному в int
        sorted_items = sorted(positions.items(), key=lambda x: int(x[0]))
    except ValueError:
        # Обработка случая, если ключи не могут быть преобразованы в int
        # В этом случае порядок обработки не гарантирован, что может повлиять на chapter_ref
        print(f"ПРЕДУПРЕЖДЕНИЕ (annotate_structure_fields): Не удалось отсортировать позиции по ключам: {list(positions.keys())}. Логика 'chapter_ref' может быть нарушена.")
        sorted_items = positions.items() # Обрабатываем в том порядке, какой есть

    current_chapter = None 

    for _, pos_item in sorted_items: 
        if not isinstance(pos_item, dict): 
            continue

        section_number = pos_item.get("номер раздела")
        is_chapter_flag = bool(section_number) 
        pos_item["is_chapter"] = is_chapter_flag

        if is_chapter_flag:
            current_chapter = section_number 
            if isinstance(section_number, str) and "." in section_number:
                parent_chapter_parts = section_number.split(".")[:-1]
                pos_item["chapter_ref"] = ".".join(parent_chapter_parts)
            else:
                pos_item["chapter_ref"] = None 
        else:
            pos_item["chapter_ref"] = current_chapter