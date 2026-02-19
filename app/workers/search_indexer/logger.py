# -*- coding: utf-8 -*-
# app/workers/search_indexer/logger.py
"""
Конфигурация логгирования для search_indexer воркера.

Настраивает отдельный JSON-логгер для Search Indexer, позволяя
отслеживать операции эмбеддинга, дедупликации и активации
отдельно от основного приложения.

Структурированный JSON-формат упрощает парсинг логов в production.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional


class _JsonFormatter(logging.Formatter):
    """Формирует каждый log-record как одну JSON-строку."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "ts": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            log_obj["exc"] = self.formatException(record.exc_info)
        # Дополнительные поля, прокидываемые через extra={}
        # Сохраняем все кастомные атрибуты, не только захардкоженный whitelist.
        for key, val in vars(record).items():
            if (
                key not in log_obj
                and key not in _STANDARD_LOG_ATTRS
                and not key.startswith("_")
            ):
                log_obj[key] = val
        return json.dumps(log_obj, ensure_ascii=False)


# Стандартные атрибуты LogRecord, которые не нужно дублировать в JSON.
_STANDARD_LOG_ATTRS = frozenset({
    "name", "msg", "args", "created", "relativeCreated",
    "thread", "threadName", "process", "processName",
    "pathname", "filename", "module", "funcName",
    "levelno", "levelname", "lineno", "msecs",
    "stack_info", "exc_info", "exc_text", "message", "asctime",
    "taskName",
})


def setup_search_indexer_logger(
    name: str = "search_indexer",
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    include_console: bool = True,
) -> logging.Logger:
    """
    Настраивает логгер для search_indexer воркера.

    Интегрируется с общей системой логгирования проекта, используя
    те же переменные окружения (LOG_LEVEL) и формат логов.

    Args:
        name: Имя логгера
        log_level: Уровень логгирования (DEBUG, INFO, WARNING, ERROR).
                  Если не указан, берется из SEARCH_INDEXER_LOG_LEVEL или LOG_LEVEL
        log_file: Путь к файлу логов (по умолчанию logs/search_indexer.log)
        include_console: Включать ли вывод в консоль

    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(name)

    # Избегаем повторной настройки (используем custom-атрибут вместо logger.handlers,
    # чтобы внешне добавленные хендлеры не помешали инициализации JSON-формата)
    if getattr(logger, "_search_indexer_configured", False):
        return logger

    # Определяем уровень логгирования
    # Приоритет: параметр > SEARCH_INDEXER_LOG_LEVEL > LOG_LEVEL > INFO
    if log_level is None:
        log_level = os.getenv(
            "SEARCH_INDEXER_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO")
        )

    # Используем встроенную конвертацию имени уровня (поддерживает
    # DEBUG, INFO, WARNING, ERROR, CRITICAL, FATAL и их числовые значения)
    numeric_level = logging.getLevelName(log_level.upper())
    level = numeric_level if isinstance(numeric_level, int) else logging.INFO
    logger.setLevel(level)

    formatter = _JsonFormatter()

    # Файловый хендлер
    if log_file is None:
        log_dir = Path("logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "search_indexer.log"

    log_file_path = Path(log_file)
    parent_dir = log_file_path.parent
    if str(parent_dir) not in (".", ""):
        parent_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Консольный хендлер
    if include_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    logger.propagate = False
    logger._search_indexer_configured = True
    return logger


def get_search_indexer_logger(name: str = "search_indexer") -> logging.Logger:
    """
    Возвращает настроенный логгер для search_indexer воркера.
    Если логгер еще не настроен, настраивает его с параметрами по умолчанию.

    Args:
        name: Имя логгера (можно использовать для создания подлоггеров)

    Returns:
        Логгер для search_indexer воркера
    """
    logger = logging.getLogger(name)
    if not getattr(logger, "_search_indexer_configured", False):
        logger = setup_search_indexer_logger(name=name)
    return logger
