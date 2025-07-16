# tests/helpers/test_postprocess.py

import pytest
from helpers.postprocess import (
    _clean_deviation_fields,
    replace_div0_with_null,
    annotate_structure_fields,
    DataIntegrityError,
    normalize_lots_json_structure,
    _is_value_zero # Импортируем для прямого тестирования
)
from constants import (
    JSON_KEY_BASELINE_PROPOSAL,
    JSON_KEY_CHAPTER_NUMBER,
    JSON_KEY_CONTRACTOR_ITEMS,
    JSON_KEY_CONTRACTOR_POSITIONS,
    JSON_KEY_CONTRACTOR_SUMMARY,
    JSON_KEY_CONTRACTOR_TITLE,
    JSON_KEY_DEVIATION_FROM_CALCULATED_COST,
    JSON_KEY_LOTS,
    JSON_KEY_PROPOSALS,
    JSON_KEY_TOTAL_COST,
    TABLE_PARSE_BASELINE_COST,
    JSON_KEY_IS_CHAPTER,
    JSON_KEY_CHAPTER_REF
)

# =================================================================
# 1. Тесты для `replace_div0_with_null`
# =================================================================

def test_replace_div0_with_null_replaces_all_error_types():
    """Проверяет замену всех вариантов ошибок деления на ноль."""
    input_data = {
        'err1': '#DIV/0!',
        'err2': '  div/0  ',
        'err3': 'деление на 0',
        'items': [{'value': '#DIV/0!'}]
    }
    expected = {
        'err1': None,
        'err2': None,
        'err3': None,
        'items': [{'value': None}]
    }
    assert replace_div0_with_null(input_data) == expected

def test_replace_div0_with_null_does_not_change_valid_data():
    """Проверяет, что корректные данные остаются без изменений."""
    input_data = {'value': 'Some string', 'cost': 100.5, 'items': [1, 2]}
    assert replace_div0_with_null(input_data) == input_data

# =================================================================
# 2. Тесты для `_is_value_zero`
# =================================================================

@pytest.mark.parametrize("value", [
    None, 0, "0", "0.0", "", "0,0", "  NONE  "
])
def test_is_value_zero_returns_true_for_zero_values(value):
    """Проверяет, что функция возвращает True для всех "нулевых" значений."""
    assert _is_value_zero(value) is True

@pytest.mark.parametrize("value", [
    1, -1, "100", "some text", 0.1
])
def test_is_value_zero_returns_false_for_non_zero_values(value):
    """Проверяет, что функция возвращает False для ненулевых значений."""
    assert _is_value_zero(value) is False

# =================================================================
# 3. Тесты для `annotate_structure_fields`
# =================================================================

def test_annotate_structure_fields_happy_path():
    """Тестирует базовую аннотацию разделов, подразделов и позиций."""
    positions = {
        "1": {JSON_KEY_CHAPTER_NUMBER: "1"},
        "2": {"description": "Work in section 1"},
        "3": {JSON_KEY_CHAPTER_NUMBER: "1.1"},
        "4": {"description": "Work in subsection 1.1"},
    }
    # Функция возвращает новый словарь
    annotated = annotate_structure_fields(positions)

    assert annotated["1"][JSON_KEY_IS_CHAPTER] is True
    assert annotated["1"][JSON_KEY_CHAPTER_REF] is None # Верхний уровень
    assert annotated["2"][JSON_KEY_IS_CHAPTER] is False
    assert annotated["2"][JSON_KEY_CHAPTER_REF] == "1"
    assert annotated["3"][JSON_KEY_IS_CHAPTER] is True
    assert annotated["3"][JSON_KEY_CHAPTER_REF] == "1" # Ссылка на родителя
    assert annotated["4"][JSON_KEY_IS_CHAPTER] is False
    assert annotated["4"][JSON_KEY_CHAPTER_REF] == "1.1"

def test_annotate_structure_fields_empty_input():
    """Проверяет, что функция корректно обрабатывает пустой ввод."""
    assert annotate_structure_fields({}) == {}

# tests/helpers/test_postprocess.py

