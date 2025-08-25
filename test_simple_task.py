#!/usr/bin/env python3
"""
Простой тест Celery задач в синхронном режиме.
Полезен для быстрой отладки без запуска воркера.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

from app.workers.gemini.tasks import process_tender_positions

# Загружаем переменные окружения
load_dotenv()


def simple_test():
    """Простой тест одной задачи напрямую"""

    # Получаем API ключ
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY не найден в .env")
        print("💡 Установите GOOGLE_API_KEY в файле .env для полного тестирования")
        return

    print(f"✅ GOOGLE_API_KEY найден: {api_key[:10]}...")

    # Ищем любой доступный файл позиций
    positions_dir = Path("tenders_positions")
    positions_files = list(positions_dir.glob("*_positions.md"))

    if not positions_files:
        print(f"❌ Файлы позиций не найдены в {positions_dir}")
        print("💡 Запустите парсинг тендера для создания файлов позиций")
        return

    positions_file = positions_files[0]  # Берем первый доступный
    print(f"✅ Используем файл позиций: {positions_file}")

    # Извлекаем tender_id и lot_id из имени файла (например, 134_134_positions.md)
    file_parts = positions_file.stem.split("_")
    if len(file_parts) >= 2:
        tender_id = file_parts[0]
        lot_id = file_parts[1]
    else:
        tender_id = "test_tender"
        lot_id = "test_lot"

    # Запускаем задачу напрямую (без Celery worker, синхронно)
    try:
        print("🚀 Запускаем задачу синхронно...")

        # Используем apply() вместо delay() для синхронного выполнения
        result = process_tender_positions.apply(args=[tender_id, lot_id, str(positions_file), api_key])

        print("✅ Задача выполнена! Результат:")
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
