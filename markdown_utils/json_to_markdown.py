import os

def json_to_markdown(data: dict, json_path: str):
    """
    Преобразует итоговый JSON-объект (сформированный парсером и прошедший
    постобработку) в структурированный Markdown-файл.

    Функция выполняет очистку текстовых данных от символов переноса строки.
    Она также поддерживает иерархическое отображение позиций, используя
    предварительно добавленные поля "is_chapter" и "chapter_ref".
    Для разделов/глав выводится их собственная суммарная информация (если доступна),
    а для обычных позиций — полная детализация. Обычные позиции нумеруются
    последовательно внутри каждого подрядчика.

    Markdown-файл сохраняется в той же директории, что и исходный JSON-файл,
    с тем же именем, но с расширением .md.

    Args:
        data (dict): Словарь Python, представляющий полную структуру данных
                     тендера из JSON. Ожидается, что данные прошли
                     предварительную обработку (например, функциями
                     `normalize_lots_json_structure` и `annotate_structure_fields`).
        json_path (str): Путь к исходному JSON-файлу. Используется для
                         формирования имени выходного .md файла.

    Returns:
        None: Функция ничего не возвращает, но создает файл на диске.

    Side Effects:
        - Создает (или перезаписывает) Markdown-файл.
        - Печатает в консоль сообщение о сохранении файла.

    Особенности форматирования Markdown:
    - Общая информация о тендере (H1, жирный шрифт).
    - Исполнитель (H2, список).
    - Лоты (H2, горизонтальная черта для разделения).
    - Расчетная стоимость (baseline_proposal):
        - Если отсутствует, выводится соответствующий маркер.
        - В противном случае, выводится ее имя и только итоговые суммы
          (из `baseline_proposal['items']['summary']`).
    - Предложения подрядчиков (H3 для каждого подрядчика):
        - Итоговые суммы (`summary`) подрядчика.
        - Дополнительная информация (ключ "Дополнительная информация").
        - Позиции подрядчика (H4):
            - Если позиция является разделом/главой (`is_chapter: True`):
                - Она форматируется как заголовок H5 с эмодзи `📘`, номером раздела,
                  информацией о родительском разделе и наименованием.
                - Под заголовком раздела выводятся его собственные итоговые
                  стоимости ("за единицу" и "всего") и "комментарий участника",
                  если эти данные присутствуют в объекте раздела.
            - Обычные позиции (не разделы) нумеруются последовательно (1, 2, 3...)
              внутри каждого подрядчика и включают полную детализацию (наименование,
              ед.изм., кол-во, стоимость за единицу, стоимость всего, стоимость
              за объемы заказчика, комментарий).
    - Текстовые значения очищаются от символов переноса строки.
    - Отсутствующие числовые значения в блоках стоимости позиций отображаются как "0 руб.".
    """
    md_lines = []

    def sanitize_text(text_val):
        """Удаляет переносы строк и лишние пробелы из текста."""
        if isinstance(text_val, str):
            return text_val.replace("\n", " ").replace("\r", " ").strip()
        return text_val

    tender_id = data.get("tender_id", "N/A")
    title = sanitize_text(data.get("tender_title", "Без названия"))
    obj = sanitize_text(data.get("object", ""))
    addr = sanitize_text(data.get("address", ""))

    md_lines.append(f"# Тендер №{tender_id} \"{title}\"\n")
    if obj:
        md_lines.append(f"**Объект:** {obj}  ")
    if addr:
        md_lines.append(f"**Адрес:** {addr}\n")

    executor = data.get("executor", {})
    if executor:
        md_lines.append("\n## Исполнитель")
        for key, val in executor.items():
            if val is not None and str(val).strip() != "":
                md_lines.append(f"- {key.capitalize()}: {sanitize_text(val)}")
        md_lines.append("")

    for lot_key, lot_data in data.get("lots", {}).items():
        md_lines.append(f"\n---\n\n## {lot_key.upper()}: {sanitize_text(lot_data.get('lot_title', ''))}\n")

        baseline = lot_data.get("baseline_proposal", {})
        if baseline.get("name") == "Расчетная стоимость отсутствует":
            md_lines.append("**Расчетная стоимость:** отсутствует\n")
        elif baseline:
            md_lines.append(f"**Расчетная стоимость:** {sanitize_text(baseline.get('name', 'Н/Д'))}")
            baseline_summary = baseline.get("items", {}).get("summary", {})
            if baseline_summary:
                for label, values_dict in baseline_summary.items():
                    if isinstance(values_dict, dict):
                        md_lines.append(f"- {sanitize_text(label)}:")
                        total_cost_data = values_dict.get("стоимость всего", {})
                        if isinstance(total_cost_data, dict) and any(v is not None for v in total_cost_data.values()): # Печатаем, только если есть значения
                            for k_cost, v_cost in total_cost_data.items():
                                if v_cost is not None: # Отображаем только не-None значения
                                    md_lines.append(f"  - {sanitize_text(k_cost)}: {v_cost} руб.")
                md_lines.append("")
            else:
                md_lines.append("- *Итоговые суммы для расчетной стоимости не найдены.*\n")
        
        for contractor_key_loop, contractor_data_loop in lot_data.get("proposals", {}).items():
            contractor_name = sanitize_text(contractor_data_loop.get("name", "Неизвестный подрядчик"))
            md_lines.append(f"\n### Подрядчик: {contractor_name}")

            contractor_summary = contractor_data_loop.get("items", {}).get("summary", {})
            if contractor_summary:
                for label, values_dict in contractor_summary.items():
                     if isinstance(values_dict, dict):
                        md_lines.append(f"- {sanitize_text(label)}:")
                        total_cost_data = values_dict.get("стоимость всего", {})
                        if isinstance(total_cost_data, dict) and any(v is not None for v in total_cost_data.values()):
                            for k_cost, v_cost in total_cost_data.items():
                                if v_cost is not None:
                                    md_lines.append(f"  - {sanitize_text(k_cost)}: {v_cost} руб.")
            
            extra_info_data = contractor_data_loop.get("Дополнительная информация", {})
            if extra_info_data:
                md_lines.append("- **Доп. информация:**")
                for k_info, v_info in extra_info_data.items():
                    md_lines.append(f"  - {sanitize_text(k_info)}: {sanitize_text(v_info) if v_info is not None else '—'}")

            md_lines.append(f"\n#### Позиции подрядчика {contractor_name}:")
            positions_data = contractor_data_loop.get("items", {}).get("positions", {})
            if not positions_data:
                 md_lines.append("_Позиции отсутствуют или не найдены._")
            
            visible_item_index = 1 # Счетчик для нумерации обычных позиций
            for _, pos_item in positions_data.items(): # Ключ из positions не используем для нумерации
                pos_name = sanitize_text(pos_item.get("наименование работ", "Без названия"))
                pos_unit = sanitize_text(pos_item.get("единица измерения"))
                pos_quantity = pos_item.get("количество") # sanitize_text здесь применится, если количество - строка
                
                is_chapter_flag = pos_item.get("is_chapter", False)
                chapter_ref_val = pos_item.get("chapter_ref")
                
                section_info_str = ""
                if chapter_ref_val: # chapter_ref_val может быть None
                    ref_str = str(chapter_ref_val) # Убедимся, что это строка для .count('.')
                    parent_label = "подразделу" if "." in ref_str else "разделу" # Используем ref_str
                    section_info_str = f" (относится к {parent_label} {chapter_ref_val})"

                if is_chapter_flag:
                    chapter_num = pos_item.get("номер раздела", "") # Используем chapter_num вместо "номер"
                    # Проверка, чтобы случайно не отформатировать название лота как раздел, если оно есть в позициях
                    if not pos_name.lower().startswith("лот №"): 
                        title_type = "Подраздел" if isinstance(chapter_num, str) and "." in chapter_num else "Раздел"
                        md_lines.append(f"\n##### 📘 {title_type} {chapter_num}{section_info_str}: {pos_name}")

                        # Вывод итогов по разделу/подразделу
                        label_suffix = f"по {title_type.lower()}у {chapter_num} (\"{pos_name}\")"

                        unit_costs_chapter = pos_item.get("стоимость за единицу", {})
                        if any(v is not None and v != "" for v in unit_costs_chapter.values()):
                            md_lines.append(f"- Итоговая стоимость за единицу {label_suffix}:")
                            for k_cost_u_ch, v_cost_u_ch in unit_costs_chapter.items():
                                if v_cost_u_ch is not None:
                                    md_lines.append(f"  - {k_cost_u_ch.capitalize()}: {v_cost_u_ch} руб.")

                        total_costs_chapter = pos_item.get("стоимость всего", {})
                        if any(v is not None and v != "" for v in total_costs_chapter.values()):
                            md_lines.append(f"- Итоговая стоимость всего {label_suffix}:")
                            for k_cost_t_ch, v_cost_t_ch in total_costs_chapter.items():
                                if v_cost_t_ch is not None:
                                    md_lines.append(f"  - {k_cost_t_ch.capitalize()}: {v_cost_t_ch} руб.")
                        
                        comment_chapter = pos_item.get("комментарий участника")
                        if comment_chapter:
                            md_lines.append(f"- Комментарий участника {label_suffix}: {sanitize_text(comment_chapter)}")
                        md_lines.append("") # Отступ после информации о разделе
                else: # Обычная позиция
                    md_lines.append(f"{visible_item_index}. **{pos_name}**{section_info_str}  ")
                    visible_item_index += 1 # Инкрементируем счетчик только для обычных позиций
                    
                    if pos_unit:
                        md_lines.append(f"  - Ед. изм: {pos_unit}")
                    if pos_quantity is not None:
                        md_lines.append(f"  - Кол-во: {pos_quantity}")

                    md_lines.append("  - Стоимость за единицу:")
                    unit_costs = pos_item.get("стоимость за единицу", {})
                    for cost_key_u in ["материалы", "работы", "косвенные расходы", "всего"]:
                        val_u = unit_costs.get(cost_key_u)
                        val_u_str = str(val_u) if val_u not in [None, ""] else "0"
                        md_lines.append(f"    - {cost_key_u.capitalize()}: {val_u_str} руб.")

                    md_lines.append("  - Стоимость всего:")
                    total_costs = pos_item.get("стоимость всего", {})
                    for cost_key_t in ["материалы", "работы", "косвенные расходы", "всего"]:
                        val_t = total_costs.get(cost_key_t)
                        val_t_str = str(val_t) if val_t not in [None, ""] else "0"
                        display_key_t = "Полная стоимость по позиции" if cost_key_t == "всего" else cost_key_t.capitalize()
                        md_lines.append(f"    - {display_key_t}: {val_t_str} руб.")

                    customer_total = pos_item.get("стоимость всего за объемы заказчика")
                    if customer_total is not None:
                        md_lines.append(f"  - За объемы заказчика: {customer_total} руб.")

                    comment = pos_item.get("комментарий участника")
                    if comment:
                        md_lines.append(f"  - Комментарий участника: {sanitize_text(comment)}")
                    md_lines.append("")

    md_path = os.path.splitext(json_path)[0] + ".md"
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        print(f"Markdown сохранен в {md_path}")
    except IOError as e:
        print(f"Ошибка при сохранении Markdown файла {md_path}: {e}")