def test_annotate_structure_fields_with_non_integer_keys(caplog):
    """
    Проверяет, что функция не падает и логирует предупреждение,
    если ключи позиций не являются числами.
    """
    # Arrange: создаем "плохие" данные с нечисловым ключом
    positions = {
        "1": {"description": "Work 1"},
        "abc": {"description": "Work with non-int key"}
    }
    
    # Act: вызываем функцию
    annotated = annotate_structure_fields(positions)

    # Assert:
    # 1. Проверяем, что функция все равно отработала и вернула результат
    assert "abc" in annotated
    assert "1" in annotated

    # 2. Проверяем, что было записано предупреждение в лог
    assert "Не удалось отсортировать позиции" in caplog.text

def test_annotate_structure_fields_handles_non_dict_input():
    """
    Проверяет, что annotate_structure_fields возвращает пустой словарь,
    если на вход подан не словарь, покрывая защитный код.
    """
    assert annotate_structure_fields(None) == {}
    assert annotate_structure_fields("не словарь") == {}



# =================================================================
# 4. Тесты для `normalize_lots_json_structure`
# =================================================================

@pytest.fixture
def sample_tender_data():
    """Фикстура pytest: предоставляет базовую структуру тендера для тестов."""
    return {
        JSON_KEY_LOTS: {
            "lot_1": {
                JSON_KEY_PROPOSALS: {
                    "proposal_1": {
                        JSON_KEY_CONTRACTOR_TITLE: "Подрядчик 1",
                        JSON_KEY_CONTRACTOR_ITEMS: {
                            JSON_KEY_CONTRACTOR_POSITIONS: {
                                "1": {"description": "Работа 1", JSON_KEY_DEVIATION_FROM_CALCULATED_COST: 10}
                            },
                            JSON_KEY_CONTRACTOR_SUMMARY: {
                                JSON_KEY_DEVIATION_FROM_CALCULATED_COST: {"total": 10}
                            }
                        }
                    },
                    "proposal_2": {
                        JSON_KEY_CONTRACTOR_TITLE: TABLE_PARSE_BASELINE_COST,
                        JSON_KEY_CONTRACTOR_ITEMS: {
                            JSON_KEY_CONTRACTOR_SUMMARY: {
                                "some_total": {
                                    JSON_KEY_TOTAL_COST: {"value": 1000}
                                }
                            }
                        }
                    }
                }
            }
        }
    }

def test_normalize_with_valid_baseline(sample_tender_data):
    """
    Тест "счастливого пути": Расчетная стоимость найдена и валидна.
    """
    result = normalize_lots_json_structure(sample_tender_data)
    lot_1 = result[JSON_KEY_LOTS]["lot_1"]

    # 1. baseline_proposal должен быть создан и содержать данные "Расчетной стоимости"
    assert lot_1[JSON_KEY_BASELINE_PROPOSAL][JSON_KEY_CONTRACTOR_TITLE] == TABLE_PARSE_BASELINE_COST

    # 2. В proposals должен остаться только "Подрядчик 1" под новым ключом
    assert len(lot_1[JSON_KEY_PROPOSALS]) == 1
    contractor_1 = lot_1[JSON_KEY_PROPOSALS]["contractor_1"]
    assert contractor_1[JSON_KEY_CONTRACTOR_TITLE] == "Подрядчик 1"

    # 3. Поля отклонений у "Подрядчика 1" должны остаться на месте
    pos_1 = contractor_1[JSON_KEY_CONTRACTOR_ITEMS][JSON_KEY_CONTRACTOR_POSITIONS]["1"]
    assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST in pos_1

def test_normalize_with_invalid_baseline(sample_tender_data):
    """
    Тест, когда "Расчетная стоимость" есть, но пустая (невалидная).
    """
    # Arrange: "обнуляем" расчетную стоимость
    baseline = sample_tender_data[JSON_KEY_LOTS]["lot_1"][JSON_KEY_PROPOSALS]["proposal_2"]
    baseline[JSON_KEY_CONTRACTOR_ITEMS][JSON_KEY_CONTRACTOR_SUMMARY]["some_total"][JSON_KEY_TOTAL_COST]["value"] = "0.0"

    result = normalize_lots_json_structure(sample_tender_data)
    lot_1 = result[JSON_KEY_LOTS]["lot_1"]

    # 1. baseline_proposal должен сообщать об отсутствии стоимости
    assert lot_1[JSON_KEY_BASELINE_PROPOSAL][JSON_KEY_CONTRACTOR_TITLE] == "Расчетная стоимость отсутствует"

    # 2. Поля отклонений у "Подрядчика 1" должны быть удалены
    contractor_1 = lot_1[JSON_KEY_PROPOSALS]["contractor_1"]
    pos_1 = contractor_1[JSON_KEY_CONTRACTOR_ITEMS][JSON_KEY_CONTRACTOR_POSITIONS]["1"]
    summary = contractor_1[JSON_KEY_CONTRACTOR_ITEMS][JSON_KEY_CONTRACTOR_SUMMARY]

    assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST not in pos_1
    assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST not in summary

