from .get_items_dict import get_items_dict
from .parse_contractor_row import parse_contractor_row

def get_positions(ws, contractor):
    """
    Извлекает все детализированные позиции работ/материалов и отдельно
    итоговые/суммирующие строки, относящиеся к конкретному подрядчику,
    из листа Excel.

    Функция начинает чтение данных с предопределенной строки (13-я) и
    продолжает до тех пор, пока не встретит полностью пустую строку.
    Она различает два режима обработки строк:
    1.  'normal': для обычных строк с детализированными позициями. Эти позиции
        добавляются в словарь `positions`.
    2.  'merged_mode': для итоговых/суммирующих строк, которые обычно
        начинаются с объединенной ячейки. Эти строки добавляются в словарь
        `summary`.

    Переключение в 'merged_mode' происходит, если первая ячейка текущей строки
    является объединенной (и функция была в режиме 'normal'), и после этого
    функция остается в этом режиме до конца обработки данного подрядчика.

    Args:
        ws (openpyxl.worksheet.worksheet.Worksheet): Лист Excel, с которого
            считываются данные.
        contractor (dict): Словарь, содержащий информацию о подрядчике.
            Должен включать:
            - "merged_shape": {"colspan": int} - информация о количестве колонок,
              занимаемых данными подрядчика.
            - "column_start": int - начальная колонка данных этого подрядчика
              (ожидается функцией `parse_contractor_row`).
            - "value": str (опционально, используется для отладочного вывода) -
              имя или идентификатор подрядчика.

    Returns:
        dict: Словарь с двумя ключами:
            - "positions" (dict): Словарь, где ключи - это строки с порядковыми
              номерами детализированных позиций ("1", "2", ...), а значения -
              словари, описывающие каждую такую позицию. **Итоговые строки сюда НЕ попадают.**
            - "summary" (dict): Словарь, где ключи - это строки, идентифицирующие
              итоговые показатели (например, "ИТОГО С НДС", "НДС", или
              сгенерированный ключ вида "merged_{номер_строки}"),
              а значения - словари, описывающие эти итоговые строки.
              **Эти строки НЕ дублируются в словаре "positions".**

    Side effects:
        - Печатает отладочную информацию в консоль при старте функции и на
          каждой итерации обработки строки.
    """
    # Отладочный вывод
    print("==== START get_positions for contractor ====")

    positions = {}  # Словарь для детализированных позиций
    summary = {}    # Словарь только для итоговых/суммирующих строк
    start_row = 13
    
    contractor_colspan = contractor["merged_shape"]["colspan"]
    merged_ranges = ws.merged_cells.ranges

    mode = "normal"
    index_item = 1 # Счетчик только для детализированных позиций

    while True:
        row_cells = ws[start_row]
        first_cell = row_cells[0]
        first_coord = first_cell.coordinate

        print(f"{start_row=}, {mode=}, {first_cell.value=}, {contractor.get('value', 'N/A')=}")

        if all(cell.value is None for cell in row_cells):
            break

        if mode == "normal" and any(first_coord in r.coord for r in merged_ranges):
            mode = "merged_mode"

        if mode == "normal":
            item = get_items_dict(contractor_colspan)

            item["порядковый номер"] = ws.cell(row=start_row, column=1).value
            item["номер раздела"] = ws.cell(row=start_row, column=2).value
            item["статья смр"] = ws.cell(row=start_row, column=3).value
            item["наименование работ"] = ws.cell(row=start_row, column=4).value
            # Измененное поле:
            item["комментарий организатора"] = ws.cell(row=start_row, column=6).value
            item["единица измерения"] = ws.cell(row=start_row, column=7).value
            item["количество"] = ws.cell(row=start_row, column=8).value

            contractor_data = parse_contractor_row(ws, start_row, contractor)
            item.update(contractor_data)
            
            # Добавляем только "нормальные" позиции в positions
            positions[str(index_item)] = item
            index_item += 1

        else: # mode == "merged_mode"
            raw_label = str(first_cell.value).strip().lower() if first_cell.value else ""
            
            key_summary = None
            if "итого" in raw_label and "ндс" in raw_label:
                key_summary = "ИТОГО С НДС"
            elif "в том числе ндс" in raw_label or ("ндс" in raw_label and "итого" not in raw_label):
                key_summary = "НДС"
            elif "отклонение от расчетной стоимости" in raw_label:
                key_summary = "Отклонение от расчетной стоимости"
            elif "первоначальная стоимость" in raw_label:
                key_summary = "Первоначальная стоимость"
            else:
                key_summary = f"merged_{start_row}"
            
            item_summary = { # Переименовал item в item_summary для ясности
                "наименование работ": first_cell.value,
            }
            contractor_data = parse_contractor_row(ws, start_row, contractor)
            item_summary.update(contractor_data)
            
            # Добавляем только итоговые строки в summary
            summary[key_summary] = item_summary

        start_row += 1

    return {
        "positions": positions,
        "summary": summary
    }