#!/usr/bin/env python3
"""
Тест системы логгирования gemini_module.
Проверяет создание логгера, запись в файл и консоль.
"""

import os
import sys
from pathlib import Path

# Добавляем путь к проекту
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.gemini_module.logger import setup_gemini_logger, get_gemini_logger


def test_logging_setup():
    """Тестирует настройку логгирования."""
    print("🧪 Тестирование системы логгирования gemini_module")

    # Тест 1: Создание логгера
    print("\n1️⃣ Тестирую создание логгера...")
    logger = setup_gemini_logger(log_level="DEBUG")

    # Тест 2: Проверка уровней логгирования
    print("2️⃣ Тестирую различные уровни логгирования...")
    logger.debug("🔍 DEBUG сообщение - детали работы")
    logger.info("ℹ️ INFO сообщение - общая информация")
    logger.warning("⚠️ WARNING сообщение - предупреждение")
    logger.error("❌ ERROR сообщение - ошибка")

    # Тест 3: Получение существующего логгера
    print("3️⃣ Тестирую получение существующего логгера...")
    logger2 = get_gemini_logger()
    logger2.info("✅ Логгер получен успешно")

    # Тест 4: Проверка файла логов
    log_file = Path("logs/gemini.log")
    if log_file.exists():
        print(f"4️⃣ ✅ Файл логов создан: {log_file}")
        print(f"   📊 Размер файла: {log_file.stat().st_size} байт")
    else:
        print("4️⃣ ❌ Файл логов не создан")

    print("\n🎉 Тестирование завершено!")


if __name__ == "__main__":
    test_logging_setup()
