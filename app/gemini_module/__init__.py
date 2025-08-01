# gemini_module/__init__.py

# Делаем основные классы и конфигурации доступными прямо из пакета
from .processor import TenderProcessor
from .config import (
    DEFAULT_MODEL,
    SUPPORTED_EXTENSIONS, 
    MAX_FILE_SIZE_MB,
    MESSAGES,
    validate_input_file,
    get_message
)

__all__ = [
    "TenderProcessor",
    "DEFAULT_MODEL", 
    "SUPPORTED_EXTENSIONS",
    "MAX_FILE_SIZE_MB", 
    "MESSAGES",
    "validate_input_file",
    "get_message"
]
