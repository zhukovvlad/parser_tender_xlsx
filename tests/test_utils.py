"""
Тесты для модуля utils.py.

Тестирует утилиты общего назначения:
- Валидация данных
- Работа с файлами
- Форматирование данных
"""

import pytest
import tempfile
import hashlib
from pathlib import Path
from unittest.mock import patch, mock_open

from utils import (
    validate_email, validate_phone, validate_inn,
    sanitize_filename, generate_file_hash, format_file_size,
    clean_text, normalize_currency, is_valid_coordinate,
    generate_temporary_id, truncate_text, get_file_extension,
    is_empty_value, ValidationError, FileProcessingError
)


class TestValidation:
    """Тесты для функций валидации."""
    
    def test_validate_email_valid(self):
        """Тест валидации корректных email адресов."""
        valid_emails = [
            "test@example.com",
            "user.name@domain.org",
            "user+tag@example.co.uk",
            "123@numbers.com"
        ]
        
        for email in valid_emails:
            assert validate_email(email) is True
    
    def test_validate_email_invalid(self):
        """Тест валидации некорректных email адресов."""
        invalid_emails = [
            "invalid-email",
            "@example.com",
            "test@",
            "test.example.com",
            ""
        ]
        
        for email in invalid_emails:
            assert validate_email(email) is False
    
    def test_validate_phone_valid(self):
        """Тест валидации корректных номеров телефонов."""
        valid_phones = [
            "+7 (123) 456-78-90",
            "1234567890",
            "+1-234-567-8900",
            "123 456 7890"
        ]
        
        for phone in valid_phones:
            assert validate_phone(phone) is True
    
    def test_validate_phone_invalid(self):
        """Тест валидации некорректных номеров телефонов."""
        invalid_phones = [
            "123",
            "abc-def-ghij",
            "",
            "123456789012345678901234567890"  # Слишком длинный
        ]
        
        for phone in invalid_phones:
            assert validate_phone(phone) is False
    
    def test_validate_inn_valid(self):
        """Тест валидации корректных ИНН."""
        valid_inns = [
            "1234567890",      # 10 цифр
            "123456789012"     # 12 цифр
        ]
        
        for inn in valid_inns:
            assert validate_inn(inn) is True
    
    def test_validate_inn_invalid(self):
        """Тест валидации некорректных ИНН."""
        invalid_inns = [
            "123456789",       # 9 цифр
            "12345678901",     # 11 цифр
            "1234567890123",   # 13 цифр
            "123456789a",      # Содержит букву
            ""
        ]
        
        for inn in invalid_inns:
            assert validate_inn(inn) is False


