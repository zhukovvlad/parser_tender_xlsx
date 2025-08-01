"""
Тесты для модуля sanitize_text.

Этот модуль содержит тесты для функций очистки и нормализации текста:
- sanitize_text: базовая очистка текста
- sanitize_object_and_address_text: специфическая очистка для объектов и адресов  
- normalize_job_title_with_lemmatization: продвинутая нормализация с лемматизацией
"""

import pytest
from unittest.mock import patch, MagicMock
from app.excel_parser.sanitize_text import (
    sanitize_text,
    sanitize_object_and_address_text,
    normalize_job_title_with_lemmatization,
    SPACY_AVAILABLE,
    NLP_SPACY
)


class TestSanitizeText:
    """Тесты для функции sanitize_text."""

    def test_sanitize_text_with_string(self):
        """Тест очистки строки с символами новой строки и пробелами."""
        text = "  Пример\nтекста\r\n с пробелами  "
        result = sanitize_text(text)
        # После замены \n на пробел и удаления \r получаем два пробела между словами
        expected = "Пример текста  с пробелами"
        assert result == expected

    def test_sanitize_text_with_quotes(self):
        """Тест, что кавычки сохраняются."""
        text = 'Текст с "кавычками"'
        result = sanitize_text(text)
        expected = 'Текст с "кавычками"'
        assert result == expected

    def test_sanitize_text_with_none(self):
        """Тест, что None возвращается без изменений."""
        result = sanitize_text(None)
        assert result is None

    def test_sanitize_text_with_number(self):
        """Тест, что числа возвращаются без изменений."""  
        result = sanitize_text(123)
        assert result == 123

    def test_sanitize_text_with_empty_string(self):
        """Тест очистки пустой строки."""
        result = sanitize_text("   ")
        assert result == ""

    def test_sanitize_text_with_only_newlines(self):
        """Тест очистки строки только с символами новой строки."""
        result = sanitize_text("\n\r\n")
        # \n заменяется на пробел, \r удаляется, затем strip() убирает пробелы
        assert result == ""

    def test_sanitize_text_with_mixed_whitespace(self):
        """Тест очистки строки со смешанными пробельными символами."""
        text = "\t  Текст\n\r с табами \t\r\n  "
        result = sanitize_text(text)
        expected = "Текст  с табами"
        assert result == expected


class TestSanitizeObjectAndAddressText:
    """Тесты для функции sanitize_object_and_address_text."""

    def test_sanitize_object_and_address_basic(self):
        """Тест базовой очистки адреса с точками и заглавными буквами."""
        text = "Ул. Ленина, д. 5, КОРП. 1А."
        result = sanitize_object_and_address_text(text)
        expected = "ул ленина, д 5, корп 1а"
        assert result == expected

    def test_sanitize_object_and_address_with_quotes(self):
        """Тест, что кавычки сохраняются при очистке объекта."""
        text = '  Объект "Капитель" с Большими Буквами.  '
        result = sanitize_object_and_address_text(text)
        expected = 'объект "капитель" с большими буквами'
        assert result == expected

    def test_sanitize_object_and_address_with_none(self):
        """Тест, что None возвращается без изменений."""
        result = sanitize_object_and_address_text(None)
        assert result is None

    def test_sanitize_object_and_address_with_number(self):
        """Тест, что числа возвращаются без изменений."""
        result = sanitize_object_and_address_text(123)
        assert result == 123

    def test_sanitize_object_and_address_multiple_dots(self):
        """Тест удаления множественных точек."""
        text = "А.Б.В.Г...Д."
        result = sanitize_object_and_address_text(text)
        expected = "абвгд"
        assert result == expected

    def test_sanitize_object_and_address_empty_string(self):
        """Тест очистки пустой строки."""
        result = sanitize_object_and_address_text("   ")
        assert result == ""

    def test_sanitize_object_and_address_with_newlines(self):
        """Тест очистки строки с символами новой строки и точками."""
        text = "Объект.\nНа двух\rстроках."
        result = sanitize_object_and_address_text(text)
        # Функция удаляет точки, приводит к нижнему регистру, но НЕ вызывает sanitize_text
        # поэтому \n и \r остаются
        expected = "объект\nна двух\rстроках"
        assert result == expected


