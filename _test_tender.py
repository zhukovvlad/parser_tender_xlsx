# _test_tender.py
# ⚠️  DEPRECATED: Этот файл устарел и будет удален в следующей версии
# 🚀 Используйте _test_tender_refactored.py для всех новых задач
# 📝 TODO: Удалить после полного перехода на новую версию

import json
import os
import warnings

# Показываем предупреждение при импорте
warnings.warn("⚠️  _test_tender.py устарел! Используйте _test_tender_refactored.py", DeprecationWarning, stacklevel=2)

from dotenv import load_dotenv

from app.gemini_module import TenderProcessor

# Импортируем все необходимые константы
from app.gemini_module.constants import (
    FALLBACK_CATEGORY,
    TENDER_CATEGORIES,
    TENDER_CONFIGS,
)

# --- Настройки ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
INPUT_FILE = "42_42_positions.md"


def main():
    print("⚠️  ВНИМАНИЕ: Вы используете устаревшую версию!")
    print("🚀 Переходите на _test_tender_refactored.py для лучшей функциональности")
    print("=" * 60)
    print("🚀 Запускаем интеллектуальный анализ документа...")

    if not API_KEY:
        print("❌ Ошибка: API ключ не найден.")
        return
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Ошибка: Входной файл не найден: {INPUT_FILE}")
        return

    processor = None
    try:
        processor = TenderProcessor(api_key=API_KEY).upload(INPUT_FILE)

        # --- ЭТАП 1: Классификация ---
        print("⏳ Определяю категорию документа...")
        tender_type = processor.classify(categories=TENDER_CATEGORIES, fallback_label=FALLBACK_CATEGORY)
        print(f"✅ Документ классифицирован как: '{tender_type}'")

        # --- ЭТАП 2: Интеллектуальное извлечение данных ---
        print(f"⏳ Извлекаю данные по шаблону для '{tender_type}'...")
        extracted_data = processor.extract_json(category=tender_type, configs=TENDER_CONFIGS)

        extracted_data["determined_tender_type"] = tender_type

        # --- ВЫВОД РЕЗУЛЬТАТА ---
        print("\n🎉 --- Итоговый результат анализа --- 🎉")
        print(json.dumps(extracted_data, ensure_ascii=False, indent=2))

    except Exception as e:
        print(f"❌ Произошла непредвиденная ошибка: {e}")

    finally:
        if processor:
            processor.delete_uploaded_file()


if __name__ == "__main__":
    main()
