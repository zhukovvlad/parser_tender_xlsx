#!/usr/bin/env python3
"""
Запуск всех тестов для gemini_module.

Этот скрипт запускает все доступные тесты для модуля gemini_module,
включая тесты логгирования, процессора и интеграционные тесты.
"""

import sys
from pathlib import Path

# Добавляем путь к корню проекта
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from test_gemini_logging import test_gemini_logging_integration
from test_logging import test_gemini_logging_basic
from test_processor_logging import test_processor_logging


def run_all_tests():
    """Запускает все тесты gemini_module."""

    print("🧪 Запуск всех тестов для gemini_module\n")

    tests = [
        ("Базовое логгирование", test_gemini_logging_basic),
        ("Интеграция логгирования", test_gemini_logging_integration),
        ("Логгирование процессора", test_processor_logging),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            print(f"▶️  Запуск теста: {test_name}")
            test_func()
            print(f"✅ {test_name} - УСПЕШНО\n")
            passed += 1
        except Exception as e:
            print(f"❌ {test_name} - ОШИБКА: {e}\n")
            failed += 1

    print("📊 Результаты:")
    print(f"   ✅ Успешно: {passed}")
    print(f"   ❌ Ошибок: {failed}")
    print(f"   📈 Всего: {passed + failed}")

    if failed == 0:
        print("\n🎉 Все тесты прошли успешно!")
        return True
    else:
        print(f"\n⚠️  {failed} тест(ов) завершились с ошибками")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