class TestNormalizeJobTitleWithLemmatization:
    """Тесты для функции normalize_job_title_with_lemmatization."""

    def test_normalize_job_title_with_none(self):
        """Тест, что None возвращается без изменений."""
        result = normalize_job_title_with_lemmatization(None)
        assert result is None

    def test_normalize_job_title_with_empty_string(self):
        """Тест, что пустая строка возвращает None после очистки."""
        result = normalize_job_title_with_lemmatization("")
        # Пустая строка после очистки становится None
        assert result is None

    def test_normalize_job_title_basic_cleanup(self):
        """Тест базовой очистки без spaCy."""
        with patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', False):
            text = "**Старший** разработчик! (Python)"
            result = normalize_job_title_with_lemmatization(text)
            # Должно убрать пунктуацию и привести к нижнему регистру
            expected = "старший разработчик python"
            assert result == expected

    def test_normalize_job_title_with_numbers(self):
        """Тест очистки должности с числами."""
        with patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', False):
            text = "Менеджер 1С версия 8.3"
            result = normalize_job_title_with_lemmatization(text) 
            # Точка заменяется на пробел в regex [^\w\s-]
            expected = "менеджер 1с версия 8 3"
            assert result == expected

    def test_normalize_job_title_markdown_cleanup(self):
        """Тест удаления Markdown разметки."""
        with patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', False):
            text = "# Заголовок\n**жирный текст** и *курсив*"
            result = normalize_job_title_with_lemmatization(text)
            expected = "заголовок жирный текст и курсив" 
            assert result == expected

    @patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', True)
    def test_normalize_job_title_with_spacy_mock(self):
        """Тест лемматизации с мокированным spaCy."""
        # Создаем мок для spaCy
        mock_doc = MagicMock()
        mock_token1 = MagicMock()
        mock_token1.lemma_ = "разработчик"
        mock_token1.pos_ = "NOUN"
        mock_token1.is_punct = False
        mock_token1.is_space = False
        
        mock_token2 = MagicMock()
        mock_token2.lemma_ = "программа"
        mock_token2.pos_ = "NOUN" 
        mock_token2.is_punct = False
        mock_token2.is_space = False
        
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_token1, mock_token2]))
        
        with patch('app.excel_parser.sanitize_text.NLP_SPACY') as mock_nlp:
            mock_nlp.return_value = mock_doc
            
            text = "разработчики программ"
            result = normalize_job_title_with_lemmatization(text)
            expected = "разработчик программа"
            assert result == expected

    def test_normalize_job_title_special_characters(self):
        """Тест удаления специальных символов."""
        with patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', False):
            text = "Java-разработчик @company #senior $$$"
            result = normalize_job_title_with_lemmatization(text)
            # Дефис сохраняется согласно regex [^\w\s-], остальные символы заменяются на пробелы
            expected = "java-разработчик company senior"
            assert result == expected

    def test_normalize_job_title_whitespace_normalization(self):
        """Тест нормализации пробелов."""
        with patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', False):
            text = "   Senior    Developer   \n\t  "
            result = normalize_job_title_with_lemmatization(text)
            expected = "senior developer"
            assert result == expected

    def test_normalize_job_title_real_spacy_if_available(self):
        """Тест с реальным spaCy, если он доступен."""
        if SPACY_AVAILABLE and NLP_SPACY:
            text = "старшие разработчики"
            result = normalize_job_title_with_lemmatization(text)
            # С реальным spaCy должна произойти лемматизация
            # "старшие" -> "старший", "разработчики" -> "разработчик"
            assert "старший" in result.lower()
            assert "разработчик" in result.lower()
        else:
            # Если spaCy недоступен, пропускаем тест
            pytest.skip("spaCy не доступен для реального тестирования")


class TestSpacyIntegration:
    """Тесты интеграции с spaCy."""

    def test_spacy_availability_flag(self):
        """Тест, что флаг SPACY_AVAILABLE корректно установлен."""
        assert isinstance(SPACY_AVAILABLE, bool)

    def test_spacy_model_loading(self):
        """Тест загрузки модели spaCy."""
        if SPACY_AVAILABLE:
            assert NLP_SPACY is not None
            # Проверяем, что это действительно модель spaCy
            assert hasattr(NLP_SPACY, '__call__')
        else:
            assert NLP_SPACY is None

    @patch('app.excel_parser.sanitize_text.SPACY_AVAILABLE', False)  
    def test_normalize_without_spacy(self):
        """Тест нормализации когда spaCy недоступен."""
        text = "Тестовый текст для проверки"
        result = normalize_job_title_with_lemmatization(text)
        # Должна работать базовая очистка без лемматизации
        assert result == "тестовый текст для проверки"
        assert isinstance(result, str)
