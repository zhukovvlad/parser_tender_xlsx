#!/usr/bin/env python3
"""
Тест логгирования в TenderProcessor без реального API ключа.
"""

import os
import sys

sys.path.append("/root/Projects/Python_projects/parser")

from app.gemini_module.logger import get_gemini_logger


def test_processor_logging():
    """Тестирует логгирование в TenderProcessor."""

    print("=== Тест логгирования TenderProcessor ===\n")

    # Получаем логгер как он используется в processor.py
    logger = get_gemini_logger()

    # Симулируем логи как в реальном processor.py
    print("1. Симуляция загрузки файла...")
    file_path = "test_file.xlsx"
    logger.info(f"Загружаю файл: {file_path}")
    logger.info("✅ Файл успешно загружен: files/test123")

    print("\n2. Симуляция классификации...")
    categories = ["котлован", "фундамент", "кровля"]
    categories_str = ", ".join([f"'{cat}'" for cat in categories])
    logger.debug(f"Классифицирую документ по категориям: {categories_str}")
    logger.debug("Отправляю запрос к модели models/gemini-1.5-pro")
    logger.debug("Получен ответ длиной 12 символов")
    logger.info("Документ классифицирован как: котлован")

    print("\n3. Симуляция извлечения JSON...")
    category = "котлован"
    logger.debug(f"Извлекаю JSON данные для категории: {category}")
    logger.info(f"Успешно извлечены JSON данные для категории '{category}'")

    print("\n4. Симуляция ошибки...")
    logger.warning("Модель не вернула кандидатов в ответе")
    logger.error("Не удалось распарсить JSON для категории 'котлован': Invalid JSON format")

    print("\n5. Симуляция очистки...")
    logger.info("Удаляю файл files/test123 с сервера")
    logger.info("🗑️ Файл успешно удален с сервера: files/test123")

    print("\n=== Все логи записаны в logs/gemini.log ===")


if __name__ == "__main__":
    test_processor_logging()