def test_normalize_without_baseline(sample_tender_data):
    """
    Тест, когда предложения "Расчетная стоимость" нет вообще.
    """
    # Arrange: удаляем "Расчетную стоимость" из предложений
    del sample_tender_data[JSON_KEY_LOTS]["lot_1"][JSON_KEY_PROPOSALS]["proposal_2"]

    result = normalize_lots_json_structure(sample_tender_data)
    lot_1 = result[JSON_KEY_LOTS]["lot_1"]

    # 1. baseline_proposal должен сообщать об отсутствии стоимости
    assert lot_1[JSON_KEY_BASELINE_PROPOSAL][JSON_KEY_CONTRACTOR_TITLE] == "Расчетная стоимость отсутствует"

    # 2. Поля отклонений у "Подрядчика 1" также должны быть удалены
    contractor_1 = lot_1[JSON_KEY_PROPOSALS]["contractor_1"]
    pos_1 = contractor_1[JSON_KEY_CONTRACTOR_ITEMS][JSON_KEY_CONTRACTOR_POSITIONS]["1"]
    assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST not in pos_1

def test_normalize_raises_error_on_malformed_position(sample_tender_data):
    """
    Проверяет, что normalize_lots_json_structure падает с ошибкой DataIntegrityError,
    если одна из позиций не является словарем (например, None).
    """
    # Arrange: добавляем "сломанные" данные
    positions = sample_tender_data["lots"]["lot_1"]["proposals"]["proposal_1"]["contractor_items"]["positions"]
    positions["2"] = None  # Некорректная позиция

    # Act & Assert: Проверяем, что при вызове функции будет вызвано именно наше исключение
    with pytest.raises(DataIntegrityError) as excinfo:
        normalize_lots_json_structure(sample_tender_data)
    
    # Опционально, но полезно: проверяем текст ошибки
    assert "Ожидался словарь, но получен тип NoneType" in str(excinfo.value)

def test_normalize_handles_missing_contractor_items(sample_tender_data):
    """
    Проверяет, что normalize не падает, если у подрядчика
    поле 'contractor_items' отсутствует, покрывая защитный код в _clean_deviation_fields.
    """
    # Arrange:
    # 1. Делаем baseline невалидным, чтобы точно вызвать функцию _clean_deviation_fields
    baseline = sample_tender_data["lots"]["lot_1"]["proposals"]["proposal_2"]
    baseline["contractor_items"]["summary"]["some_total"]["total_cost"]["value"] = 0
    
    # 2. Удаляем поле 'contractor_items' у реального подрядчика
    del sample_tender_data["lots"]["lot_1"]["proposals"]["proposal_1"]["contractor_items"]

    # Act & Assert: Проверяем, что функция не падает с ошибкой
    try:
        result = normalize_lots_json_structure(sample_tender_data)
        # Проверяем, что подрядчик остался на месте, но без items
        contractor_1 = result["lots"]["lot_1"]["proposals"]["contractor_1"]
        assert "contractor_items" not in contractor_1
    except Exception as e:
        pytest.fail(f"Функция упала на данных с отсутствующим 'contractor_items': {e}")

def test_clean_deviation_fields_handles_malformed_items():
    """
    Проверяет, что _clean_deviation_fields не падает, если 'contractor_items'
    не является словарем, покрывая последнюю строку.
    """
    # Arrange: создаем предложение, где 'items' - это None
    proposals = {
        "Подрядчик 1": {
            "title": "Подрядчик 1",
            "contractor_items": None # Некорректные данные
        }
    }

    # Act & Assert: Проверяем, что функция не падает с ошибкой
    try:
        cleaned = _clean_deviation_fields(proposals)
        # Проверяем, что подрядчик остался, а его items по-прежнему None
        assert cleaned["Подрядчик 1"]["contractor_items"] is None
    except Exception as e:
        pytest.fail(f"_clean_deviation_fields упала на некорректных 'items': {e}")