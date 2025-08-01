"""
Тесты для модуля get_items_dict.

Эти тесты проверяют реальное поведение функции get_items_dict,
которая создает шаблонные словари для позиций тендера.

Философия тестирования:
- Тестируем ПОВЕДЕНИЕ: какую структуру возвращает функция для разных colspan
- Проверяем КОНТРАКТ: что функция гарантирует клиентскому коду
- Валидируем ДАННЫЕ: корректность структуры возвращаемых словарей
"""

import pytest

from app.constants import (
    JSON_KEY_ARTICLE_SMR,
    JSON_KEY_CHAPTER_NUMBER,
    JSON_KEY_COMMENT_CONTRACTOR,
    JSON_KEY_COMMENT_ORGANIZER,
    JSON_KEY_DEVIATION_FROM_CALCULATED_COST,
    JSON_KEY_INDIRECT_COSTS,
    JSON_KEY_JOB_TITLE,
    JSON_KEY_MATERIALS,
    JSON_KEY_NUMBER,
    JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
    JSON_KEY_QUANTITY,
    JSON_KEY_SUGGESTED_QUANTITY,
    JSON_KEY_TOTAL,
    JSON_KEY_TOTAL_COST,
    JSON_KEY_UNIT,
    JSON_KEY_UNIT_COST,
    JSON_KEY_WORKS,
)
from app.excel_parser.get_items_dict import get_items_dict


class TestGetItemsDictBehavior:
    """Тесты основного поведения функции get_items_dict."""

    def test_returns_dict_for_any_input(self):
        """
        ПОВЕДЕНИЕ: Функция всегда должна возвращать словарь,
        независимо от входного значения colspan.
        """
        test_cases = [8, 9, 10, 11, 12, 0, -1, 100, 999]

        for colspan in test_cases:
            result = get_items_dict(colspan)
            assert isinstance(result, dict), f"Для colspan={colspan} должен возвращаться dict"

    def test_always_includes_common_fields(self):
        """
        ПОВЕДЕНИЕ: Функция должна всегда включать общие поля
        в возвращаемый словарь, независимо от colspan.
        """
        common_fields = [
            JSON_KEY_NUMBER,
            JSON_KEY_CHAPTER_NUMBER,
            JSON_KEY_ARTICLE_SMR,
            JSON_KEY_JOB_TITLE,
            JSON_KEY_COMMENT_ORGANIZER,
            JSON_KEY_UNIT,
            JSON_KEY_QUANTITY,
        ]

        test_cases = [8, 9, 10, 11, 12, -1, 999]  # Включая невалидные значения

        for colspan in test_cases:
            result = get_items_dict(colspan)

            for field in common_fields:
                assert field in result, f"Поле {field} должно присутствовать для colspan={colspan}"

    def test_common_fields_default_to_none(self):
        """
        ПОВЕДЕНИЕ: Все общие поля должны по умолчанию иметь значение None.
        """
        common_fields = [
            JSON_KEY_NUMBER,
            JSON_KEY_CHAPTER_NUMBER,
            JSON_KEY_ARTICLE_SMR,
            JSON_KEY_JOB_TITLE,
            JSON_KEY_COMMENT_ORGANIZER,
            JSON_KEY_UNIT,
            JSON_KEY_QUANTITY,
        ]

        result = get_items_dict(8)  # Используем минимальный валидный colspan

        for field in common_fields:
            assert result[field] is None, f"Поле {field} должно иметь значение None по умолчанию"


