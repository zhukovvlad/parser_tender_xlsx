# app/workers/rag_catalog/logger.py
"""
Логгер для RAG Catalog воркера.
"""

import logging
import os
from pathlib import Path

LOG_DIR = Path(os.getenv("LOG_DIR", "logs"))
LOG_DIR.mkdir(exist_ok=True)


def get_rag_logger(name: str = "rag_catalog") -> logging.Logger:
    """
    Создает и возвращает логгер для RAG модуля.
    
    Args:
        name: Имя логгера (по умолчанию "rag_catalog")
        
    Returns:
        Настроенный логгер
    """
    logger = logging.getLogger(f"rag_catalog.{name}")
    
    # Если уже настроен, возвращаем
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.DEBUG)
    
    # Файловый хэндлер
    file_handler = logging.FileHandler(
        LOG_DIR / "rag_catalog.log",
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    
    # Консольный хэндлер
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Форматтер
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
