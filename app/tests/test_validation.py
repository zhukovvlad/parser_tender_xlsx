"""
Тесты для модуля валидации файлов.
"""

import pytest
from fastapi import HTTPException, UploadFile
from io import BytesIO
from unittest.mock import Mock

from app.validation import (
    FileValidationError,
    validate_file_extension,
    validate_file_size,
    validate_mime_type,
    sanitize_filename,
    validate_upload_file,
)


class TestFileExtensionValidation:
    """Тесты валидации расширений файлов."""

    def test_valid_extension(self):
        """Тест валидного расширения."""
        assert validate_file_extension("test.xlsx", [".xlsx", ".xls"]) is True

    def test_case_insensitive_extension(self):
        """Тест нечувствительности к регистру."""
        assert validate_file_extension("test.XLSX", [".xlsx", ".xls"]) is True

    def test_invalid_extension(self):
        """Тест невалидного расширения."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_file_extension("test.pdf", [".xlsx", ".xls"])
        assert "not allowed" in str(exc_info.value)

    def test_empty_filename(self):
        """Тест пустого имени файла."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_file_extension("", [".xlsx"])
        assert "cannot be empty" in str(exc_info.value)

    def test_no_extension(self):
        """Тест файла без расширения."""
        with pytest.raises(FileValidationError):
            validate_file_extension("test", [".xlsx"])


class TestFileSizeValidation:
    """Тесты валидации размера файлов."""

    def test_valid_size(self):
        """Тест валидного размера."""
        assert validate_file_size(1024, 2048) is True

    def test_exact_max_size(self):
        """Тест точного максимального размера."""
        assert validate_file_size(1024, 1024) is True

    def test_oversized_file(self):
        """Тест превышения размера."""
        with pytest.raises(FileValidationError) as exc_info:
            validate_file_size(2048, 1024)
        assert "exceeds maximum" in str(exc_info.value)


class TestMimeTypeValidation:
    """Тесты валидации MIME типов."""

    def test_valid_xlsx_mime_type(self):
        """Тест валидного MIME типа для XLSX."""
        mock_file = Mock(spec=UploadFile)
        mock_file.content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        mock_file.filename = "test.xlsx"
        
        assert validate_mime_type(mock_file) is True

    def test_valid_xls_mime_type(self):
        """Тест валидного MIME типа для XLS."""
        mock_file = Mock(spec=UploadFile)
        mock_file.content_type = "application/vnd.ms-excel"
        mock_file.filename = "test.xls"
        
        assert validate_mime_type(mock_file) is True

    def test_invalid_mime_type_valid_extension(self):
        """Тест невалидного MIME типа с валидным расширением."""
        mock_file = Mock(spec=UploadFile)
        mock_file.content_type = "text/plain"
        mock_file.filename = "test.xlsx"
        
        # Должно пройти благодаря угадыванию по расширению
        assert validate_mime_type(mock_file) is True

    def test_invalid_mime_type_invalid_extension(self):
        """Тест невалидного MIME типа с невалидным расширением."""
        mock_file = Mock(spec=UploadFile)
        mock_file.content_type = "text/plain"
        mock_file.filename = "test.txt"
        
        with pytest.raises(FileValidationError) as exc_info:
            validate_mime_type(mock_file)
        assert "not allowed" in str(exc_info.value)


class TestFilenameeSanitization:
    """Тесты очистки имен файлов."""

    def test_safe_filename(self):
        """Тест безопасного имени файла."""
        assert sanitize_filename("test.xlsx") == "test.xlsx"

    def test_path_traversal_attack(self):
        """Тест защиты от path traversal."""
        assert sanitize_filename("../../../etc/passwd") == "passwd"
        assert sanitize_filename("..\\..\\windows\\system32") == "_windows_system32"

    def test_dangerous_characters(self):
        """Тест удаления опасных символов."""
        result = sanitize_filename('test<>:"/\\|?*.xlsx')
        assert all(char not in result for char in '<>:"/\\|?*')

    def test_empty_filename_after_sanitization(self):
        """Тест пустого имени после очистки."""
        assert sanitize_filename("...") == "unnamed_file"
        assert sanitize_filename("") == "unnamed_file"


class TestUploadFileValidation:
    """Тесты комплексной валидации загружаемых файлов."""

    @pytest.fixture
    def mock_upload_file(self):
        """Фикстура для мок UploadFile."""
        content = b"test file content"
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = "test.xlsx"
        mock_file.content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        
        # Создаем async функцию для read
        async def async_read():
            return content
        
        # Создаем async функцию для seek
        async def async_seek(position):
            pass
        
        mock_file.read = async_read
        mock_file.seek = async_seek
        return mock_file

    @pytest.mark.asyncio
    async def test_valid_file_upload(self, mock_upload_file):
        """Тест валидной загрузки файла."""
        result = await validate_upload_file(
            mock_upload_file, 
            max_size=1024 * 1024,  # 1MB
            allowed_extensions=[".xlsx", ".xls"]
        )
        
        assert result["filename"] == "test.xlsx"
        assert result["size"] == len(b"test file content")
        assert "hash" in result
        assert result["content_type"] == mock_upload_file.content_type

    @pytest.mark.asyncio
    async def test_no_filename(self):
        """Тест файла без имени."""
        mock_file = Mock(spec=UploadFile)
        mock_file.filename = None
        
        with pytest.raises(HTTPException) as exc_info:
            await validate_upload_file(mock_file, 1024, [".xlsx"])
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_oversized_file(self, mock_upload_file):
        """Тест превышения размера файла."""
        # Создаем новый мок с большим контентом
        large_content = b"x" * 2000
        
        async def async_read_large():
            return large_content
        
        mock_upload_file.read = async_read_large
        
        with pytest.raises(HTTPException) as exc_info:
            await validate_upload_file(mock_upload_file, 1000, [".xlsx"])
        assert exc_info.value.status_code == 400
        assert "exceeds maximum" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_file_processing_error(self, mock_upload_file):
        """Тест ошибки при обработке файла."""
        async def async_read_error():
            raise Exception("File read error")
        
        mock_upload_file.read = async_read_error
        
        with pytest.raises(HTTPException) as exc_info:
            await validate_upload_file(mock_upload_file, 1024, [".xlsx"])
        assert exc_info.value.status_code == 500