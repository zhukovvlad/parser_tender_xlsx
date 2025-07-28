"""
Пользовательские исключения для приложения парсера тендеров.

Модуль определяет специализированные исключения для различных
сценариев ошибок в процессе обработки тендерных документов.
"""


class TenderParsingError(Exception):
    """Базовое исключение для ошибок парсинга тендеров."""

    def __init__(self, message: str, file_path: str = None):
        super().__init__(message)
        self.file_path = file_path


class XLSXFileError(TenderParsingError):
    """Исключение для ошибок работы с XLSX файлами."""

    pass


class ServerRegistrationError(TenderParsingError):
    """Исключение для ошибок регистрации тендера на сервере."""

    def __init__(self, message: str, status_code: int = None, file_path: str = None):
        super().__init__(message, file_path)
        self.status_code = status_code


class ConfigurationError(Exception):
    """Исключение для ошибок конфигурации приложения."""

    pass


class ArtifactGenerationError(TenderParsingError):
    """Исключение для ошибок генерации артефактов."""

    pass