class TestGetItemsDictValidColspan:
    """Тесты для поддерживаемых значений contractor_colspan (8, 9, 10, 11, 12)."""

    def test_colspan_8_structure(self):
        """
        ПОВЕДЕНИЕ: При colspan=8 должны присутствовать только
        общие поля + unit_cost + total_cost.
        """
        result = get_items_dict(8)

        # Проверяем наличие обязательных полей для colspan=8
        assert JSON_KEY_UNIT_COST in result
        assert JSON_KEY_TOTAL_COST in result

        # Проверяем, что это вложенные словари с правильной структурой
        assert isinstance(result[JSON_KEY_UNIT_COST], dict)
        assert isinstance(result[JSON_KEY_TOTAL_COST], dict)

        # Поля, которые НЕ должны присутствовать при colspan=8
        absent_fields = [
            JSON_KEY_SUGGESTED_QUANTITY,
            JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
            JSON_KEY_COMMENT_CONTRACTOR,
            JSON_KEY_DEVIATION_FROM_CALCULATED_COST,
        ]

        for field in absent_fields:
            assert field not in result, f"Поле {field} не должно присутствовать при colspan=8"

    def test_colspan_9_structure(self):
        """
        ПОВЕДЕНИЕ: При colspan=9 добавляется поле deviation_from_calculated_cost.
        """
        result = get_items_dict(9)

        # Все поля из colspan=8 должны присутствовать
        assert JSON_KEY_UNIT_COST in result
        assert JSON_KEY_TOTAL_COST in result

        # Плюс дополнительное поле для colspan=9
        assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST in result
        assert result[JSON_KEY_DEVIATION_FROM_CALCULATED_COST] is None

        # Поля, которые НЕ должны присутствовать при colspan=9
        absent_fields = [
            JSON_KEY_SUGGESTED_QUANTITY,
            JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
            JSON_KEY_COMMENT_CONTRACTOR,
        ]

        for field in absent_fields:
            assert field not in result, f"Поле {field} не должно присутствовать при colspan=9"

    def test_colspan_10_structure(self):
        """
        ПОВЕДЕНИЕ: При colspan=10 добавляется поле comment_contractor.
        """
        result = get_items_dict(10)

        # Все поля из colspan=9 должны присутствовать
        assert JSON_KEY_UNIT_COST in result
        assert JSON_KEY_TOTAL_COST in result
        assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST in result

        # Плюс дополнительное поле для colspan=10
        assert JSON_KEY_COMMENT_CONTRACTOR in result
        assert result[JSON_KEY_COMMENT_CONTRACTOR] is None

        # Поля, которые НЕ должны присутствовать при colspan=10
        absent_fields = [
            JSON_KEY_SUGGESTED_QUANTITY,
            JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
        ]

        for field in absent_fields:
            assert field not in result, f"Поле {field} не должно присутствовать при colspan=10"

    def test_colspan_11_structure(self):
        """
        ПОВЕДЕНИЕ: При colspan=11 добавляются поля suggested_quantity
        и organizer_quantity_total_cost.
        """
        result = get_items_dict(11)

        # Все поля из colspan=10 должны присутствовать
        assert JSON_KEY_UNIT_COST in result
        assert JSON_KEY_TOTAL_COST in result
        assert JSON_KEY_DEVIATION_FROM_CALCULATED_COST in result
        assert JSON_KEY_COMMENT_CONTRACTOR in result

        # Плюс дополнительные поля для colspan=11
        assert JSON_KEY_SUGGESTED_QUANTITY in result
        assert JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST in result

        assert result[JSON_KEY_SUGGESTED_QUANTITY] is None
        assert result[JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST] is None

    def test_colspan_12_structure(self):
        """
        ПОВЕДЕНИЕ: При colspan=12 присутствуют все возможные поля
        (максимальная структура).
        """
        result = get_items_dict(12)

        # Все поля должны присутствовать
        expected_fields = [
            # Общие поля
            JSON_KEY_NUMBER,
            JSON_KEY_CHAPTER_NUMBER,
            JSON_KEY_ARTICLE_SMR,
            JSON_KEY_JOB_TITLE,
            JSON_KEY_COMMENT_ORGANIZER,
            JSON_KEY_UNIT,
            JSON_KEY_QUANTITY,
            # Поля подрядчика (все)
            JSON_KEY_SUGGESTED_QUANTITY,
            JSON_KEY_UNIT_COST,
            JSON_KEY_TOTAL_COST,
            JSON_KEY_ORGANIZER_QUANTITY_TOTAL_COST,
            JSON_KEY_COMMENT_CONTRACTOR,
            JSON_KEY_DEVIATION_FROM_CALCULATED_COST,
        ]

        for field in expected_fields:
            assert field in result, f"Поле {field} должно присутствовать при colspan=12"

        # Проверяем значения по умолчанию
        for field in expected_fields:
            if field not in [JSON_KEY_UNIT_COST, JSON_KEY_TOTAL_COST]:
                assert result[field] is None, f"Поле {field} должно иметь значение None"


