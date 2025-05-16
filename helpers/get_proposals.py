from .get_additional_info import get_additional_info
from .get_positions import get_positions
from .read_contractors import read_contractors

def get_proposals(ws):
    """
    Извлекает и структурирует данные по предложениям всех подрядчиков с листа Excel.

    Функция сначала получает список подрядчиков с помощью `read_contractors`.
    Затем для каждого подрядчика из списка (начиная со второго элемента,
    т.е. с индексом 1) собирается подробная информация, включая:
    - Основные данные: наименование, ИНН, адрес, сведения об аккредитации,
      координата основной ячейки, ее ширина и высота.
    - Детализированные позиции: получается с помощью функции `get_positions`.
    - Дополнительная информация: получается с помощью функции `get_additional_info`.

    ИНН, адрес и сведения об аккредитации извлекаются из ячеек, расположенных
    относительно начальной ячейки подрядчика, только если высота объединенной
    ячейки подрядчика (`rowspan`) равна 1.

    Результатом является словарь, где каждый ключ — это идентификатор подрядчика
    (например, "contractor_1"), а значение — словарь с полной информацией
    по этому подрядчику.

    Предполагается, что лист Excel имеет определенную структуру, и подрядчики
    в нем перечислены особым образом, который учитывается функцией `read_contractors`.
    При изменении структуры листа может потребоваться адаптация этой функции
    и вызываемых ею модулей.

    Args:
        ws (openpyxl.worksheet.worksheet.Worksheet): Лист Excel (объект openpyxl),
            с которого считываются данные о предложениях.

    Returns:
        dict: Словарь, где ключи - это строковые идентификаторы подрядчиков
              (например, "contractor_1", "contractor_2", ...), а значения -
              словари с подробной информацией по каждому подрядчику.
              Структура информации по каждому подрядчику:
              {
                  "name": str,  # Наименование подрядчика
                  "inn": str | None,  # ИНН (если доступно и rowspan == 1)
                  "address": str | None,  # Адрес (если доступно и rowspan == 1)
                  "accreditation": str | None,  # Сведения об аккредитации (если доступно и rowspan == 1)
                  "coordinate": str,  # Координата начальной ячейки подрядчика
                  "width": int,  # Ширина объединенной ячейки подрядчика (colspan)
                  "height": int,  # Высота объединенной ячейки подрядчика (rowspan)
                  "items": dict,  # Структура, возвращаемая get_positions()
                  "additional_info": dict  # Структура, возвращаемая get_additional_info()
              }
    """
    contractors_list = read_contractors(ws) # Получаем список словарей с данными о подрядчиках
    proposals = {}

    # Итерация по списку подрядчиков.
    # range(1, ...) означает, что первый элемент contractors_list[0] (если он есть) пропускается.
    # Ключи в итоговом словаре будут "contractor_1", "contractor_2", ...
    for index in range(1, len(contractors_list)):
        contractor = contractors_list[index] # Текущий подрядчик

        # Извлечение основной информации о подрядчике
        contractor_name = contractor["value"] # Предполагается, что "value" содержит имя
        
        # ИНН, адрес и аккредитация извлекаются из следующих строк относительно начала блока подрядчика
        # contractor["row_start"] - строка, где начинается информация о подрядчике (его имя)
        # contractor["column_start"] - колонка, где начинается информация о подрядчике
        contractor_inn = ws.cell(row=contractor["row_start"] + 1, column=contractor["column_start"]).value
        contractor_address = ws.cell(row=contractor["row_start"] + 2, column=contractor["column_start"]).value
        contractor_accreditation = ws.cell(row=contractor["row_start"] + 3, column=contractor["column_start"]).value
        
        contractor_coordinate = contractor["coordinate"]
        contractor_width = contractor["merged_shape"]["colspan"] if "merged_shape" in contractor else 1
        contractor_height = contractor["merged_shape"]["rowspan"] if "merged_shape" in contractor else 1
        
        # Получение детализированных позиций и дополнительной информации
        contractor_items = get_positions(ws, contractor)
        contractor_additional_info = get_additional_info(ws, contractor)
        
        # Формирование словаря для текущего подрядчика
        proposals["contractor_" + str(index)] = {
            "name": contractor_name,
            # ИНН, адрес и аккредитация добавляются только если высота основной ячейки подрядчика равна 1
            "inn": contractor_inn if "merged_shape" in contractor and contractor["merged_shape"]["rowspan"] == 1 else None,
            "address": contractor_address if "merged_shape" in contractor and contractor["merged_shape"]["rowspan"] == 1 else None,
            "accreditation": contractor_accreditation if "merged_shape" in contractor and contractor["merged_shape"]["rowspan"] == 1 else None,
            "coordinate": contractor_coordinate,
            "width": contractor_width,
            "height": contractor_height,
            "items": contractor_items,
            "additional_info": contractor_additional_info,
        }
        
    return proposals