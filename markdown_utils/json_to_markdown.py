from typing import Dict, Any, List # Добавлен List для возвращаемого типа

from helpers.sanitize_text import sanitize_text

# Импорт всех необходимых констант JSON ключей
from constants import (
    JSON_KEY_BASELINE_PROPOSAL, JSON_KEY_COMMENT_CONTRACTOR, JSON_KEY_COMMENT_ORGANIZER,
    JSON_KEY_CONTRACTOR_ACCREDITATION, JSON_KEY_CONTRACTOR_ADDITIONAL_INFO,
    JSON_KEY_CONTRACTOR_ADDRESS, JSON_KEY_CONTRACTOR_INN, JSON_KEY_CONTRACTOR_ITEMS,
    JSON_KEY_CONTRACTOR_POSITIONS, JSON_KEY_CONTRACTOR_SUMMARY, JSON_KEY_CONTRACTOR_TITLE,
    JSON_KEY_EXECUTOR, JSON_KEY_EXECUTOR_DATE, JSON_KEY_EXECUTOR_NAME, JSON_KEY_EXECUTOR_PHONE,
    JSON_KEY_INDIRECT_COSTS, JSON_KEY_JOB_TITLE, JSON_KEY_LOT_TITLE, JSON_KEY_LOTS,
    JSON_KEY_MATERIALS, JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST, JSON_KEY_PROPOSALS,
    JSON_KEY_QUANTITY, JSON_KEY_SUGGESTED_QUANTITY, JSON_KEY_TENDER_ADDRESS,
    JSON_KEY_TENDER_ID, JSON_KEY_TENDER_OBJECT, JSON_KEY_TENDER_TITLE, JSON_KEY_TOTAL,
    JSON_KEY_TOTAL_COST, JSON_KEY_TOTAL_COST_VAT, JSON_KEY_UNIT, JSON_KEY_UNIT_COST,
    JSON_KEY_VAT, JSON_KEY_WORKS, JSON_KEY_CHAPTER_NUMBER
)