class TestFileUtils:
    """Тесты для утилит работы с файлами."""
    
    def test_sanitize_filename(self):
        """Тест очистки имени файла."""
        test_cases = [
            ("file<name>.txt", "file_name_.txt"),
            ("file|name.txt", "file_name.txt"),
            ("normal_file.txt", "normal_file.txt"),
            ("file with spaces.txt", "file with spaces.txt")
        ]
        
        for input_name, expected in test_cases:
            result = sanitize_filename(input_name)
            assert result == expected
    
    def test_sanitize_filename_long(self):
        """Тест очистки длинного имени файла."""
        long_name = "a" * 250 + ".txt"
        result = sanitize_filename(long_name)
        assert len(result) <= 200
        assert result.endswith(".txt")
    
    def test_generate_file_hash(self):
        """Тест генерации хеша файла."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as tmp:
            tmp.write("test content")
            tmp_path = tmp.name
        
        try:
            hash_result = generate_file_hash(tmp_path)
            
            # Проверяем что хеш генерируется
            assert isinstance(hash_result, str)
            assert len(hash_result) == 32  # MD5 hash length
            
            # Проверяем что одинаковые файлы дают одинаковые хеши
            hash_result2 = generate_file_hash(tmp_path)
            assert hash_result == hash_result2
            
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    
    def test_generate_file_hash_missing_file(self):
        """Тест генерации хеша несуществующего файла."""
        with pytest.raises(FileProcessingError):
            generate_file_hash("/nonexistent/file.txt")
    
    def test_format_file_size(self):
        """Тест форматирования размера файла."""
        test_cases = [
            (0, "0.0 B"),
            (1023, "1023.0 B"),
            (1024, "1.0 KB"),
            (1024 * 1024, "1.0 MB"),
            (1024 * 1024 * 1024, "1.0 GB"),
        ]
        
        for size, expected in test_cases:
            result = format_file_size(size)
            assert result == expected
    
    def test_get_file_extension(self):
        """Тест получения расширения файла."""
        test_cases = [
            ("file.txt", ".txt"),
            ("file.TAR.GZ", ".gz"),
            ("file", ""),
            ("file.PDF", ".pdf"),
            ("file.XLSX", ".xlsx")
        ]
        
        for filename, expected in test_cases:
            result = get_file_extension(filename)
            assert result == expected


class TestTextUtils:
    """Тесты для утилит работы с текстом."""
    
    def test_clean_text(self):
        """Тест очистки текста."""
        test_cases = [
            ("  hello   world  ", "hello world"),
            ("text\n\nwith\t\ttabs", "text with tabs"),
            ("", ""),
            (None, ""),
            ("normal text", "normal text")
        ]
        
        for input_text, expected in test_cases:
            result = clean_text(input_text)
            assert result == expected
    
    def test_normalize_currency(self):
        """Тест нормализации денежных сумм."""
        test_cases = [
            ("1000", 1000.0),
            ("1,000.50", 1000.5),
            ("1 000,50", 1000.5),
            ("1.000,50", 1000.5),
            ("$1,000.50", 1000.5),
            ("", None),
            (None, None),
            ("abc", None),
            (1000, 1000.0),
            (1000.5, 1000.5)
        ]
        
        for input_value, expected in test_cases:
            result = normalize_currency(input_value)
            assert result == expected
    
    def test_is_valid_coordinate(self):
        """Тест валидации Excel координат."""
        valid_coords = ["A1", "B2", "AA10", "XFD1048576"]
        invalid_coords = ["1A", "A", "1", "", "A1B", "a1"]
        
        for coord in valid_coords:
            assert is_valid_coordinate(coord) is True
        
        for coord in invalid_coords:
            assert is_valid_coordinate(coord) is False
    
    def test_truncate_text(self):
        """Тест обрезки текста."""
        test_cases = [
            ("short text", 20, "short text"),
            ("very long text that should be truncated", 10, "very lo..."),
            ("exact length", 12, "exact length"),
            ("", 10, "")
        ]
        
        for text, max_length, expected in test_cases:
            result = truncate_text(text, max_length)
            assert result == expected
            assert len(result) <= max_length
    
    def test_is_empty_value(self):
        """Тест проверки пустых значений."""
        empty_values = [None, "", "   ", [], {}, ()]
        non_empty_values = [0, "text", [1], {"key": "value"}, (1,)]
        
        for value in empty_values:
            assert is_empty_value(value) is True
        
        for value in non_empty_values:
            assert is_empty_value(value) is False


class TestUtilityFunctions:
    """Тесты для вспомогательных функций."""
    
    def test_generate_temporary_id(self):
        """Тест генерации временного ID."""
        id1 = generate_temporary_id()
        id2 = generate_temporary_id()
        
        # Проверяем что ID разные
        assert id1 != id2
        
        # Проверяем формат ID
        assert id1.startswith("temp_")
        assert id2.startswith("temp_")
        
        # Проверяем что ID содержит временную метку и хеш
        parts = id1.split("_")
        assert len(parts) == 3
        assert parts[0] == "temp"
        assert parts[1].isdigit()  # timestamp
        assert len(parts[2]) == 8  # hash part