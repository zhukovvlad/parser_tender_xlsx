"""
markdown_utils/json_to_markdown.py

Модуль для преобразования структурированных JSON-данных о тендере в Markdown.

Содержит функцию `generate_markdown_for_lots`, которая принимает полный JSON-объект
данных тендера и генерирует:
1.  Словарь, где ключ - это идентификатор лота, а значение - список строк
    в формате Markdown для этого лота. Каждый такой список является
    полноценным документом, содержащим как общую информацию о тендере,
    так и детализацию по конкретному лоту.
2.  Словарь с основной (заголовочной) информацией о тендере и исполнителе.
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
from ..excel_parser.sanitize_text import sanitize_object_and_address_text, sanitize_text


def _safe_float(val: Any) -> float:
    """Безопасно преобразует значение в float, возвращая 0.0 в случае ошибки."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def generate_markdown_for_lots(
    data: Dict[str, Any], ai_results: Optional[List[Dict]] = None, lot_ids_map: Optional[Dict[str, int]] = None
) -> Tuple[Dict[str, List[str]], Dict[str, Optional[str]]]:
    """
    Преобразует JSON-объект в отдельные Markdown-документы для каждого лота.

    Функция генерирует общую "шапку" с информацией о тендере и исполнителе,
    а затем для каждого лота в исходных данных создает свой список строк
    Markdown, добавляя в начало эту общую шапку.

    Args:
        data: JSON данные тендера
        ai_results: Результаты AI обработки (опционально)
        lot_ids_map: Маппинг лотов к их реальным ID (опционально)
    """
    # --- 1. Генерация общей "шапки" и метаданных (информация о тендере и исполнителе) ---
    header_md_lines: List[str] = []
    tender_id_val = data.get(JSON_KEY_TENDER_ID, "N/A")
    title_val = sanitize_text(data.get(JSON_KEY_TENDER_TITLE, "Без названия"))
    obj_val = sanitize_object_and_address_text(data.get(JSON_KEY_TENDER_OBJECT, ""))
    addr_val = sanitize_object_and_address_text(data.get(JSON_KEY_TENDER_ADDRESS, ""))

    header_md_lines.append(f"# Тендер №{tender_id_val} «{title_val}».")
    if obj_val or addr_val:
        header_md_lines.append("")
    if obj_val:
        header_md_lines.append(f"**Объект:** {obj_val}.  ")
    if addr_val:
        header_md_lines.append(f"**Адрес:** {addr_val}.")
    if obj_val or addr_val:
        header_md_lines.append("")

    executor = data.get(JSON_KEY_EXECUTOR, {})
    exec_name_s: Optional[str] = None
    exec_phone_s: Optional[str] = None
    exec_date_s: Optional[str] = None

    if executor:
        exec_name_s = sanitize_text(executor.get(JSON_KEY_EXECUTOR_NAME, "Неизвестный исполнитель"))
        exec_phone_s = sanitize_text(executor.get(JSON_KEY_EXECUTOR_PHONE, "Не указан"))
        exec_date_s = sanitize_text(executor.get(JSON_KEY_EXECUTOR_DATE, "Не указана"))

        header_md_lines.append(f"**Исполнитель:** {exec_name_s}.  ")
        header_md_lines.append(f"**Телефон:** {exec_phone_s}.  ")
        header_md_lines.append(f"**Дата документа:** {exec_date_s}.")
        header_md_lines.append("")

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
        k: v for k, v in initial_metadata.items() if v is not None and (str(v).strip() != "" or k == "tender_id")
    }

    # --- 2. Обработка лотов и генерация отдельных MD-документов ---
    lot_markdowns: Dict[str, List[str]] = {}

    for lot_key_str, lot_data_dict in data.get(JSON_KEY_LOTS, {}).items():
        lot_specific_md_lines = list(header_md_lines)

        lot_title_s = sanitize_text(lot_data_dict.get(JSON_KEY_LOT_TITLE, "Лот без названия"))
        lot_specific_md_lines.append(f"\n---\n\n## {sanitize_text(lot_key_str).upper()}: {lot_title_s}\n")

        # --- AI СЕКЦИЯ ---
        if ai_results and lot_ids_map:
            real_lot_id = lot_ids_map.get(lot_key_str)
            if real_lot_id:
                # Ищем AI результат для этого лота
                ai_by_lot_id = {str(result.get("lot_id")): result for result in ai_results}
                lot_ai_result = ai_by_lot_id.get(str(real_lot_id))

                if lot_ai_result:
                    lot_specific_md_lines.append("### 🤖 AI Анализ документа\n")

                    # Категория и дата обработки
                    category = lot_ai_result.get("category", "Не определена")
                    processed_at = lot_ai_result.get("processed_at", "")
                    lot_specific_md_lines.append(f"**Категория:** {category}  ")
                    if processed_at:
                        lot_specific_md_lines.append(f"**Обработано:** {processed_at}\n")

                    # RAW JSON данные - ищем в правильном поле
                    extraction_data = lot_ai_result.get("extraction_data") or lot_ai_result.get("ai_data")
                    if extraction_data:
                        lot_specific_md_lines.append("#### 📊 Извлеченные технические данные:\n")
                        lot_specific_md_lines.append("```json")
                        import json

                        lot_specific_md_lines.append(json.dumps(extraction_data, ensure_ascii=False, indent=2))
                        lot_specific_md_lines.append("```\n")
                    else:
                        lot_specific_md_lines.append("*AI данные не найдены или не обработаны*\n")

        # -- 3.1 Расчетная стоимость (Baseline Proposal) --
        baseline_prop = lot_data_dict.get(JSON_KEY_BASELINE_PROPOSAL, {})
        baseline_prop_title = sanitize_text(baseline_prop.get(JSON_KEY_CONTRACTOR_TITLE, ""))

        if baseline_prop_title == "Расчетная стоимость отсутствует":
            lot_specific_md_lines.append(f"### Расчетная стоимость\n")
            lot_specific_md_lines.append("Не предоставлялась или не валидна.\n")
        elif baseline_prop:
            lot_specific_md_lines.append(f"### Расчетная стоимость\n")
            lot_specific_md_lines.append(f'**Название:** "{baseline_prop_title}"')
            baseline_summary_items = baseline_prop.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(
                JSON_KEY_CONTRACTOR_SUMMARY, {}
            )
            if baseline_summary_items:
                lot_specific_md_lines.append("**Итоги:**")
                has_baseline_output = False
                for label_key, values_s_dict in baseline_summary_items.items():
                    if isinstance(values_s_dict, dict):
                        total_cost_s_data = values_s_dict.get(JSON_KEY_TOTAL_COST, {})
                        if isinstance(total_cost_s_data, dict) and any(
                            v is not None for v in total_cost_s_data.values()
                        ):
                            has_baseline_output = True
                            display_label = sanitize_text(values_s_dict.get(JSON_KEY_JOB_TITLE, label_key)).capitalize()
                            lot_specific_md_lines.append(f"- **{display_label}:**")
                            for k_cost, v_cost in total_cost_s_data.items():
                                if v_cost is not None:
                                    lot_specific_md_lines.append(
                                        f"  - {sanitize_text(k_cost).capitalize()}: {v_cost} руб."
                                    )
                if not has_baseline_output:
                    lot_specific_md_lines.append(
                        f"  *Итоговые суммы для «{baseline_prop_title}» не найдены или пусты.*"
                    )
                lot_specific_md_lines.append("")
            else:
                lot_specific_md_lines.append(f"  *Раздел итогов для «{baseline_prop_title}» не найден.*\n")

        # -- 3.2 Предложения подрядчиков --
        for contractor_id_str, contractor_data in lot_data_dict.get(JSON_KEY_PROPOSALS, {}).items():
            contractor_name_s = sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_TITLE, "Неизвестный подрядчик"))
            lot_specific_md_lines.append(f"\n### {contractor_name_s}\n")

            # -- 3.2.1 Основные сведения о подрядчике (H4) --
            details_md_parts = []
            if inn_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_INN)):
                details_md_parts.append(f"**ИНН:** {inn_s}.")
            if addr_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_ADDRESS)):
                details_md_parts.append(f"**Адрес:** {addr_s}.")
            if accr_s := sanitize_text(contractor_data.get(JSON_KEY_CONTRACTOR_ACCREDITATION)):
                details_md_parts.append(f"**Статус аккредитации:** {accr_s}.")
            if details_md_parts:
                lot_specific_md_lines.append(f"#### Основные сведения о подрядчике\n")
                lot_specific_md_lines.append("  ".join(details_md_parts) + "  \n")

            # -- 3.2.2 Коммерческие условия (H4) --
            additional_info_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ADDITIONAL_INFO, {})
            if additional_info_dict:
                lot_specific_md_lines.append(f"#### Коммерческие условия {contractor_name_s}\n")
                lot_specific_md_lines.append(
                    f" Здесь описываются коммерческие условия, указанные {contractor_name_s} в предложении к тендеру {tender_id_val}.\n"
                )
                lot_specific_md_lines.append(
                    "  Коммерческие условия могут включать в себя различные аспекты, такие как сроки выполнения, условия оплаты, гарантии и т.д.\n"
                )
                lot_specific_md_lines.append("  Ниже приведены ключевые коммерческие условия, указанные подрядчиком:\n")
                for key_info, val_info in additional_info_dict.items():
                    lot_specific_md_lines.append(
                        f"{sanitize_text(key_info)}: {sanitize_text(val_info) if val_info is not None else 'нет данных'}."
                    )
                lot_specific_md_lines.append("")

            # -- 3.2.3 Общие итоги по предложению подрядчика (H4) --
            contractor_summary_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(
                JSON_KEY_CONTRACTOR_SUMMARY, {}
            )
            if contractor_summary_dict:
                lot_specific_md_lines.append(f"#### Общие итоги по предложению {contractor_name_s}\n")
                summary_total_vat = contractor_summary_dict.get(JSON_KEY_TOTAL_COST_VAT, {}).get(
                    JSON_KEY_TOTAL_COST, {}
                )
                summary_vat_only = contractor_summary_dict.get(JSON_KEY_VAT, {}).get(JSON_KEY_TOTAL_COST, {})
                total_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_TOTAL, 0))
                vat_sum_val = sanitize_text(summary_vat_only.get(JSON_KEY_TOTAL, 0))
                lot_specific_md_lines.append(
                    f"Итоговая полная стоимость коммерческого предложения {contractor_name_s} по всем позициям составляет всего {total_sum_val} руб, "
                    f"в том числе НДС {vat_sum_val} руб."
                )
                materials_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_MATERIALS, 0))
                materials_vat_val = sanitize_text(summary_vat_only.get(JSON_KEY_MATERIALS, 0))
                lot_specific_md_lines.append(
                    f"Стоимость материалов составляет {materials_sum_val} руб, "
                    f"в том числе НДС {materials_vat_val} руб."
                )
                works_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_WORKS, 0))
                works_vat_val = sanitize_text(summary_vat_only.get(JSON_KEY_WORKS, 0))
                lot_specific_md_lines.append(
                    f"Стоимость работ СМР составляет {works_sum_val} руб, " f"в том числе НДС {works_vat_val} руб."
                )
                indirect_sum_val = sanitize_text(summary_total_vat.get(JSON_KEY_INDIRECT_COSTS, 0))
                indirect_vat_val = sanitize_text(summary_vat_only.get(JSON_KEY_INDIRECT_COSTS, 0))

                if _safe_float(indirect_sum_val) != 0 or _safe_float(indirect_vat_val) != 0:
                    lot_specific_md_lines.append(
                        f"Косвенные расходы составляют {indirect_sum_val} руб, "
                        f"в том числе НДС {indirect_vat_val} руб."
                    )
                lot_specific_md_lines.append("")

            # -- 3.2.4 Детализация позиций (H4) --
            lot_specific_md_lines.append(f"#### Детализация позиций ({contractor_name_s})\n")
            positions_dict = contractor_data.get(JSON_KEY_CONTRACTOR_ITEMS, {}).get(JSON_KEY_CONTRACTOR_POSITIONS, {})
            if not positions_dict:
                lot_specific_md_lines.append("*Позиции отсутствуют или не найдены.*\n")
            else:
                try:
                    sorted_positions_list = sorted(positions_dict.items(), key=lambda x: int(x[0]))
                except ValueError:
                    sorted_positions_list = sorted(positions_dict.items())

                visible_item_idx_num = 1
                for _, pos_item_data in sorted_positions_list:
                    if not isinstance(pos_item_data, dict):
                        continue

                    pos_name_s = sanitize_text(pos_item_data.get(JSON_KEY_JOB_TITLE, "Без названия"))
                    pos_unit_s = sanitize_text(pos_item_data.get(JSON_KEY_UNIT, "ед."))
                    pos_quantity_val = pos_item_data.get(JSON_KEY_QUANTITY)
                    pos_comm_org_s = sanitize_text(pos_item_data.get(JSON_KEY_COMMENT_ORGANIZER))
                    pos_comm_contr_s = sanitize_text(pos_item_data.get(JSON_KEY_COMMENT_CONTRACTOR))
                    pos_sugg_qty_val = pos_item_data.get(JSON_KEY_SUGGESTED_QUANTITY)
                    pos_org_qty_cost_val = pos_item_data.get(JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST)

                    is_chapter_f = pos_item_data.get("is_chapter", False)
                    chapter_num_s = sanitize_text(pos_item_data.get(JSON_KEY_CHAPTER_NUMBER, ""))
                    chapter_ref_s = sanitize_text(pos_item_data.get("chapter_ref", ""))

                    section_info_display_str = ""
                    if chapter_ref_s:
                        parent_label_str = "подразделу" if "." in chapter_ref_s else "разделу"
                        section_info_display_str = f" (относится к {parent_label_str} {chapter_ref_s})"

                    if is_chapter_f:
                        chapter_type_display = (
                            "Подраздел"
                            if isinstance(pos_item_data.get(JSON_KEY_CHAPTER_NUMBER), str)
                            and "." in pos_item_data.get(JSON_KEY_CHAPTER_NUMBER, "")
                            else "Раздел"
                        )
                        if not pos_name_s.lower().startswith("лот №"):
                            lot_specific_md_lines.append(
                                f"\n##### {chapter_type_display} {chapter_num_s}{section_info_display_str}: **{pos_name_s}**\n"
                            )

                            label_suffix_str = f'по {chapter_type_display.lower()}у {chapter_num_s} ("{pos_name_s}")'
                            unit_costs_ch_dict = pos_item_data.get(JSON_KEY_UNIT_COST, {})
                            if isinstance(unit_costs_ch_dict, dict) and any(
                                v is not None for v in unit_costs_ch_dict.values()
                            ):
                                materials_uc = unit_costs_ch_dict.get(JSON_KEY_MATERIALS, 0)
                                works_uc = unit_costs_ch_dict.get(JSON_KEY_WORKS, 0)
                                indirect_uc = unit_costs_ch_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                                total_uc = unit_costs_ch_dict.get(JSON_KEY_TOTAL, 0)
                                lot_specific_md_lines.append(
                                    f"Итоговая единичная стоимость {contractor_name_s} {label_suffix_str} составляет {total_uc} руб, "
                                    f"в том числе включены единичная стоимость материалов — {materials_uc} руб., "
                                    f"единичная стоимость работ СМР — {works_uc} руб, "
                                    f"единичная стоимость косвенных расходов — {indirect_uc} руб."
                                )

                            total_costs_ch_dict = pos_item_data.get(JSON_KEY_TOTAL_COST, {})
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
                                lot_specific_md_lines.append(
                                    f"Полная стоимость {contractor_name_s} {label_suffix_str}{org_qty_label} составляет {total_costs_ch_dict.get(JSON_KEY_TOTAL, 0)} руб, "
                                    f"в том числе: мат. — {total_costs_ch_dict.get(JSON_KEY_MATERIALS, 0)} руб., "
                                    f"раб. — {total_costs_ch_dict.get(JSON_KEY_WORKS, 0)} руб., "
                                    f"косв. — {total_costs_ch_dict.get(JSON_KEY_INDIRECT_COSTS, 0)} руб."
                                )
                            elif not (
                                isinstance(unit_costs_ch_dict, dict)
                                and any(v is not None for v in unit_costs_ch_dict.values())
                            ):
                                lot_specific_md_lines.append(
                                    f"Подрядчик {contractor_name_s} {label_suffix_str} не указал стоимость."
                                )

                            if pos_org_qty_cost_val is not None and pos_org_qty_cost_val != (
                                total_costs_ch_dict.get(JSON_KEY_TOTAL, 0) or 0
                            ):
                                lot_specific_md_lines.append(
                                    f"При этом полная стоимость {label_suffix_str} за объемы заказчика составляет {pos_org_qty_cost_val} руб."
                                )

                            if pos_comm_contr_s:
                                lot_specific_md_lines.append(
                                    f"Комментарий {contractor_name_s} {label_suffix_str}: {pos_comm_contr_s}"
                                )
                            lot_specific_md_lines.append("")
                    else:
                        lot_specific_md_lines.append(
                            f"###### {visible_item_idx_num}. **{pos_name_s}**{section_info_display_str}  "
                        )
                        visible_item_idx_num += 1

                        if pos_comm_org_s:
                            lot_specific_md_lines.append(
                                f"  \nПри подготовке тендерного задания по данной позиции организатор указал следующий комментарий: «{pos_comm_org_s}»"
                            )

                        quantity_display = sanitize_text(pos_quantity_val) if pos_quantity_val is not None else "Н/Д"
                        if quantity_display:
                            lot_specific_md_lines.append(
                                f"  \nОбъем работ по тендерному заданию для данной позиции составляет {quantity_display} {pos_unit_s}."
                            )
                        else:
                            lot_specific_md_lines.append(
                                f"  \nПо данной позиции согласно тендерного задания объем работ не указан."
                            )

                        if pos_sugg_qty_val is not None and pos_sugg_qty_val != pos_quantity_val:
                            lot_specific_md_lines.append(
                                f"  \nУчастник тендера {contractor_name_s} при подготовке предложения указал следующий объем работ по данной позиции, который он считает корректным: {sanitize_text(pos_sugg_qty_val)} {pos_unit_s}."
                            )

                        uc_dict = pos_item_data.get(JSON_KEY_UNIT_COST, {})
                        uc_total = uc_dict.get(JSON_KEY_TOTAL, 0)
                        uc_mat = uc_dict.get(JSON_KEY_MATERIALS, 0)
                        uc_wrk = uc_dict.get(JSON_KEY_WORKS, 0)
                        uc_ind = uc_dict.get(JSON_KEY_INDIRECT_COSTS, 0)
                        lot_specific_md_lines.append(
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
                        lot_specific_md_lines.append(
                            f"  \nПолная стоимость позиции {pos_name_s} у {contractor_name_s} составляет {tc_total} руб., в том числе "
                            f"стоимость материалов — {tc_mat} руб., "
                            f"стоимость работ СМР — {tc_wrk} руб., "
                            f"стоимость косвенных расходов — {tc_ind} руб."
                        )

                        # --- ИЗМЕНЕНИЕ 1: Удален дублирующийся блок кода ---
                        if pos_org_qty_cost_val is not None and pos_org_qty_cost_val != tc_total:
                            lot_specific_md_lines.append(
                                f"  \nУчитывая, что подрядчик указал собственные объемы работ по данной позиции, то стоимость предложения за объемы заказчика при тех же единичных расценках составляет {pos_org_qty_cost_val} руб."
                            )

                        if pos_comm_contr_s:
                            lot_specific_md_lines.append(
                                f"  \nУчастник тендера при подготовке предложения указал следующий комментарий к позиции: «{pos_comm_contr_s}»"
                            )
                        lot_specific_md_lines.append("  \n")

        lot_markdowns[lot_key_str] = lot_specific_md_lines

    return lot_markdowns, initial_metadata