def json_to_markdown(data: Dict[str, Any]) -> List[str]:
    """
    Преобразует итоговый JSON-объект (сформированный парсером и прошедший
    постобработку) в список строк для структурированного Markdown-отчета.

    Функция выполняет очистку текстовых данных от символов переноса строки
    с помощью импортированной функции `sanitize_text`. Она также поддерживает
    иерархическое отображение позиций, используя предварительно добавленные
    поля "is_chapter" и "chapter_ref" (результат работы
    `annotate_structure_fields` из `postprocess.py`). Для разделов/глав
    выводится их собственная суммарная информация (если доступна), а для
    обычных позиций — полная детализация. Обычные позиции нумеруются
    последовательно внутри каждого подрядчика.

    Args:
        data (Dict[str, Any]): Словарь Python, представляющий полную структуру данных
            тендера из JSON. Ожидается, что данные прошли
            предварительную обработку (например, функциями
            `normalize_lots_json_structure` и `annotate_structure_fields`).

    Returns:
        List[str]: Список строк Markdown, готовых для записи в файл.

    Особенности форматирования Markdown (согласно предоставленному коду):
    -   Общая информация о тендере (H1, жирный шрифт).
    -   Исполнитель (выделенные метки, значения).
    -   Лоты (H2, горизонтальная черта для разделения).
    -   Расчетная стоимость (baseline_proposal):
        -   Если отсутствует, выводится соответствующий маркер.
        -   В противном случае, выводится ее имя и итоговые суммы
            (из `baseline_proposal['items']['summary']`).
    -   Предложения подрядчиков (H3 для каждого подрядчика):
        -   Итоговые суммы (`summary`) подрядчика (детализированные предложения).
        -   Дополнительная информация.
        -   Позиции подрядчика (H4):
            -   Если позиция является разделом/главой (`is_chapter: True`):
                -   Форматируется как заголовок H5 с эмодзи `📘`, номером раздела,
                    информацией о родительском разделе и наименованием.
                -   Выводятся собственные итоговые стоимости раздела и комментарий.
            -   Обычные позиции (не разделы) нумеруются и выводятся как H6
                с полной детализацией.
    -   Текстовые значения очищаются от символов переноса строки.
    -   Числовые значения выводятся как есть (без специального форматирования типа "0.00 руб."),
        если не указано иное в логике извлечения из JSON.
    """
    md_lines: List[str] = []

    # --- 1. Общая информация о тендере ---
    tender_id_val = data.get(JSON_KEY_TENDER_ID, "N/A") # Используем _val для ясности
    title_val = sanitize_text(data.get(JSON_KEY_TENDER_TITLE, "Без названия"))
    obj_val = sanitize_text(data.get(JSON_KEY_TENDER_OBJECT, ""))
    addr_val = sanitize_text(data.get(JSON_KEY_TENDER_ADDRESS, ""))

    md_lines.append(f"# Тендер №{tender_id_val} «{title_val}»\n") # Используем «» для названия
    if obj_val:
        md_lines.append(f"**Объект:** {obj_val}  ") # Два пробела для markdown line break
    if addr_val:
        md_lines.append(f"**Адрес:** {addr_val}")
    if obj_val or addr_val:
        md_lines.append("  \n") # Явный перенос строки после адреса, если что-то было
    md_lines.append("") # Пустая строка для отступа

    # --- 2. Информация об исполнителе ---
    executor = data.get(JSON_KEY_EXECUTOR, {}) # Используем константу
    if executor: # Проверяем, что словарь не пустой
        exec_name = sanitize_text(executor.get(JSON_KEY_EXECUTOR_NAME, 'Неизвестный исполнитель'))
        exec_phone = sanitize_text(executor.get(JSON_KEY_EXECUTOR_PHONE, 'Не указан'))
        exec_date = sanitize_text(executor.get(JSON_KEY_EXECUTOR_DATE, 'Не указана'))
        md_lines.append(f"**Исполнитель:** {exec_name}  ")
        md_lines.append(f"**Телефон:** {exec_phone}  ")
        md_lines.append(f"**Дата документа:** {exec_date}")
        md_lines.append("\n") # Явный перенос

    # --- 3. Обработка лотов ---
    for lot_key_str, lot_data_dict in data.get(JSON_KEY_LOTS, {}).items(): # Используем константу
        lot_title_s = sanitize_text(lot_data_dict.get(JSON_KEY_LOT_TITLE, 'Лот без названия'))
        md_lines.append(f"\n---\n\n## {sanitize_text(lot_key_str).upper()}: {lot_title_s}\n")

        # -- 3.1 Расчетная стоимость (Baseline Proposal) --
        baseline_prop = lot_data_dict.get(JSON_KEY_BASELINE_PROPOSAL, {})
        baseline_prop_title = sanitize_text(baseline_prop.get(JSON_KEY_CONTRACTOR_TITLE, ''))

        if baseline_prop_title == "Расчетная стоимость отсутствует":
            md_lines.append("**Расчетная стоимость:** отсутствует\n")
        elif baseline_prop: # Если baseline существует и это не маркер отсутствия
            md_lines.append(f"**Расчетная стоимость (\"{baseline_prop_title}\"):**") # Название в кавычках
            baseline_summary_items = baseline_prop.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_SUMMARY, {})
            if baseline_summary_items:
                has_baseline_output = False
                for label_key, values_s_dict in baseline_summary_items.items():
                    if isinstance(values_s_dict, dict):
                        # Отображаем только если есть блок общей стоимости и в нем есть данные
                        total_cost_s_data = values_s_dict.get(JSON_KEY_TOTAL_COST, {})
                        if isinstance(total_cost_s_data, dict) and any(v is not None for v in total_cost_s_data.values()):
                            has_baseline_output = True
                            # Используем JOB_TITLE из summary_item_values как метку, если есть, иначе сам ключ
                            display_label = sanitize_text(values_s_dict.get(JSON_KEY_JOB_TITLE, label_key)).capitalize()
                            md_lines.append(f"- **{display_label}:**")
                            for k_cost, v_cost in total_cost_s_data.items():
                                if v_cost is not None:
                                    # Отображаем компонент стоимости, если он не None
                                    md_lines.append(f"  - {sanitize_text(k_cost).capitalize()}: {v_cost} руб.")
                if not has_baseline_output:
                    md_lines.append(f"  *Итоговые суммы для «{baseline_prop_title}» не найдены или пусты.*")
                md_lines.append("") # Отступ после baseline summary
            else:
                md_lines.append(f"  *Раздел итогов для «{baseline_prop_title}» не найден.*\n")
        
        # -- 3.2 Предложения подрядчиков --
        for contractor_id_str, contractor_data in lot_data_dict.get(JSON_KEY_PROPOSALS, {}).items():
            contractor_name_s = sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_TITLE, "Неизвестный подрядчик"))
            md_lines.append(f"\n### Подрядчик: {contractor_name_s} ({sanitize_text(contractor_id_str)})\n")

            # Основные сведения (ИНН, Адрес, Аккредитация) - вывод в одну строку, если есть
            details_md_parts = []
            if inn_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_INN)): details_md_parts.append(f"**ИНН:** {inn_s}")
            if addr_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_ADDRESS)): details_md_parts.append(f"**Адрес:** {addr_s}")
            if accr_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_ACCREDITATION)): details_md_parts.append(f"**Статус аккредитации:** {accr_s}")
            if details_md_parts:
                md_lines.append("  ".join(details_md_parts) + "  \n")

            # Коммерческие условия (дополнительная информация)
            additional_info_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ADDITIONAL_INFO, {})
            if additional_info_dict:
                md_lines.append(f"**Коммерческие условия от {contractor_name_s}:**")
                for key_info, val_info in additional_info_dict.items():
                    md_lines.append(f"- {sanitize_text(key_info)}: {sanitize_text(val_info) if val_info is not None else '—'}")
                md_lines.append("") # Отступ

            # Итоговые суммы по предложению подрядчика (сохраняя вашу оригинальную структуру вывода)
            contractor_summary_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_SUMMARY, {})
            if contractor_summary_dict:
                # Извлечение данных для удобства
                summary_total_vat = contractor_summary_dict.get(JSON_KEY_TOTAL_COST_VAT, {}).get(JSON_KEY_TOTAL_COST, {})
                summary_vat_only = contractor_summary_dict.get(JSON_KEY_VAT, {}).get(JSON_KEY_TOTAL_COST, {})

                total_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_TOTAL, 0))
                vat_sum_val = sanitize_text(summary_vat_only.get(JSON_KEY_TOTAL, 0))
                md_lines.append(
                    f"Итоговая полная стоимость коммерческого предложения {contractor_name_s} по всем позициям составляет всего {total_sum_val} руб, "
                    f"в том числе НДС {vat_sum_val} руб."
                )
                
                materials_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_MATERIALS, 0))
                materials_vat_val = sanitize_text(summary_vat_only.get(JSON_KEY_MATERIALS, 0))
                md_lines.append(
                    f"Стоимость материалов составляет {materials_sum_val} руб, "
                    f"в том числе НДС {materials_vat_val} руб."
                )

                works_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_WORKS, 0))
                works_vat_val = sanitize_text(summary_vat_only.get(JSON_KEY_WORKS, 0))
                md_lines.append(
                    f"Стоимость работ СМР составляет {works_sum_val} руб, "
                    f"в том числе НДС {works_vat_val} руб.\n" # Перенос строки в конце этого блока
                )
            
            # Детализация позиций подрядчика
            md_lines.append(f"#### Детализация позиций ({contractor_name_s}):\n")
            positions_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_POSITIONS, {})
            if not positions_dict:
                md_lines.append("*Позиции отсутствуют или не найдены.*\n")
            else:
                try: # Сортировка позиций по числовому ключу
                    sorted_positions_list = sorted(positions_dict.items(), key=lambda x: int(x[0]))
                except ValueError:
                    sorted_positions_list = sorted(positions_dict.items()) # Если ключи не числовые

                visible_item_idx_num = 1 # Счетчик для нумерованных обычных позиций
                for _, pos_item_data in sorted_positions_list:
                    if not isinstance(pos_item_data, dict): continue

                    pos_name_s = sanitize_text(pos_item_data.get(JSON_KEY_JOB_TITLE, "Без названия"))
                    pos_unit_s = sanitize_text(pos_item_data.get(JSON_KEY_UNIT, "ед.")) # Значение по умолчанию для единиц
                    pos_quantity_val = pos_item_data.get(JSON_KEY_QUANTITY) # Оставляем как есть, sanitize_text применится ниже при выводе
                    pos_comm_org_s = sanitize_text(pos_item_data.get(JSON_KEY_COMMENT_ORGANIZER))
                    pos_comm_contr_s = sanitize_text(pos_item_data.get(JSON_KEY_COMMENT_CONTRACTOR))
                    pos_sugg_qty_val = pos_item_data.get(JSON_KEY_SUGGESTED_QUANTITY)
                    pos_org_qty_cost_val = pos_item_data.get(JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST)
                    
                    is_chapter_f = pos_item_data.get("is_chapter", False)
                    chapter_num_s = sanitize_text(pos_item_data.get(JSON_KEY_CHAPTER_NUMBER, "")) # Используем константу и sanitize
                    chapter_ref_s = sanitize_text(pos_item_data.get("chapter_ref", ""))
                    
                    section_info_display_str = ""
                    if chapter_ref_s:
                        parent_label_str = "подразделу" if "." in chapter_ref_s else "разделу"
                        section_info_display_str = f" (относится к {parent_label_str} {chapter_ref_s})"

                    if is_chapter_f:
                        # Форматирование для раздела/главы
                        chapter_type_display = "Подраздел" if isinstance(pos_item_data.get(JSON_KEY_CHAPTER_NUMBER), str) and "." in pos_item_data.get(JSON_KEY_CHAPTER_NUMBER, "") else "Раздел"
                        if not pos_name_s.lower().startswith("лот №"): 
                            md_lines.append(f"\n##### 📘 {chapter_type_display} {chapter_num_s}{section_info_display_str}: **{pos_name_s}**\n")

                            # Вывод итогов по разделу/подразделу (сохраняя вашу оригинальную структуру)
                            label_suffix_str = f"по {chapter_type_display.lower()}у {chapter_num_s} (\"{pos_name_s}\")"
                            unit_costs_ch_dict = pos_item_data.get(JSON_KEY_UNIT_COST, {})
                            if isinstance(unit_costs_ch_dict, dict) and any(v is not None for v in unit_costs_ch_dict.values()):
                                materials_uc = unit_costs_ch_dict.get(JSON_KEY_MATERIALS, 0)
                                works_uc = unit_costs_ch_dict.get(JSON_KEY_WORKS, 0)
                                indirect_uc = unit_costs_ch_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                                total_uc = unit_costs_ch_dict.get(JSON_KEY_TOTAL, 0)
                                md_lines.append(
                                    f"Итоговая единичная стоимость {label_suffix_str} составляет {total_uc} руб, "
                                    f"в том числе включены единичная стоимость материалов — {materials_uc} руб., "
                                    f"единичная стоимость работ СМР — {works_uc} руб, "
                                    f"единичная стоимость косвенных расходов — {indirect_uc} руб."
                                )
                            
                            total_costs_ch_dict = pos_item_data.get(JSON_KEY_TOTAL_COST, {})
                            # Проверка на наличие хотя бы одного ненулевого значения перед выводом строки
                            if isinstance(total_costs_ch_dict, dict) and any(total_costs_ch_dict.get(k, 0) != 0 for k in [JSON_KEY_MATERIALS, JSON_KEY_WORKS, JSON_KEY_INDIRECT_COSTS, JSON_KEY_TOTAL]):
                                org_qty_label = f'за объемы подрядчика {contractor_name_s}' if pos_org_qty_cost_val else '' # Было: pos_item.get(JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST)
                                md_lines.append(
                                    f"Полная стоимость {label_suffix_str} {org_qty_label} составляет {total_costs_ch_dict.get(JSON_KEY_TOTAL, 0)} руб, "
                                    f"в том числе включены стоимость материалов — {total_costs_ch_dict.get(JSON_KEY_MATERIALS, 0)} руб, "
                                    f"стоимость работ СМР — {total_costs_ch_dict.get(JSON_KEY_WORKS, 0)} руб, "
                                    f"стоимость косвенных расходов — {total_costs_ch_dict.get(JSON_KEY_INDIRECT_COSTS, 0)} руб."
                                )
                            elif not (isinstance(unit_costs_ch_dict, dict) and any(v is not None for v in unit_costs_ch_dict.values())): # Если и ед.стоимости не было
                                md_lines.append(f"Подрядчик {contractor_name_s} {label_suffix_str} не указал стоимость.")

                            if pos_org_qty_cost_val is not None and pos_org_qty_cost_val != (total_costs_ch_dict.get(JSON_KEY_TOTAL, 0) or 0):
                                md_lines.append(f"При этом полная стоимость {label_suffix_str} за объемы заказчика составляет {pos_org_qty_cost_val} руб.")
                            
                            if pos_comm_contr_s: # Для разделов использовался pos_item.get(JSON_KEY_COMMENT_CONTRACTOR)
                                md_lines.append(f"Комментарий участника {label_suffix_str}: {pos_comm_contr_s}")
                            md_lines.append("") # Отступ после информации о разделе

                    else: # Обычная позиция
                        md_lines.append(f"###### {visible_item_idx_num}. **{pos_name_s}**{section_info_display_str}  ")
                        visible_item_idx_num += 1

                        if pos_comm_org_s:
                            md_lines.append(f"  \nПри подготовке тендерного задания по данной позиции организатор указал следующий комментарий: «{pos_comm_org_s}»")
                        md_lines.append(f"  \nОбъем работ согласно тендерного задания по данной позиции составляет {sanitize_text(pos_quantity_val)} {pos_unit_s}.")
                        if pos_sugg_qty_val is not None and pos_sugg_qty_val != pos_quantity_val:
                            md_lines.append(f"  \nУчастник тендера при подготовке предложения указал следующий объем работ по данной позиции, который он считает корректным: {sanitize_text(pos_sugg_qty_val)} {pos_unit_s}.")
                        
                        # Единичная стоимость
                        uc_dict = pos_item_data.get(JSON_KEY_UNIT_COST, {})
                        uc_total = uc_dict.get(JSON_KEY_TOTAL, 0)
                        uc_mat = uc_dict.get(JSON_KEY_MATERIALS, 0)
                        uc_wrk = uc_dict.get(JSON_KEY_WORKS, 0)
                        uc_ind = uc_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                        md_lines.append(
                            f"  \nЕдиничная стоимость позиции составляет {uc_total} руб/{pos_unit_s}, в том числе включены "
                            f"единичная стоимость материалов — {uc_mat} руб/{pos_unit_s}, "
                            f"единичная стоимость работ СМР — {uc_wrk} руб/{pos_unit_s}, "
                            f"единичная стоимость косвенных расходов — {uc_ind} руб/{pos_unit_s}."
                        )
                        
                        # Полная стоимость
                        tc_dict = pos_item_data.get(JSON_KEY_TOTAL_COST, {})
                        tc_total = tc_dict.get(JSON_KEY_TOTAL, 0)
                        tc_mat = tc_dict.get(JSON_KEY_MATERIALS, 0)
                        tc_wrk = tc_dict.get(JSON_KEY_WORKS, 0)
                        tc_ind = tc_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                        md_lines.append(
                            f"  \nПолная стоимость позиции составляет {tc_total} руб., в том числе "
                            f"стоимость материалов — {tc_mat} руб., "
                            f"стоимость работ СМР — {tc_wrk} руб., "
                            f"стоимость косвенных расходов — {tc_ind} руб."
                        )

                        if pos_org_qty_cost_val is not None and pos_org_qty_cost_val != tc_total:
                            md_lines.append(f"  \nУчитывая, что подрядчик указал собственные объемы работ по данной позиции, то стоимость предложения за объемы заказчика при тех же единичных расценках составляет {pos_org_qty_cost_val} руб.")
                        if pos_comm_contr_s:
                            md_lines.append(f"  \nУчастник тендера при подготовке предложения указал следующий комментарий к позиции: «{pos_comm_contr_s}»")
                        md_lines.append("  \n") # Явный перенос и отступ после позиции
        md_lines.append("\n---") # Разделитель между лотами
    return md_lines