def normalize_lots_json_structure(data):
    """
    Переносит 'Расчетную стоимость' из proposals в baseline_proposal,
    переиндексирует остальных подрядчиков, и очищает 'Дополнительную информацию' из baseline.
    Если в summary baseline все значения 'стоимость всего' равны нулю/None — baseline игнорируется.
    """
    lots = data.get("lots", {})

    for lot_key, lot in lots.items():
        proposals = lot.get("proposals", {})
        new_proposals = {}
        baseline = None
        index = 1

        for key, contractor in proposals.items():
            name = contractor.get("name", "").strip().lower()
            if name == "расчетная стоимость":
                baseline = contractor
            else:
                new_proposals[f"contractor_{index}"] = contractor
                index += 1

        keep_baseline = True
        if baseline:
            # Удаляем дополнительную информацию
            baseline.pop("Дополнительная информация", None)

            # Проверяем, есть ли смысл сохранять baseline
            summary = baseline.get("summary", {})
            total_values = []

            for block in summary.values():
                total_block = block.get("стоимость всего", {})
                values = total_block.values() if isinstance(total_block, dict) else []
                total_values.extend(values)

            # Оставляем baseline только если в нем есть хоть одно ненулевое значение
            if all(
                v in (None, 0, "0", "0.0", "", "0,0")
                or (isinstance(v, str) and v.strip().lower() in {"0", "0.0", "0,0", "none"})
                for v in total_values
            ):
                keep_baseline = False

        if keep_baseline and baseline:
            lot["baseline_proposal"] = baseline

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
