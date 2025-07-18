"""
Модуль для настройки логирования в парсере тендерных документов.

Предоставляет централизованную настройку логирования с поддержкой:
- Записи в файл с ротацией
- Вывода в консоль
- Различных уровней логирования
- Структурированного формата
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional

from config import get_logging_config


class ColoredFormatter(logging.Formatter):
    """Форматтер с цветной подсветкой для консоли."""
    
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        log_color = self.COLORS.get(record.levelname, '')
        record.levelname = f"{log_color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    name: Optional[str] = None,
    level: Optional[str] = None,
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """
    Настраивает логирование для приложения.
    
    Args:
        name: Имя логгера (по умолчанию root)
        level: Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_to_file: Логировать в файл
        log_to_console: Логировать в консоль
        
    Returns:
        logging.Logger: Настроенный логгер
    """
    config = get_logging_config()
    
    # Создаем логгер
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level or config.level))
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Настраиваем формат
    file_formatter = logging.Formatter(config.format)
    console_formatter = ColoredFormatter(config.format)
    
    # Обработчик для файла
    if log_to_file and config.file_path:
        file_handler = logging.handlers.RotatingFileHandler(
            config.file_path,
            maxBytes=config.max_size,
            backupCount=config.backup_count,
            encoding='utf-8'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
    
    # Обработчик для консоли
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # Предотвращаем дублирование логов
    logger.propagate = False
    
    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Возвращает логгер для указанного модуля.
    
    Args:
        name: Имя модуля
        
    Returns:
        logging.Logger: Логгер
    """
    return logging.getLogger(name)


def log_function_call(func):
    """
    Декоратор для логирования вызовов функций.
    
    Args:
        func: Функция для логирования
        
    Returns:
        Обернутая функция
    """
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        logger.debug(f"Вызов функции {func.__name__} с аргументами: args={args}, kwargs={kwargs}")
        
        try:
            result = func(*args, **kwargs)
            logger.debug(f"Функция {func.__name__} успешно выполнена")
            return result
        except Exception as e:
            logger.error(f"Ошибка в функции {func.__name__}: {e}", exc_info=True)
            raise
    
    return wrapper


def log_method_calls(cls):
    """
    Декоратор класса для логирования вызовов методов.
    
    Args:
        cls: Класс для логирования
        
    Returns:
        Обернутый класс
    """
    for attr_name in dir(cls):
        attr = getattr(cls, attr_name)
        if callable(attr) and not attr_name.startswith('_'):
            setattr(cls, attr_name, log_function_call(attr))
    
    return cls


class LoggingContext:
    """Контекстный менеджер для временного изменения уровня логирования."""
    
    def __init__(self, logger: logging.Logger, level: str):
        self.logger = logger
        self.new_level = getattr(logging, level.upper())
        self.old_level = logger.level
    
    def __enter__(self):
        self.logger.setLevel(self.new_level)
        return self.logger
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.setLevel(self.old_level)


def configure_third_party_loggers():
    """Настраивает логирование для сторонних библиотек."""
    # Уменьшаем уровень логирования для шумных библиотек
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    logging.getLogger('sqlalchemy').setLevel(logging.WARNING)
    logging.getLogger('transformers').setLevel(logging.WARNING)
    logging.getLogger('sentence_transformers').setLevel(logging.WARNING)


def setup_application_logging():
    """Настраивает логирование для всего приложения."""
    # Настраиваем основной логгер
    main_logger = setup_logging('parser_tender_xlsx', 'INFO')
    
    # Настраиваем логгеры для модулей
    setup_logging('app.parse', 'INFO')
    setup_logging('app.helpers', 'INFO')
    setup_logging('app.llm', 'INFO')
    setup_logging('tools', 'INFO')
    
    # Настраиваем сторонние библиотеки
    configure_third_party_loggers()
    
    main_logger.info("Логирование настроено")
    return main_logger


# Настраиваем логирование при импорте модуля
if __name__ != "__main__":
    setup_application_logging()