class TestGetItemsDictCostBlocks:
    """Тесты для структуры вложенных блоков стоимости."""

    def test_cost_blocks_are_independent_copies(self):
        """
        ПОВЕДЕНИЕ: unit_cost и total_cost должны быть независимыми
        копиями, а не ссылками на один объект.
        """
        result = get_items_dict(8)

        unit_cost = result[JSON_KEY_UNIT_COST]
        total_cost = result[JSON_KEY_TOTAL_COST]

        # Это должны быть разные объекты
        assert unit_cost is not total_cost, "unit_cost и total_cost не должны быть одним объектом"

        # Но с одинаковой структурой
        assert unit_cost == total_cost, "unit_cost и total_cost должны иметь одинаковую структуру"

        # Модификация одного не должна влиять на другой
        unit_cost[JSON_KEY_MATERIALS] = "test_value"
        assert total_cost[JSON_KEY_MATERIALS] is None, "Изменение unit_cost не должно влиять на total_cost"

    def test_cost_block_structure(self):
        """
        ПОВЕДЕНИЕ: Блоки стоимости должны содержать правильные поля
        со значениями None по умолчанию.
        """
        result = get_items_dict(8)

        expected_cost_fields = [
            JSON_KEY_MATERIALS,
            JSON_KEY_WORKS,
            JSON_KEY_INDIRECT_COSTS,
            JSON_KEY_TOTAL,
        ]

        for cost_block_key in [JSON_KEY_UNIT_COST, JSON_KEY_TOTAL_COST]:
            cost_block = result[cost_block_key]

            # Проверяем наличие всех полей
            for field in expected_cost_fields:
                assert field in cost_block, f"Поле {field} должно присутствовать в {cost_block_key}"
                assert cost_block[field] is None, f"Поле {field} в {cost_block_key} должно иметь значение None"

            # Проверяем, что нет лишних полей
            assert len(cost_block) == len(
                expected_cost_fields
            ), f"В {cost_block_key} должно быть ровно {len(expected_cost_fields)} полей"

    def test_cost_blocks_present_in_all_valid_colspan(self):
        """
        ПОВЕДЕНИЕ: Блоки стоимости должны присутствовать
        во всех поддерживаемых значениях colspan.
        """
        valid_colspans = [8, 9, 10, 11, 12]

        for colspan in valid_colspans:
            result = get_items_dict(colspan)

            assert JSON_KEY_UNIT_COST in result, f"unit_cost должен присутствовать при colspan={colspan}"
            assert JSON_KEY_TOTAL_COST in result, f"total_cost должен присутствовать при colspan={colspan}"

            assert isinstance(result[JSON_KEY_UNIT_COST], dict), f"unit_cost должен быть dict при colspan={colspan}"
            assert isinstance(result[JSON_KEY_TOTAL_COST], dict), f"total_cost должен быть dict при colspan={colspan}"


class TestGetItemsDictInvalidColspan:
    """Тесты для обработки неподдерживаемых значений contractor_colspan."""

    def test_invalid_colspan_adds_error_field(self):
        """
        ПОВЕДЕНИЕ: При неподдерживаемом colspan должно добавляться поле "error"
        с описанием проблемы.
        """
        invalid_colspans = [0, -1, 7, 13, 100, 999]

        for colspan in invalid_colspans:
            result = get_items_dict(colspan)

            assert "error" in result, f"Поле 'error' должно присутствовать при colspan={colspan}"
            assert isinstance(result["error"], str), f"Поле 'error' должно быть строкой при colspan={colspan}"
            assert str(colspan) in result["error"], f"Сообщение об ошибке должно содержать значение colspan={colspan}"

    def test_invalid_colspan_still_includes_common_fields(self):
        """
        ПОВЕДЕНИЕ: При неподдерживаемом colspan общие поля всё равно
        должны присутствовать в результате.
        """
        result = get_items_dict(999)  # Явно неподдерживаемое значение

        common_fields = [
            JSON_KEY_NUMBER,
            JSON_KEY_CHAPTER_NUMBER,
            JSON_KEY_ARTICLE_SMR,
            JSON_KEY_JOB_TITLE,
            JSON_KEY_COMMENT_ORGANIZER,
            JSON_KEY_UNIT,
            JSON_KEY_QUANTITY,
        ]

        for field in common_fields:
            assert field in result, f"Общее поле {field} должно присутствовать даже при неподдерживаемом colspan"
            assert result[field] is None, f"Общее поле {field} должно иметь значение None"

    def test_error_message_format(self):
        """
        ПОВЕДЕНИЕ: Сообщение об ошибке должно иметь ожидаемый формат.
        """
        result = get_items_dict(999)

        error_message = result["error"]
        expected_message = "Unknown contractor_colspan: 999"

        assert error_message == expected_message, f"Сообщение об ошибке должно быть: '{expected_message}'"


