#!/usr/bin/env python3
# app/workers/gemini/cli.py

"""
Консольный интерфейс для Gemini воркера.
"""

import argparse
import os
import sys
from pathlib import Path

# Добавляем корневую папку проекта в PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

# Загружаем переменные окружения
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent.parent.parent / '.env'
    load_dotenv(env_path)
except ImportError:
    env_file = Path(__file__).parent.parent.parent.parent / '.env'
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    os.environ[key] = value

from app.workers.gemini import GeminiManager, GeminiIntegration
from app.gemini_module.logger import get_gemini_logger


def main():
    parser = argparse.ArgumentParser(description="Gemini воркер для обработки тендеров")
    
    subparsers = parser.add_subparsers(dest="command", help="Доступные команды")
    
    # Команда для запуска воркера очереди
    queue_parser = subparsers.add_parser("worker", help="Запустить воркер очереди Redis")
    queue_parser.add_argument("--queue", default="ai_tasks", help="Имя очереди Redis")
    queue_parser.add_argument("--redis-host", default="localhost", help="Хост Redis")
    queue_parser.add_argument("--redis-port", type=int, default=6379, help="Порт Redis")
    
    # Команда для обработки файла
    process_parser = subparsers.add_parser("process", help="Обработать файл позиций")
    process_parser.add_argument("tender_id", help="ID тендера")
    process_parser.add_argument("lot_id", help="ID лота")
    process_parser.add_argument("positions_file", help="Путь к файлу positions.md")
    
    # Общие параметры
    parser.add_argument("--api-key", help="Google API ключ (по умолчанию из GOOGLE_API_KEY)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Настройка логирования
    logger = get_gemini_logger()
    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Получаем API ключ
    api_key = args.api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.error("❌ Google API ключ не найден. Установите GOOGLE_API_KEY или используйте --api-key")
        return 1
    
    try:
        if args.command == "worker":
            run_worker(api_key, args)
        elif args.command == "process":
            run_process(api_key, args)
        else:
            parser.print_help()
            
    except KeyboardInterrupt:
        logger.info("🛑 Прервано пользователем")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        return 1


def run_worker(api_key: str, args):
    """Запускает воркер очереди"""
    logger = get_gemini_logger()
    
    # Подключение к Redis
    try:
        import redis
        redis_client = redis.Redis(host=args.redis_host, port=args.redis_port, decode_responses=False)
        redis_client.ping()
        logger.info(f"✅ Подключение к Redis: {args.redis_host}:{args.redis_port}")
    except ImportError:
        logger.error("❌ Redis не установлен. Установите: pip install redis")
        return
    except Exception as e:
        logger.error(f"❌ Ошибка подключения к Redis: {e}")
        return
    
    # Создаем и запускаем менеджер
    manager = GeminiManager(api_key, redis_client)
    logger.info(f"🚀 Запускаю Gemini воркер очереди '{args.queue}'...")
    manager.run_queue_worker(args.queue)


def run_process(api_key: str, args):
    """Обрабатывает один файл"""
    logger = get_gemini_logger()
    
    positions_file = Path(args.positions_file)
    if not positions_file.exists():
        logger.error(f"❌ Файл не найден: {positions_file}")
        return
    
    # Создаем менеджер и обрабатываем
    manager = GeminiManager(api_key)
    
    from app.gemini_module.constants import TENDER_CATEGORIES, TENDER_CONFIGS, FALLBACK_CATEGORY
    
    task = {
        "tender_id": args.tender_id,
        "lot_id": args.lot_id,
        "positions_file_path": str(positions_file),
        "categories": TENDER_CATEGORIES,
        "configs": TENDER_CONFIGS,
        "fallback_category": FALLBACK_CATEGORY
    }
    
    logger.info(f"🔄 Обрабатываю файл: {positions_file}")
    result = manager.process_sync(task)
    
    # Выводим результат
    print(f"\n📊 Результат обработки:")
    print(f"   Тендер: {result.get('tender_id')}")
    print(f"   Лот: {result.get('lot_id')}")
    print(f"   Статус: {result.get('status')}")
    print(f"   Категория: {result.get('category')}")
    
    if result.get('status') == 'success':
        ai_data = result.get('ai_data', {})
        print(f"   Извлечено полей: {len(ai_data)}")
        if ai_data:
            print(f"   Данные: {list(ai_data.keys())}")
    else:
        print(f"   Ошибка: {result.get('error')}")


if __name__ == "__main__":
    main()
