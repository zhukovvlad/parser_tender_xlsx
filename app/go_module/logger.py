# app/go_module/logger.py
"""
Конфигурация логгирования для go_module.

Этот модуль настраивает отдельный логгер для операций с Go API бэкендом,
позволяя отслеживать HTTP запросы, ответы и ошибки отдельно
от основного приложения.

Интегрируется с общей системой логгирования проекта, используя те же
настройки уровня логгирования и формата.
"""

import logging
import os
from pathlib import Path
from typing import Optional


def setup_go_logger(
    name: str = "go_module",
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    include_console: bool = True,
) -> logging.Logger:
    """
    Настраивает логгер для go_module.

    Интегрируется с общей системой логгирования проекта, используя
    те же переменные окружения (LOG_LEVEL) и формат логов.

    Args:
        name: Имя логгера
        log_level: Уровень логгирования (DEBUG, INFO, WARNING, ERROR).
                  Если не указан, берется из LOG_LEVEL или GO_LOG_LEVEL
        log_file: Путь к файлу логов (по умолчанию logs/go_module.log)
        include_console: Включать ли вывод в консоль

    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(name)

    # Избегаем повторной настройки
    if logger.handlers:
        return logger

    # Определяем уровень логгирования (приоритет: параметр > GO_LOG_LEVEL > LOG_LEVEL > INFO)
    if log_level is None:
        log_level = os.getenv("GO_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))

    log_levels = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }

    level = log_levels.get(log_level.upper(), logging.INFO)
    logger.setLevel(level)

    # Используем тот же формат, что и в основном приложении
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Файловый хендлер
    if log_file is None:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / "go_module.log"

    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Консольный хендлер (опционально)
    if include_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def get_go_logger() -> logging.Logger:
    """
    Возвращает настроенный логгер для go_module.
    Если логгер еще не настроен, настраивает его с параметрами по умолчанию.

    Returns:
        Логгер для go_module
    """
    logger = logging.getLogger("go_module")
    if not logger.handlers:
        logger = setup_go_logger()
    return logger
