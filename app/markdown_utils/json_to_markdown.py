"""
markdown_utils/json_to_markdown.py

Модуль для преобразования структурированных JSON-данных о тендере в Markdown.

Содержит функцию `json_to_markdown`, которая принимает полный JSON-объект
данных тендера (после парсинга и постобработки) и генерирует:
1.  Список строк в формате Markdown, предназначенный для создания человекочитаемого отчета
    с улучшенной структурой для последующего разделения на чанки.
2.  Словарь с основной (заголовочной) информацией о тендере и исполнителе.

Модуль использует импортируемые функции `sanitize_text` и `sanitize_object_and_address_text`
из пакета `helpers` для очистки текстовых данных, а также константы для доступа
к полям JSON-объекта. Основное внимание уделяется структурированному и
иерархическому представлению тендерной информации в Markdown.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..constants import (
    JSON_KEY_BASELINE_PROPOSAL,
    JSON_KEY_CHAPTER_NUMBER,
    JSON_KEY_COMMENT_CONTRACTOR,
    JSON_KEY_COMMENT_ORGANIZER,
    JSON_KEY_CONTRACTOR_ACCREDITATION,
    JSON_KEY_CONTRACTOR_ADDITIONAL_INFO,
    JSON_KEY_CONTRACTOR_ADDRESS,
    JSON_KEY_CONTRACTOR_INN,
    JSON_KEY_CONTRACTOR_ITEMS,
    JSON_KEY_CONTRACTOR_POSITIONS,
    JSON_KEY_CONTRACTOR_SUMMARY,
    JSON_KEY_CONTRACTOR_TITLE,
    JSON_KEY_EXECUTOR,
    JSON_KEY_EXECUTOR_DATE,
    JSON_KEY_EXECUTOR_NAME,
    JSON_KEY_EXECUTOR_PHONE,
    JSON_KEY_INDIRECT_COSTS,
    JSON_KEY_JOB_TITLE,
    JSON_KEY_LOT_TITLE,
    JSON_KEY_LOTS,
    JSON_KEY_MATERIALS,
    JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
    JSON_KEY_PROPOSALS,
    JSON_KEY_QUANTITY,
    JSON_KEY_SUGGESTED_QUANTITY,
    JSON_KEY_TENDER_ADDRESS,
    JSON_KEY_TENDER_ID,
    JSON_KEY_TENDER_OBJECT,
    JSON_KEY_TENDER_TITLE,
    JSON_KEY_TOTAL,
    JSON_KEY_TOTAL_COST,
    JSON_KEY_TOTAL_COST_VAT,
    JSON_KEY_UNIT,
    JSON_KEY_UNIT_COST,
    JSON_KEY_VAT,
    JSON_KEY_WORKS,
)
from ..helpers.sanitize_text import sanitize_object_and_address_text, sanitize_text


def json_to_markdown(
    data: Dict[str, Any],
) -> Tuple[List[str], Dict[str, Optional[str]]]:
    """
    Преобразует итоговый JSON-объект в список строк Markdown и словарь метаданных.

    Функция использует импортированные `sanitize_text` и
    `sanitize_object_and_address_text` для очистки текстовых данных.
    Создает более гранулярную структуру Markdown с использованием дополнительных
    заголовков H3 (для Расчетной стоимости) и H4 (для секций информации
    о подрядчике), что улучшает последующее разделение на чанки.

    Args:
        data (Dict[str, Any]): Словарь Python с полной структурой данных тендера.

    Returns:
        Tuple[List[str], Dict[str, Optional[str]]]: Кортеж:
            - Список строк Markdown.
            - Словарь `initial_metadata` с основной информацией.

    Особенности форматирования генерируемого Markdown:
    -   Общая информация о тендере (H1).
    -   Исполнитель (текст).
    -   Лоты (H2).
        -   Расчетная стоимость (`baseline_proposal`): Заголовок H3, название, итоги.
        -   Предложения подрядчиков: Заголовок H3.
            -   Основные сведения: Заголовок H4, затем ИНН, адрес и т.д.
            -   Коммерческие условия: Заголовок H4, затем список условий.
            -   Общие итоги по предложению: Заголовок H4, затем суммы.
            -   Детализация позиций: Заголовок H4.
                -   Разделы/главы (`is_chapter: True`): Заголовок H5.
                -   Обычные позиции: Заголовок H6.
    -   Текстовые значения очищаются. Числа выводятся как есть.
    """
    md_lines: List[str] = []

    # --- 1. Общая информация о тендере ---
    tender_id_val = data.get(JSON_KEY_TENDER_ID, "N/A")
    title_val = sanitize_text(data.get(JSON_KEY_TENDER_TITLE, "Без названия"))
    obj_val = sanitize_object_and_address_text(data.get(JSON_KEY_TENDER_OBJECT, ""))
    addr_val = sanitize_object_and_address_text(data.get(JSON_KEY_TENDER_ADDRESS, ""))

    md_lines.append(f"# Тендер №{tender_id_val} «{title_val}».")
    if obj_val or addr_val:
        md_lines.append("")

    if obj_val:
        md_lines.append(f"**Объект:** {obj_val}.  ")
    if addr_val:
        md_lines.append(f"**Адрес:** {addr_val}.")

    if obj_val or addr_val:
        md_lines.append("")

    # --- 2. Информация об исполнителе ---
    executor = data.get(JSON_KEY_EXECUTOR, {})
    exec_name_s: Optional[str] = None
    exec_phone_s: Optional[str] = None
    exec_date_s: Optional[str] = None

    if executor:
        exec_name_s = sanitize_text(
            executor.get(JSON_KEY_EXECUTOR_NAME, "Неизвестный исполнитель")
        )
        exec_phone_s = sanitize_text(executor.get(JSON_KEY_EXECUTOR_PHONE, "Не указан"))
        exec_date_s = sanitize_text(executor.get(JSON_KEY_EXECUTOR_DATE, "Не указана"))

        md_lines.append(f"**Исполнитель:** {exec_name_s}.  ")
        md_lines.append(f"**Телефон:** {exec_phone_s}.  ")
        md_lines.append(f"**Дата документа:** {exec_date_s}.")
        md_lines.append("")

    initial_metadata: Dict[str, Optional[str]] = {
        "tender_id": tender_id_val,
        "tender_title": title_val,
        "tender_object": obj_val,
        "tender_address": addr_val,
        "executor_name": exec_name_s,
        "executor_phone": exec_phone_s,
        "executor_date": exec_date_s,
    }
    initial_metadata = {
        k: v
        for k, v in initial_metadata.items()
        if v is not None and (str(v).strip() != "" or k == "tender_id")
    }

    # --- 3. Обработка лотов ---
    for lot_key_str, lot_data_dict in data.get(JSON_KEY_LOTS, {}).items():
        lot_title_s = sanitize_text(
            lot_data_dict.get(JSON_KEY_LOT_TITLE, "Лот без названия")
        )
        md_lines.append(
            f"\n---\n\n## {sanitize_text(lot_key_str).upper()}: {lot_title_s}\n"
        )

        # -- 3.1 Расчетная стоимость (Baseline Proposal) - теперь под H3 --
        baseline_prop = lot_data_dict.get(JSON_KEY_BASELINE_PROPOSAL, {})
        baseline_prop_title = sanitize_text(
            baseline_prop.get(JSON_KEY_CONTRACTOR_TITLE, "")
        )

        if baseline_prop_title == "Расчетная стоимость отсутствует":
            md_lines.append(f"### Расчетная стоимость\n")  # Новый H3
            md_lines.append("Не предоставлялась или не валидна.\n")
        elif baseline_prop:
            md_lines.append(f"### Расчетная стоимость\n")  # Новый H3
            md_lines.append(f'**Название:** "{baseline_prop_title}"')
            baseline_summary_items = baseline_prop.get(
                JSON_KEY_CONTRACTOR_ITEMS, {}
            ).get(JSON_KEY_CONTRACTOR_SUMMARY, {})
            if baseline_summary_items:
                md_lines.append("**Итоги:**")
                has_baseline_output = False
                for label_key, values_s_dict in baseline_summary_items.items():
                    if isinstance(values_s_dict, dict):
                        total_cost_s_data = values_s_dict.get(JSON_KEY_TOTAL_COST, {})
                        if isinstance(total_cost_s_data, dict) and any(
                            v is not None for v in total_cost_s_data.values()
                        ):
                            has_baseline_output = True
                            display_label = sanitize_text(
                                values_s_dict.get(JSON_KEY_JOB_TITLE, label_key)
                            ).capitalize()
                            md_lines.append(f"- **{display_label}:**")
                            for k_cost, v_cost in total_cost_s_data.items():
                                if v_cost is not None:
                                    md_lines.append(
                                        f"  - {sanitize_text(k_cost).capitalize()}: {v_cost} руб."
                                    )
                if not has_baseline_output:
                    md_lines.append(
                        f"  *Итоговые суммы для «{baseline_prop_title}» не найдены или пусты.*"
                    )
                md_lines.append("")
            else:
                md_lines.append(
                    f"  *Раздел итогов для «{baseline_prop_title}» не найден.*\n"
                )

        # -- 3.2 Предложения подрядчиков --
        for contractor_id_str, contractor_data in lot_data_dict.get(
            JSON_KEY_PROPOSALS, {}
        ).items():
            contractor_name_s = sanitize_text(
                contractor_data.get(JSON_KEY_CONTRACTOR_TITLE, "Неизвестный подрядчик")
            )
            md_lines.append(f"\n### {contractor_name_s}\n")

            # -- 3.2.1 Основные сведения о подрядчике (H4) --
            details_md_parts = []
            if inn_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_INN)):
                details_md_parts.append(f"**ИНН:** {inn_s}.")
            if addr_s := sanitize_text(
                contractor_data.get(JSON_KEY_CONTRACTOR_ADDRESS)
            ):
                details_md_parts.append(f"**Адрес:** {addr_s}.")
            if accr_s := sanitize_text(
                contractor_data.get(JSON_KEY_CONTRACTOR_ACCREDITATION)
            ):
                details_md_parts.append(f"**Статус аккредитации:** {accr_s}.")
            if details_md_parts:
                md_lines.append(f"#### Основные сведения о подрядчике\n")
                md_lines.append("  ".join(details_md_parts) + "  \n")

            # -- 3.2.2 Коммерческие условия (H4) --
            additional_info_dict = contractor_data.get(
                JSON_KEY_CONTRACTOR_ADDITIONAL_INFO, {}
            )
            if additional_info_dict:
                md_lines.append(f"#### Коммерческие условия {contractor_name_s}\n")
                md_lines.append(
                    f" Здесь описываются коммерческие условия, указанные {contractor_name_s} в предложении к тендеру {tender_id_val}.\n"
                )
                md_lines.append(
                    "  Коммерческие условия могут включать в себя различные аспекты, такие как сроки выполнения, условия оплаты, гарантии и т.д.\n"
                )
                md_lines.append(
                    "  Ниже приведены ключевые коммерческие условия, указанные подрядчиком:\n"
                )
                for key_info, val_info in additional_info_dict.items():
                    md_lines.append(
                        f"{sanitize_text(key_info)}: {sanitize_text(val_info) if val_info is not None else 'нет данных'}."
                    )
                md_lines.append("")

            # -- 3.2.3 Общие итоги по предложению подрядчика (H4) --
            contractor_summary_dict = contractor_data.get(
                JSON_KEY_CONTRACTOR_ITEMS, {}
            ).get(JSON_KEY_CONTRACTOR_SUMMARY, {})
            if contractor_summary_dict:
                md_lines.append(
                    f"#### Общие итоги по предложению {contractor_name_s}\n"
                )
                summary_total_vat = contractor_summary_dict.get(
                    JSON_KEY_TOTAL_COST_VAT, {}
                ).get(JSON_KEY_TOTAL_COST, {})
                summary_vat_only = contractor_summary_dict.get(JSON_KEY_VAT, {}).get(
                    JSON_KEY_TOTAL_COST, {}
                )
                total_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_TOTAL, 0))
                vat_sum_val = sanitize_text(summary_vat_only.get(JSON_KEY_TOTAL, 0))
                md_lines.append(
                    f"Итоговая полная стоимость коммерческого предложения {contractor_name_s} по всем позициям составляет всего {total_sum_val} руб, "
                    f"в том числе НДС {vat_sum_val} руб."
                )
                materials_sum_val = sanitize_text(
                    summary_total_vat.get(JSON_KEY_MATERIALS, 0)
                )
                materials_vat_val = sanitize_text(
                    summary_vat_only.get(JSON_KEY_MATERIALS, 0)
                )
                md_lines.append(
                    f"Стоимость материалов составляет {materials_sum_val} руб, "
                    f"в том числе НДС {materials_vat_val} руб."
                )
                works_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_WORKS, 0))
                works_vat_val = sanitize_text(summary_vat_only.get(JSON_KEY_WORKS, 0))
                md_lines.append(
                    f"Стоимость работ СМР составляет {works_sum_val} руб, "
                    f"в том числе НДС {works_vat_val} руб."
                )
                # Добавим Косвенные расходы, если они есть (по аналогии с выводом в позициях)
                indirect_sum_val = sanitize_text(
                    summary_total_vat.get(JSON_KEY_INDIRECT_COSTS, 0)
                )
                indirect_vat_val = sanitize_text(
                    summary_vat_only.get(JSON_KEY_INDIRECT_COSTS, 0)
                )
                if float(
                    indirect_sum_val != 0 or indirect_vat_val != 0
                ):  # Проверяем, что не нули
                    md_lines.append(
                        f"Косвенные расходы составляют {indirect_sum_val} руб, "
                        f"в том числе НДС {indirect_vat_val} руб."
                    )
                md_lines.append("")  # Отступ после общих итогов

            # -- 3.2.4 Детализация позиций (H4) --
            md_lines.append(f"#### Детализация позиций ({contractor_name_s})\n")
            positions_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(
                JSON_KEY_CONTRACTOR_POSITIONS, {}
            )
            if not positions_dict:
                md_lines.append("*Позиции отсутствуют или не найдены.*\n")
            else:
                try:
                    sorted_positions_list = sorted(
                        positions_dict.items(), key=lambda x: int(x[0])
                    )
                except ValueError:
                    sorted_positions_list = sorted(positions_dict.items())

                visible_item_idx_num = 1
                for _, pos_item_data in sorted_positions_list:
                    if not isinstance(pos_item_data, dict):
                        continue

                    pos_name_s = sanitize_text(
                        pos_item_data.get(JSON_KEY_JOB_TITLE, "Без названия")
                    )
                    pos_unit_s = sanitize_text(pos_item_data.get(JSON_KEY_UNIT, "ед."))
                    pos_quantity_val = pos_item_data.get(JSON_KEY_QUANTITY)
                    pos_comm_org_s = sanitize_text(
                        pos_item_data.get(JSON_KEY_COMMENT_ORGANIZER)
                    )
                    pos_comm_contr_s = sanitize_text(
                        pos_item_data.get(JSON_KEY_COMMENT_CONTRACTOR)
                    )
                    pos_sugg_qty_val = pos_item_data.get(JSON_KEY_SUGGESTED_QUANTITY)
                    pos_org_qty_cost_val = pos_item_data.get(
                        JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST
                    )

                    is_chapter_f = pos_item_data.get("is_chapter", False)
                    chapter_num_s = sanitize_text(
                        pos_item_data.get(JSON_KEY_CHAPTER_NUMBER, "")
                    )
                    chapter_ref_s = sanitize_text(pos_item_data.get("chapter_ref", ""))

                    section_info_display_str = ""
                    if chapter_ref_s:
                        parent_label_str = (
                            "подразделу" if "." in chapter_ref_s else "разделу"
                        )
                        section_info_display_str = (
                            f" (относится к {parent_label_str} {chapter_ref_s})"
                        )

                    if is_chapter_f:
                        chapter_type_display = (
                            "Подраздел"
                            if isinstance(
                                pos_item_data.get(JSON_KEY_CHAPTER_NUMBER), str
                            )
                            and "." in pos_item_data.get(JSON_KEY_CHAPTER_NUMBER, "")
                            else "Раздел"
                        )
                        if not pos_name_s.lower().startswith("лот №"):
                            md_lines.append(
                                f"\n##### {chapter_type_display} {chapter_num_s}{section_info_display_str}: **{pos_name_s}**\n"
                            )

                            label_suffix_str = f'по {chapter_type_display.lower()}у {chapter_num_s} ("{pos_name_s}")'
                            unit_costs_ch_dict = pos_item_data.get(
                                JSON_KEY_UNIT_COST, {}
                            )
                            if isinstance(unit_costs_ch_dict, dict) and any(
                                v is not None for v in unit_costs_ch_dict.values()
                            ):
                                materials_uc = unit_costs_ch_dict.get(
                                    JSON_KEY_MATERIALS, 0
                                )
                                works_uc = unit_costs_ch_dict.get(JSON_KEY_WORKS, 0)
                                indirect_uc = unit_costs_ch_dict.get(
                                    JSON_KEY_INDIRECT_COSTS, 0
                                )
                                total_uc = unit_costs_ch_dict.get(JSON_KEY_TOTAL, 0)
                                md_lines.append(
                                    f"Итоговая единичная стоимость {contractor_name_s} {label_suffix_str} составляет {total_uc} руб, "
                                    f"в том числе включены единичная стоимость материалов — {materials_uc} руб., "
                                    f"единичная стоимость работ СМР — {works_uc} руб, "
                                    f"единичная стоимость косвенных расходов — {indirect_uc} руб."
                                )

                            total_costs_ch_dict = pos_item_data.get(
                                JSON_KEY_TOTAL_COST, {}
                            )
                            if isinstance(total_costs_ch_dict, dict) and any(
                                total_costs_ch_dict.get(k, 0) != 0
                                for k in [
                                    JSON_KEY_MATERIALS,
                                    JSON_KEY_WORKS,
                                    JSON_KEY_INDIRECT_COSTS,
                                    JSON_KEY_TOTAL,
                                ]
                            ):
                                org_qty_label = (
                                    f" за объемы подрядчика {contractor_name_s}"
                                    if pos_org_qty_cost_val is not None
                                    else ""
                                )
                                md_lines.append(
                                    f"Полная стоимость {contractor_name_s} {label_suffix_str}{org_qty_label} составляет {total_costs_ch_dict.get(JSON_KEY_TOTAL, 0)} руб, "
                                    f"в том числе: мат. — {total_costs_ch_dict.get(JSON_KEY_MATERIALS, 0)} руб., "  # Сокращенный вывод
                                    f"раб. — {total_costs_ch_dict.get(JSON_KEY_WORKS, 0)} руб., "
                                    f"косв. — {total_costs_ch_dict.get(JSON_KEY_INDIRECT_COSTS, 0)} руб."
                                )
                            elif not (
                                isinstance(unit_costs_ch_dict, dict)
                                and any(
                                    v is not None for v in unit_costs_ch_dict.values()
                                )
                            ):
                                md_lines.append(
                                    f"Подрядчик {contractor_name_s} {label_suffix_str} не указал стоимость."
                                )

                            if (
                                pos_org_qty_cost_val is not None
                                and pos_org_qty_cost_val
                                != (total_costs_ch_dict.get(JSON_KEY_TOTAL, 0) or 0)
                            ):
                                md_lines.append(
                                    f"При этом полная стоимость {label_suffix_str} за объемы заказчика составляет {pos_org_qty_cost_val} руб."
                                )

                            if pos_comm_contr_s:
                                md_lines.append(
                                    f"Комментарий {contractor_name_s} {label_suffix_str}: {pos_comm_contr_s}"
                                )
                            md_lines.append("")
                    else:
                        md_lines.append(
                            f"###### {visible_item_idx_num}. **{pos_name_s}**{section_info_display_str}  "
                        )
                        visible_item_idx_num += 1

                        if pos_comm_org_s:
                            md_lines.append(
                                f"  \nПри подготовке тендерного задания по данной позиции организатор указал следующий комментарий: «{pos_comm_org_s}»"
                            )

                        quantity_display = (
                            sanitize_text(pos_quantity_val)
                            if pos_quantity_val is not None
                            else "Н/Д"
                        )
                        if quantity_display:
                            md_lines.append(
                                f"  \nОбъем работ по тендерному заданию для данной позиции составляет {quantity_display} {pos_unit_s}."
                            )
                        else:
                            md_lines.append(
                                f"  \nПо данной позиции согласно тендерного задания объем работ не указан."
                            )

                        if (
                            pos_sugg_qty_val is not None
                            and pos_sugg_qty_val != pos_quantity_val
                        ):
                            md_lines.append(
                                f"  \nУчастник тендера {contractor_name_s} при подготовке предложения указал следующий объем работ по данной позиции, который он считает корректным: {sanitize_text(pos_sugg_qty_val)} {pos_unit_s}."
                            )

                        uc_dict = pos_item_data.get(JSON_KEY_UNIT_COST, {})
                        uc_total = uc_dict.get(JSON_KEY_TOTAL, 0)
                        uc_mat = uc_dict.get(JSON_KEY_MATERIALS, 0)
                        uc_wrk = uc_dict.get(JSON_KEY_WORKS, 0)
                        uc_ind = uc_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                        md_lines.append(
                            f"  \nЕдиничная стоимость позиции {pos_name_s} у {contractor_name_s} составляет {uc_total} руб/{pos_unit_s}, в том числе включены "
                            f"единичная стоимость материалов — {uc_mat} руб/{pos_unit_s}, "
                            f"единичная стоимость работ СМР — {uc_wrk} руб/{pos_unit_s}, "
                            f"единичная стоимость косвенных расходов — {uc_ind} руб/{pos_unit_s}."
                        )

                        tc_dict = pos_item_data.get(JSON_KEY_TOTAL_COST, {})
                        tc_total = tc_dict.get(JSON_KEY_TOTAL, 0)
                        tc_mat = tc_dict.get(JSON_KEY_MATERIALS, 0)
                        tc_wrk = tc_dict.get(JSON_KEY_WORKS, 0)
                        tc_ind = tc_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                        md_lines.append(
                            f"  \nПолная стоимость позиции {pos_name_s} у {contractor_name_s} составляет {tc_total} руб., в том числе "
                            f"стоимость материалов — {tc_mat} руб., "
                            f"стоимость работ СМР — {tc_wrk} руб., "
                            f"стоимость косвенных расходов — {tc_ind} руб."
                        )

                        if (
                            pos_org_qty_cost_val is not None
                            and pos_org_qty_cost_val != tc_total
                        ):
                            md_lines.append(
                                f"pos_org_qty_cost_val - {pos_org_qty_cost_val}. tc_total - {tc_total}."
                            )
                            md_lines.append(
                                f"  \nУчитывая, что подрядчик указал собственные объемы работ по данной позиции, то стоимость предложения за объемы заказчика при тех же единичных расценках составляет {pos_org_qty_cost_val} руб."
                            )
                        if pos_comm_contr_s:
                            md_lines.append(
                                f"  \nУчастник тендера при подготовке предложения указал следующий комментарий к позиции: «{pos_comm_contr_s}»"
                            )
                        md_lines.append("  \n")
        md_lines.append("\n---")
    return md_lines, initial_metadata
