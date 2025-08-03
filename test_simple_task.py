#!/usr/bin/env python3
"""
Простой тест Celery задач без фронтенда
"""

import os

from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from app.workers.gemini.tasks import process_tender_positions


def simple_test():
    """Простой тест одной задачи напрямую"""

    # Получаем API ключ
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY не найден в .env")
        return

    print(f"✅ GOOGLE_API_KEY найден: {api_key[:10]}...")

    # Проверяем существование файла позиций
    positions_file = (
        "/root/Projects/Python_projects/parser/pending_sync_positions/temp_1754203333_5037_594277_positions.md"
    )

    if not os.path.exists(positions_file):
        print(f"❌ Файл позиций не найден: {positions_file}")
        return

    print(f"✅ Файл позиций найден: {positions_file}")

    # Запускаем задачу напрямую (без Celery worker, синхронно)
    try:
        print("🚀 Запускаем задачу синхронно...")

        # Используем apply() вместо delay() для синхронного выполнения
        result = process_tender_positions.apply(args=["test_tender", "test_lot", positions_file, api_key])

        print(f"✅ Задача выполнена! Результат:")
        print(f"   Статус: {result.result.get('status')}")
        print(f"   Категория: {result.result.get('category')}")

        ai_data = result.result.get("ai_data", {})
        print(f"   AI данных: {len(ai_data)} полей")

    except Exception as e:
        print(f"❌ Ошибка выполнения задачи: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    simple_test()
