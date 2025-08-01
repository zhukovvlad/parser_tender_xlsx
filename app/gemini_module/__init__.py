# gemini_module/__init__.py

# Делаем основные классы и конфигурации доступными прямо из пакета
from .processor import TenderProcessor
from .config import DEFAULT_MODEL, SUPPORTED_EXTENSIONS, MAX_FILE_SIZE_MB, MESSAGES, validate_input_file, get_message
from .logger import setup_gemini_logger, get_gemini_logger

__all__ = [
    "TenderProcessor",
    "DEFAULT_MODEL",
    "SUPPORTED_EXTENSIONS",
    "MAX_FILE_SIZE_MB",
    "MESSAGES",
    "validate_input_file",
    "get_message",
    "setup_gemini_logger",
    "get_gemini_logger",
]