class TestGetItemsDictEdgeCases:
    """Тесты граничных случаев и особых значений."""

    def test_zero_colspan(self):
        """
        ПОВЕДЕНИЕ: colspan=0 должен обрабатываться как неподдерживаемый.
        """
        result = get_items_dict(0)

        assert "error" in result
        assert "Unknown contractor_colspan: 0" in result["error"]

    def test_negative_colspan(self):
        """
        ПОВЕДЕНИЕ: Отрицательные значения colspan должны обрабатываться корректно.
        """
        result = get_items_dict(-5)

        assert "error" in result
        assert "Unknown contractor_colspan: -5" in result["error"]

    def test_boundary_values(self):
        """
        ПОВЕДЕНИЕ: Проверяем граничные значения около поддерживаемых colspan.
        """
        # Значения рядом с поддерживаемыми
        boundary_cases = [
            (7, "error"),  # Меньше минимального
            (8, "valid"),  # Минимальный поддерживаемый
            (12, "valid"),  # Максимальный поддерживаемый
            (13, "error"),  # Больше максимального
        ]

        for colspan, expected_type in boundary_cases:
            result = get_items_dict(colspan)

            if expected_type == "error":
                assert "error" in result, f"Для colspan={colspan} должна быть ошибка"
            else:
                assert "error" not in result, f"Для colspan={colspan} не должно быть ошибки"
                # Проверяем, что есть cost blocks для валидных значений
                assert JSON_KEY_UNIT_COST in result
                assert JSON_KEY_TOTAL_COST in result


class TestGetItemsDictDataIntegrity:
    """Тесты целостности и качества возвращаемых данных."""

    def test_no_shared_mutable_objects(self):
        """
        ПОВЕДЕНИЕ: Функция не должна возвращать разделяемые изменяемые объекты.
        Каждый вызов должен возвращать независимые структуры данных.
        """
        result1 = get_items_dict(12)
        result2 = get_items_dict(12)

        # Это должны быть разные объекты
        assert result1 is not result2

        # Но с одинаковой структурой
        assert result1 == result2

        # Изменение одного не должно влиять на другой
        result1[JSON_KEY_NUMBER] = "test"
        assert result2[JSON_KEY_NUMBER] is None

        # То же самое для вложенных объектов
        result1[JSON_KEY_UNIT_COST][JSON_KEY_MATERIALS] = "test"
        assert result2[JSON_KEY_UNIT_COST][JSON_KEY_MATERIALS] is None

    def test_consistent_field_count_for_same_colspan(self):
        """
        ПОВЕДЕНИЕ: Для одного и того же colspan функция должна
        всегда возвращать одинаковое количество полей.
        """
        colspan_values = [8, 9, 10, 11, 12]

        for colspan in colspan_values:
            results = [get_items_dict(colspan) for _ in range(5)]

            # Все результаты должны иметь одинаковое количество ключей
            field_counts = [len(result) for result in results]
            assert all(
                count == field_counts[0] for count in field_counts
            ), f"Все вызовы для colspan={colspan} должны возвращать одинаковое количество полей"

    def test_field_progression_across_colspan_values(self):
        """
        ПОВЕДЕНИЕ: При увеличении colspan количество полей должно
        увеличиваться или оставаться тем же (никогда не уменьшаться).
        """
        colspan_values = [8, 9, 10, 11, 12]
        field_counts = []

        for colspan in colspan_values:
            result = get_items_dict(colspan)
            field_counts.append(len(result))

        # Проверяем, что количество полей не уменьшается
        for i in range(1, len(field_counts)):
            assert (
                field_counts[i] >= field_counts[i - 1]
            ), f"Количество полей для colspan={colspan_values[i]} не должно быть меньше чем для colspan={colspan_values[i-1]}"
