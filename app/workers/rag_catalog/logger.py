# -*- coding: utf-8 -*-
# app/workers/rag_catalog/logger.py
"""
Конфигурация логгирования для rag_catalog воркера.

Этот модуль настраивает отдельный логгер для RAG Catalog воркера,
позволяя отслеживать операции сопоставления, дедупликации и индексации
отдельно от основного приложения.

Интегрируется с общей системой логгирования проекта, используя те же
настройки уровня логгирования и формата.
"""

import logging
import os
from pathlib import Path
from typing import Optional


def setup_rag_catalog_logger(
    name: str = "rag_catalog",
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    include_console: bool = True,
) -> logging.Logger:
    """
    Настраивает логгер для rag_catalog воркера.

    Интегрируется с общей системой логгирования проекта, используя
    те же переменные окружения (LOG_LEVEL) и формат логов.

    Args:
        name: Имя логгера
        log_level: Уровень логгирования (DEBUG, INFO, WARNING, ERROR).
                  Если не указан, берется из RAG_CATALOG_LOG_LEVEL или LOG_LEVEL
        log_file: Путь к файлу логов (по умолчанию logs/rag_catalog.log)
        include_console: Включать ли вывод в консоль

    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(name)

    # Избегаем повторной настройки
    if logger.handlers:
        return logger

    # Определяем уровень логгирования (приоритет: параметр > RAG_CATALOG_LOG_LEVEL > LOG_LEVEL > INFO)
    if log_level is None:
        log_level = os.getenv("RAG_CATALOG_LOG_LEVEL", os.getenv("LOG_LEVEL", "INFO"))

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
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "rag_catalog.log"
    
    # Убеждаемся, что родительская директория для пользовательского log_file существует
    log_file_path = Path(log_file)
    parent_dir = log_file_path.parent
    if str(parent_dir) not in (".", ""):
        parent_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # Консольный хендлер (опционально)
    if include_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        # Явно устанавливаем UTF-8 для консоли
        if hasattr(console_handler.stream, 'reconfigure'):
            try:
                console_handler.stream.reconfigure(encoding='utf-8')
            except Exception:
                pass  # Игнорируем ошибки для совместимости
        logger.addHandler(console_handler)

    return logger


def get_rag_logger(name: str = "rag_catalog") -> logging.Logger:
    """
    Возвращает настроенный логгер для rag_catalog воркера.
    Если логгер еще не настроен, настраивает его с параметрами по умолчанию.

    Args:
        name: Имя логгера (можно использовать для создания подлоггеров)

    Returns:
        Логгер для rag_catalog воркера
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger = setup_rag_catalog_logger(name=name)
    return logger
