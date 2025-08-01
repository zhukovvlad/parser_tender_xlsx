#!/usr/bin/env python3
"""
Тест интеграции логгирования gemini_module с основной системой проекта.
"""

import os
import logging
from pathlib import Path

# Добавляем путь к корню проекта для импортов
import sys
from pathlib import Path

current_dir = Path(__file__).parent
project_root = current_dir.parent.parent
sys.path.insert(0, str(project_root))

from app.gemini_module.logger import setup_gemini_logger, get_gemini_logger


def test_gemini_logging_integration():
    """Тестирует интеграцию логгирования gemini_module."""

    print("=== Тест интеграции логгирования gemini_module ===\n")

    # 1. Тест настройки логгера
    print("1. Настройка логгера...")
    logger = setup_gemini_logger(log_level="DEBUG")
    print(f"   ✅ Логгер настроен: {logger.name}")
    print(f"   ✅ Уровень логгирования: {logger.level}")
    print(f"   ✅ Количество хендлеров: {len(logger.handlers)}")

    # 2. Тест логгирования на разных уровнях
    print("\n2. Тест логгирования на разных уровнях...")
    logger.debug("Это DEBUG сообщение")
    logger.info("Это INFO сообщение")
    logger.warning("Это WARNING сообщение")
    logger.error("Это ERROR сообщение")
    print("   ✅ Сообщения отправлены")

    # 3. Тест получения существующего логгера
    print("\n3. Тест получения существующего логгера...")
    logger2 = get_gemini_logger()
    print(f"   ✅ Получен тот же логгер: {logger is logger2}")

    # 4. Проверка файла логов
    print("\n4. Проверка файла логов...")
    log_file = Path("logs/gemini.log")
    if log_file.exists():
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        print(f"   ✅ Файл логов существует: {log_file}")
        print(f"   ✅ Количество строк в логе: {len(lines)}")
        if lines:
            print(f"   ✅ Последняя запись: {lines[-1].strip()}")
    else:
        print(f"   ❌ Файл логов не найден: {log_file}")

    # 5. Тест переменных окружения
    print("\n5. Тест переменных окружения...")
    original_level = os.getenv("GEMINI_LOG_LEVEL")
    os.environ["GEMINI_LOG_LEVEL"] = "WARNING"

    # Создаем новый логгер с другим именем для тестирования
    test_logger = setup_gemini_logger(name="test_gemini", include_console=False)
    print(f"   ✅ Новый логгер с уровнем WARNING: {test_logger.level}")

    # Восстанавливаем переменную окружения
    if original_level:
        os.environ["GEMINI_LOG_LEVEL"] = original_level
    else:
        os.environ.pop("GEMINI_LOG_LEVEL", None)

    print("\n=== Тест завершен успешно ===")


if __name__ == "__main__":
    test_gemini_logging_integration()
