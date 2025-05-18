from .get_items_dict import get_items_dict
from .parse_contractor_row import parse_contractor_row

def get_positions(ws, contractor):
    """
    Извлекает все товарные позиции, работы (далее - позиции) и итоговые строки,
    относящиеся к конкретному подрядчику, из листа Excel.

    Функция начинает чтение данных с предопределенной строки (по умолчанию 13-я)
    и продолжает до тех пор, пока не встретит полностью пустую строку.
    Она различает два режима обработки строк:
    1.  'normal': для обычных строк с позициями.
    2.  'merged_mode': для итоговых/суммирующих строк, которые обычно
        начинаются с объединенной ячейки.

    Переключение в 'merged_mode' происходит, если первая ячейка текущей строки
    является объединенной, и после этого функция остается в этом режиме.

    Все извлеченные строки (как обычные позиции, так и итоговые) добавляются
    в словарь `positions` под последовательными числовыми ключами. Итоговые строки
    дополнительно сохраняются в словарь `summary` под ключами, извлеченными из
    их наименований (например, "ИТОГО С НДС").

    Args:
        ws (openpyxl.worksheet.worksheet.Worksheet): Лист Excel, с которого
            считываются данные.
        contractor (dict): Словарь, содержащий информацию о подрядчике.
            Должен включать:
            - "merged_shape": {"colspan": int} - информация о количестве колонок,
              занимаемых данными подрядчика.
            - "column_start": int - начальная колонка данных этого подрядчика (ожидается
              функцией `parse_contractor_row`).
            - "value": str (опционально, используется для отладочного вывода) -
              имя или идентификатор подрядчика.

    Returns:
        dict: Словарь с двумя ключами:
            - "positions" (dict): Словарь, где ключи - это строки с порядковыми
              номерами позиций ("1", "2", ...), а значения - словари,
              описывающие каждую позицию. Сюда попадают как обычные
              позиции, так и итоговые строки.
            - "summary" (dict): Словарь, где ключи - это строки, идентифицирующие
              итоговые показатели (например, "ИТОГО С НДС", "НДС",
              "Отклонение от расчетной стоимости", "Первоначальная стоимость" или
              сгенерированный ключ вида "merged_{номер_строки}"),
              а значения - словари, описывающие эти итоговые строки.
              Каждая запись из `summary` также присутствует в `positions`
              под своим порядковым номером.

    Side effects:
        - Печатает отладочную информацию в консоль при старте функции и на
          каждой итерации обработки строки.
    """
    # Отладочный вывод
    print("==== START get_positions for contractor ====")

    positions = {}  # Словарь для всех позиций (включая итоговые)
    summary = {}    # Словарь только для итоговых/суммирующих строк
    start_row = 13  # Начальная строка для чтения позиций
    
    # Получаем количество колонок, занимаемых данными подрядчика
    contractor_colspan = contractor["merged_shape"]["colspan"]
    # Получаем информацию обо всех объединенных ячейках на листе
    merged_ranges = ws.merged_cells.ranges

    mode = "normal"  # Начальный режим обработки строк
    index_item = 1   # Счетчик для ключей в словаре positions

    while True:
        row_cells = ws[start_row]  # Получаем все ячейки текущей строки
        first_cell = row_cells[0]  # Первая ячейка строки (колонка A)
        first_coord = first_cell.coordinate # Координата первой ячейки

        # Отладочный вывод текущего состояния
        print(f"{start_row=}, {mode=}, {first_cell.value=}, {contractor.get('value', 'N/A')=}")

        # Условие выхода из цикла: если текущая строка полностью пустая
        if all(cell.value is None for cell in row_cells):
            break

        # Переключение режима, если первая ячейка объединена и мы в 'normal' режиме
        # После переключения режим не меняется обратно на 'normal'
        if mode == "normal" and any(first_coord in r.coord for r in merged_ranges): # Исправлено: r.coord
            mode = "merged_mode"

        # --- Обработка в обычном режиме ('normal') ---
        if mode == "normal":
            # Получаем шаблон для текущей позиции
            item = get_items_dict(contractor_colspan)

            # Заполняем общие поля позиции из фиксированных колонок
            item["порядковый номер"] = ws.cell(row=start_row, column=1).value
            item["номер раздела"] = ws.cell(row=start_row, column=2).value
            item["статья смр"] = ws.cell(row=start_row, column=3).value
            item["наименование работ"] = ws.cell(row=start_row, column=4).value
            item["комментарий организатора"] = ws.cell(row=start_row, column=6).value # Колонка 5 пропускается?
            item["единица измерения"] = ws.cell(row=start_row, column=7).value
            item["количество"] = ws.cell(row=start_row, column=8).value

            # Заполняем данные, специфичные для подрядчика
            contractor_data = parse_contractor_row(ws, start_row, contractor)
            item.update(contractor_data)

        # --- Обработка в режиме объединенных ячеек ('merged_mode') ---
        # Сюда попадают строки, начиная с первой обнаруженной объединенной ячейки в колонке A
        else: # mode == "merged_mode"
            raw_label = str(first_cell.value).strip().lower() if first_cell.value else ""
            
            key_summary = None # Ключ для словаря summary
            if "итого" in raw_label and "ндс" in raw_label: # Более точное условие для "ИТОГО С НДС"
                key_summary = "ИТОГО С НДС"
            elif "в том числе ндс" in raw_label or ("ндс" in raw_label and "итого" not in raw_label): # Условие для "НДС"
                key_summary = "НДС"
            elif "отклонение от расчетной стоимости" in raw_label:
                key_summary = "Отклонение от расчетной стоимости"
            elif "первоначальная стоимость" in raw_label:
                key_summary = "Первоначальная стоимость"
            else:
                key_summary = f"merged_{start_row}" # Общий ключ для неопознанных объединенных строк
            
            # Создаем элемент для итоговой строки
            item = {
                "наименование работ": first_cell.value, # Основное описание из первой (объединенной) ячейки
            }
            # Добавляем данные подрядчика для этой итоговой строки
            contractor_data = parse_contractor_row(ws, start_row, contractor)
            item.update(contractor_data)
            
            # Сохраняем итоговую строку в словарь summary
            summary[key_summary] = item

        # Сохраняем текущий 'item' (обычную позицию или итоговую строку)
        # в общий словарь 'positions' под порядковым номером.
        # Это означает, что итоговые строки также будут в 'positions'.
        positions[str(index_item)] = item
        index_item += 1
        start_row += 1

    return {
        "positions": positions,
        "summary": summary
    }