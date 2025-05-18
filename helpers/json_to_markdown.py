import os

def json_to_markdown(data: dict, json_path: str):
    """
    Преобразует итоговый JSON-объект (сформированный парсером и прошедший
    постобработку) в структурированный Markdown-файл.

    Markdown-файл сохраняется в той же директории, что и исходный JSON-файл,
    с тем же именем, но с расширением .md.

    Args:
        data (dict): Словарь Python, представляющий полную структуру данных
                     тендера из JSON.
        json_path (str): Путь к исходному JSON-файлу. Используется для
                         формирования имени выходного .md файла.

    Returns:
        None: Функция ничего не возвращает, но создает файл на диске.

    Side Effects:
        - Создает (или перезаписывает) Markdown-файл.
        - Печатает в консоль сообщение о сохранении файла.

    Структура генерируемого Markdown-файла:
    - Общая информация о тендере (номер, название, объект, адрес).
    - Информация об исполнителе.
    - Разделы по каждому лоту, включая:
        - Информацию о "Расчетной стоимости" (baseline_proposal):
            - Если отсутствует или признана "пустой" на этапе нормализации,
              выводится соответствующий маркер.
            - В противном случае, выводится ее имя и **только итоговые суммы**
              (из `baseline_proposal['items']['summary']`) с разбивкой
              "стоимость всего". Подробные позиции "Расчетной стоимости"
              (из `baseline_proposal['items']['positions']`) в текущей
              версии не выводятся.
        - Информацию по каждому предложению подрядчика:
            - Имя подрядчика.
            - Итоговые суммы (из `contractor['items']['summary']`).
            - Дополнительная информация (`additional_info`).
            - Детализированные позиции (`items['positions']`) с указанием
              наименования, ед. измерения, количества, стоимости за единицу
              и общей стоимости (с разбивкой по статьям затрат).

    Предполагается, что входной словарь `data` имеет структуру, соответствующую
    JSON-файлу, полученному после всех этапов парсинга и постобработки
    (включая `normalize_lots_json_structure` и `replace_div0_with_null`).
    """
    md_lines = []

    # Заголовок тендера
    tender_id = data.get("tender_id", "N/A") # Добавил "N/A" для отсутствующих ID
    title = data.get("tender_title", "Без названия") # И для названия
    obj = data.get("object", "") # Предполагаем, что ключ в JSON именно "object"
    addr = data.get("address", "")

    md_lines.append(f"# Тендер №{tender_id} \"{title}\"\n")
    if obj:
        md_lines.append(f"**Объект:** {obj}  ") # Двойной пробел для переноса строки в Markdown
    if addr:
        md_lines.append(f"**Адрес:** {addr}\n")

    # Исполнитель
    executor = data.get("executor", {})
    if executor: # Проверяем, что executor не пустой словарь
        md_lines.append("\n## Исполнитель")
        for key, val in executor.items():
            if val is not None and str(val).strip() != "": # Выводим только непустые значения
                md_lines.append(f"- {key.capitalize()}: {val}")
        md_lines.append("") # Пустая строка для отступа

    # Обработка лотов
    for lot_key, lot_data in data.get("lots", {}).items(): # Переименовал lot в lot_data для ясности
        md_lines.append(f"\n---\n\n## {lot_key.upper()}: {lot_data.get('lot_title', '')}\n")

        # Расчетная стоимость (Baseline Proposal)
        baseline = lot_data.get("baseline_proposal", {})
        if baseline.get("name") == "Расчетная стоимость отсутствует":
            md_lines.append("**Расчетная стоимость:** отсутствует\n")
        elif baseline: # Убедимся, что baseline существует и это не просто {}
            md_lines.append(f"**Расчетная стоимость:** {baseline.get('name', 'Н/Д')}")
            # Отображаем только summary для baseline
            baseline_summary = baseline.get("items", {}).get("summary", {})
            if baseline_summary: # Если есть summary
                for label, values_dict in baseline_summary.items(): # values_dict - это блок summary (например, ИТОГО С НДС)
                    if isinstance(values_dict, dict): # Убедимся, что это словарь
                        md_lines.append(f"- {label}:")
                        total_cost_data = values_dict.get("стоимость всего", {})
                        if isinstance(total_cost_data, dict):
                            for k, v_cost in total_cost_data.items():
                                if v_cost is not None:
                                    md_lines.append(f"  - {k}: {v_cost} руб.")
                md_lines.append("") # Пустая строка для отступа
            else:
                md_lines.append("- *Итоговые суммы для расчетной стоимости не найдены.*\n")


        # Подрядчики
        for contractor_key, contractor_data in lot_data.get("proposals", {}).items(): # Переименовал contractor в contractor_data
            contractor_name = contractor_data.get("name", "Неизвестный подрядчик")
            md_lines.append(f"\n### Подрядчик: {contractor_name}")

            # Summary подрядчика
            contractor_summary = contractor_data.get("items", {}).get("summary", {})
            if contractor_summary:
                for label, values_dict in contractor_summary.items():
                     if isinstance(values_dict, dict):
                        md_lines.append(f"- {label}:")
                        total_cost_data = values_dict.get("стоимость всего", {})
                        if isinstance(total_cost_data, dict):
                            for k, v_cost in total_cost_data.items():
                                if v_cost is not None:
                                    md_lines.append(f"  - {k}: {v_cost} руб.")

            # Доп. информация подрядчика
            additional_info_data = contractor_data.get("additional_info", {}) # Используем английский ключ
            if additional_info_data:
                md_lines.append("- **Доп. информация:**")
                for k, v_info in additional_info_data.items():
                    md_lines.append(f"  - {k}: {v_info if v_info is not None else '—'}")

            # Позиции подрядчика
            md_lines.append(f"\n#### Позиции подрядчика {contractor_name}:")
            positions_data = contractor_data.get("items", {}).get("positions", {})
            if not positions_data:
                 md_lines.append("_Позиции отсутствуют или не найдены._")
            for pos_id, pos_item in positions_data.items(): # pos_item - это конкретная позиция
                pos_name = pos_item.get("наименование работ", "Без названия")
                pos_unit = pos_item.get("единица измерения")
                pos_quantity = pos_item.get("количество")

                md_lines.append(f"{pos_id}. **{pos_name}** ") # Двойной пробел для <br>
                if pos_unit:
                    md_lines.append(f"  - Ед. изм.: {pos_unit}")
                if pos_quantity is not None: # Проверка на None для количества
                    md_lines.append(f"  - Кол-во: {pos_quantity}")

                # Стоимость за единицу
                md_lines.append("  - Стоимость за единицу:")
                unit_costs = pos_item.get("стоимость за единицу", {})
                for cost_key in ["материалы", "работы", "косвенные расходы", "всего"]:
                    val = unit_costs.get(cost_key)
                    val_str = str(val) if val not in [None, ""] else "0" # Отображаем 0 для пустых/None
                    md_lines.append(f"    - {cost_key.capitalize()}: {val_str} руб.")

                # Стоимость всего
                md_lines.append("  - Стоимость всего:")
                total_costs = pos_item.get("стоимость всего", {})
                for cost_key in ["материалы", "работы", "косвенные расходы", "всего"]:
                    val = total_costs.get(cost_key)
                    val_str = str(val) if val not in [None, ""] else "0" # Отображаем 0 для пустых/None
                    display_key = "Полная стоимость по позиции" if cost_key == "всего" else cost_key.capitalize()
                    md_lines.append(f"    - {display_key}: {val_str} руб.")

                # Стоимость за объемы заказчика
                customer_total = pos_item.get("стоимость всего за объемы заказчика")
                if customer_total is not None:
                    md_lines.append(f"  - За объемы заказчика: {customer_total} руб.") # Добавил "руб."

                # Комментарий участника
                comment = pos_item.get("комментарий участника")
                if comment:
                    md_lines.append(f"  - Комментарий участника: {comment}")
                md_lines.append("") # Пустая строка после каждой позиции для лучшей читаемости

    # Сохраняем файл
    md_path = os.path.splitext(json_path)[0] + ".md"
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        print(f"Markdown сохранен в {md_path}")
    except IOError as e:
        print(f"Ошибка при сохранении Markdown файла {md_path}: {e}")