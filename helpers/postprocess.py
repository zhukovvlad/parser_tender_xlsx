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
       - У всех остальных ("реальных") подрядчиков в данном лоте из каждой их
         позиции (в `items['positions']`) и из каждой их итоговой строки
         (в `items['summary']`) удаляется поле "отклонение от расчетной стоимости".
    5. Остальные предложения (не "Расчетная стоимость") копируются в новый
       словарь, и их ключи переиндексируются в формат "contractor_1",
       "contractor_2" и т.д. Этот новый словарь заменяет исходное
       содержимое `lot['proposals']`.

    Функция модифицирует исходный словарь `data` на месте (in-place).

    Args:
        data (dict): Входной словарь с данными, предположительно содержащий
                     ключ "lots". Каждый лот в `data["lots"]` должен содержать
                     ключ "proposals". Каждое предложение (`contractor`) в
                     `proposals` должно иметь ключ "name" и может содержать
                     ключ "items", который в свою очередь содержит словари
                     "positions" и "summary". Позиции и итоговые строки могут
                     содержать ключ "отклонение от расчетной стоимости".

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

        for key, contractor_data_loop in proposals.items(): # Переименовал contractor во избежание путаницы с contractor ниже
            name = contractor_data_loop.get("name", "").strip().lower()
            if name == "расчетная стоимость":
                baseline = contractor_data_loop
            else:
                new_proposals[f"contractor_{index}"] = contractor_data_loop
                index += 1

        baseline_is_valid = False # Инициализируем как False

        if baseline:
            baseline.pop("Дополнительная информация", None)
            
            summary_data = baseline.get("items", {}).get("summary", {})
            total_values_from_summary = []

            for summary_item_block in summary_data.values():
                total_cost_data = summary_item_block.get("стоимость всего", {})
                current_block_total_values = total_cost_data.values() if isinstance(total_cost_data, dict) else []
                total_values_from_summary.extend(current_block_total_values)
            
            # Baseline считается валидным, если есть хотя бы одно не-нулевое значение в total_values_from_summary
            if total_values_from_summary: # Проверяем только если список не пуст
                baseline_is_valid = any(
                    val not in (None, 0, "0", "0.0", "", "0,0") and \
                    not (isinstance(val, str) and val.strip().lower() in {"0", "0.0", "0,0", "none"})
                    for val in total_values_from_summary
                )
        
        # Теперь обрабатываем lot["baseline_proposal"] и удаляем отклонения при необходимости
        if baseline_is_valid: # baseline существует и он не "пустой"
            lot["baseline_proposal"] = baseline
        else: # baseline либо не найден, либо "пустой"
            lot["baseline_proposal"] = {"name": "Расчетная стоимость отсутствует"}
            
            # Удаляем "отклонение от расчетной стоимости" из всех предложений других подрядчиков
            for actual_contractor_proposal in new_proposals.values():
                contractor_items = actual_contractor_proposal.get("items", {})

                # Удалить из обычных позиций (items["positions"])
                positions_data = contractor_items.get("positions", {})
                for pos_item in positions_data.values():
                    if isinstance(pos_item, dict):
                        pos_item.pop("отклонение от расчетной стоимости", None)

                # Удалить из итоговых строк (items["summary"])
                summary_data = contractor_items.get("summary", {})
                for summary_item in summary_data.values():
                    if isinstance(summary_item, dict):
                        summary_item.pop("отклонение от расчетной стоимости", None)
                        
        lot["proposals"] = new_proposals

    return data

# DIV_ZERO_ERROR_STRINGS = {"div/0", "#div/0!", "деление на 0"}

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
        # Рекурсивно обрабатываем значения в словаре, создавая новый словарь
        return {k: replace_div0_with_null(v) for k, v in data.items()}
    elif isinstance(data, list):
        # Рекурсивно обрабатываем элементы в списке, создавая новый список
        return [replace_div0_with_null(item) for item in data]
    elif isinstance(data, str):
        # Нормализуем строку для сравнения
        normalized_data = data.strip().lower()
        # Список строк, считающихся ошибками деления на ноль
        # Если используете константу: if normalized_data in DIV_ZERO_ERROR_STRINGS:
        if normalized_data in ("div/0", "#div/0!", "деление на 0"):
            return None  # Заменяем на None
        return data  # Возвращаем исходную строку, если это не ошибка
    else:
        # Для всех других типов данных возвращаем их без изменений
        return data
