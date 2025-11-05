#!/usr/bin/env python3
"""
Тестовый скрипт для проверки работы Gemini с файлами позиций.

Использование:
    python test_gemini_positions.py <путь_к_файлу_позиций>
    
Примеры:
    python test_gemini_positions.py tenders_positions/2_2_positions.md
    python test_gemini_positions.py tenders_positions/6_6_positions.md
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from app.gemini_module.constants import FALLBACK_CATEGORY, TENDER_CONFIGS
from app.gemini_module.processor import TenderProcessor

load_dotenv()


def main():
    parser = argparse.ArgumentParser(
        description="Тестирование Gemini на файлах позиций",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  %(prog)s tenders_positions/2_2_positions.md
  %(prog)s tenders_positions/6_6_positions.md --verbose
  %(prog)s tenders_positions/1_1_positions.md --model gemini-2.0-flash-exp
        """,
    )
    
    parser.add_argument(
        "positions_file",
        type=str,
        help="Путь к MD-файлу с позициями тендера"
    )
    
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-flash",
        help="Модель Gemini для использования (по умолчанию: gemini-2.5-flash)"
    )
    
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Подробный вывод с DEBUG логами"
    )
    
    parser.add_argument(
        "--save-result",
        action="store_true",
        help="Сохранить результат в JSON файл"
    )
    
    args = parser.parse_args()
    
    # Проверяем наличие API ключа
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ Ошибка: GOOGLE_API_KEY не найден в переменных окружения")
        print("   Убедитесь, что файл .env содержит GOOGLE_API_KEY")
        return 1
    
    # Проверяем наличие файла
    positions_path = Path(args.positions_file)
    if not positions_path.exists():
        print(f"❌ Ошибка: Файл не найден: {positions_path}")
        return 1
    
    print(f"\n{'='*70}")
    print(f"🧪 Тестирование Gemini на файле позиций")
    print(f"{'='*70}")
    print(f"📄 Файл: {positions_path}")
    print(f"🤖 Модель: {args.model}")
    print(f"📏 Размер файла: {positions_path.stat().st_size:,} байт")
    print(f"{'='*70}\n")
    
    overall_start = time.time()
    
    try:
        # Создаем процессор
        print("🔧 Инициализация Gemini API...")
        processor = TenderProcessor(api_key=api_key)
        
        # Загружаем файл
        print(f"📤 Загрузка файла на сервер Gemini...")
        processor.upload(str(positions_path))
        
        # Шаг 1: Классификация
        print("\n" + "="*70)
        print("📋 ШАГ 1: Классификация документа")
        print("="*70)
        
        categories = list(TENDER_CONFIGS.keys())
        categories.remove(FALLBACK_CATEGORY)  # Исключаем fallback
        
        print(f"Доступные категории: {', '.join(categories)}")
        
        step1_start = time.time()
        category = processor.classify(categories, fallback_label=FALLBACK_CATEGORY)
        step1_time = time.time() - step1_start
        
        print(f"\n✅ Результат классификации: {category}")
        print(f"⏱️  Время: {step1_time:.2f} сек")
        
        # Шаг 2: Извлечение данных
        print("\n" + "="*70)
        print("📊 ШАГ 2: Извлечение структурированных данных")
        print("="*70)
        
        if category == FALLBACK_CATEGORY:
            print(f"⚠️  Документ классифицирован как '{FALLBACK_CATEGORY}'")
            print("   Используется базовая структура данных")
        
        print("⏳ Обработка... (может занять до 2-3 минут для больших файлов)")
        
        step2_start = time.time()
        result = processor.extract_json(
            category=category,
            configs=TENDER_CONFIGS,
            model_name=args.model
        )
        step2_time = time.time() - step2_start
        
        print(f"\n⏱️  Время извлечения: {step2_time:.2f} сек")
        print("\n✅ Извлеченные данные:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        
        # Сохранение результата
        if args.save_result:
            output_file = positions_path.with_suffix('.gemini_result.json')
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump({
                    "file": str(positions_path),
                    "model": args.model,
                    "category": category,
                    "extracted_data": result
                }, f, ensure_ascii=False, indent=2)
            print(f"\n💾 Результат сохранен в: {output_file}")
        
        # Очистка
        print("\n🧹 Удаление временного файла с сервера Gemini...")
        processor.delete_uploaded_file()
        
        overall_time = time.time() - overall_start
        
        print("\n" + "="*70)
        print("✅ Тестирование завершено успешно!")
        print(f"⏱️  Общее время: {overall_time:.2f} сек")
        print("="*70)
        
        return 0
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        return 130
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
