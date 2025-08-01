#!/usr/bin/env python3
"""
Тест системы логгирования gemini_module.
Проверяет создание логгера, запись в файл и консоль.
"""

import os
import pytest
from pathlib import Path

from app.gemini_module.logger import setup_gemini_logger, get_gemini_logger


def test_setup_gemini_logger():
    """Тестирует настройку логгера gemini_module."""
    logger = setup_gemini_logger(name="test_logger", log_level="DEBUG")
    
    assert logger.name == "test_logger"
    assert logger.level == 10  # DEBUG level
    assert len(logger.handlers) == 2  # file + console handlers


def test_get_gemini_logger():
    """Тестирует получение логгера gemini_module."""
    logger = get_gemini_logger()
    
    assert logger.name == "gemini_module"
    assert len(logger.handlers) >= 1  # at least one handler


def test_logging_to_file():
    """Тестирует запись логов в файл."""
    # Используем временный файл для теста
    log_file = Path("logs/test_gemini.log")
    log_file.parent.mkdir(exist_ok=True)
    
    # Удаляем файл если он существует
    if log_file.exists():
        log_file.unlink()
    
    logger = setup_gemini_logger(
        name="test_file_logger", 
        log_file=str(log_file),
        include_console=False
    )
    
    test_message = "Тестовое сообщение для записи в файл"
    logger.info(test_message)
    
    # Проверяем, что файл создан и содержит наше сообщение
    assert log_file.exists()
    
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
        assert test_message in content
    
    # Очищаем после теста
    log_file.unlink()


def test_environment_variable_log_level():
    """Тестирует использование переменной окружения для уровня логгирования."""
    # Сохраняем текущее значение
    original_value = os.getenv("GEMINI_LOG_LEVEL")
    
    try:
        # Устанавливаем тестовое значение
        os.environ["GEMINI_LOG_LEVEL"] = "ERROR"
        
        logger = setup_gemini_logger(name="test_env_logger")
        assert logger.level == 40  # ERROR level
        
    finally:
        # Восстанавливаем исходное значение
        if original_value:
            os.environ["GEMINI_LOG_LEVEL"] = original_value
        else:
            os.environ.pop("GEMINI_LOG_LEVEL", None)


if __name__ == "__main__":
    pytest.main([__file__])
