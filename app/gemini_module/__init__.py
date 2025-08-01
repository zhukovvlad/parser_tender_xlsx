# gemini_module/__init__.py

# Делаем основные классы и конфигурации доступными прямо из пакета
from .config import DEFAULT_MODEL, MAX_FILE_SIZE_MB, MESSAGES, SUPPORTED_EXTENSIONS, get_message, validate_input_file
from .logger import get_gemini_logger, setup_gemini_logger
from .processor import TenderProcessor

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
