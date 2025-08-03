# app/parse_with_gemini.py

"""
Модифицированная версия parse.py с интеграцией Gemini AI обработки.

Этот файл расширяет существующий функционал parse.py, добавляя:
1. Интеграцию с GeminiWorker для AI-анализа лотов
2. Поддержку асинхронной обработки через Redis
3. Возможность синхронной и асинхронной обработки
4. Улучшенное логирование и обработку ошибок
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.workers import GeminiIntegration

from .gemini_module.logger import get_gemini_logger

# Импортируем существующую функциональность
from .parse import parse_file as original_parse_file

log = logging.getLogger(__name__)


def parse_file_with_gemini(xlsx_path: str, async_processing: bool = False, redis_config: Optional[Dict] = None) -> bool:
    """
    Расширенная версия parse_file с интеграцией Gemini AI.

    Args:
        xlsx_path: Путь к XLSX файлу
        async_processing: Использовать асинхронную обработку через Redis
        redis_config: Конфигурация Redis {host, port, db}

    Returns:
        True если обработка прошла успешно
    """
    gemini_logger = get_gemini_logger()

    # Проверяем доступность Gemini API
    api_key = os.getenv("GOOGLE_API_KEY")
    gemini_enabled = bool(api_key)

    if not gemini_enabled:
        gemini_logger.warning("⚠️ GOOGLE_API_KEY не найден - пропускаю AI обработку")

    # Выполняем стандартную обработку parse.py
    log.info("🔄 Выполняю стандартную обработку файла...")

    try:
        original_parse_file(xlsx_path)
        log.info("✅ Стандартная обработка завершена успешно")
    except Exception as e:
        log.error(f"❌ Ошибка в стандартной обработке: {e}")
        return False

    # Если Gemini недоступен, завершаем здесь
    if not gemini_enabled:
        log.info("ℹ️ Обработка завершена без AI анализа")
        return True

    # Определяем пути к сгенерированным файлам
    source_path = Path(xlsx_path).resolve()
    output_dir = source_path.parent

    # Ищем сгенерированный JSON файл
    json_files = list(output_dir.glob("*.json"))
    if not json_files:
        log.error("❌ Не найден JSON файл после стандартной обработки")
        return False

    # Берем последний созданный JSON (предполагаем, что это наш тендер)
    tender_json_path = max(json_files, key=lambda p: p.stat().st_mtime)

    # Выполняем AI обработку
    return process_tender_with_gemini(
        tender_json_path=tender_json_path, async_processing=async_processing, redis_config=redis_config
    )


def process_tender_with_gemini(
    tender_json_path: Path, async_processing: bool = False, redis_config: Optional[Dict] = None
) -> bool:
    """
    Обрабатывает тендер с использованием Gemini AI.

    Args:
        tender_json_path: Путь к JSON файлу тендера
        async_processing: Использовать асинхронную обработку
        redis_config: Конфигурация Redis

    Returns:
        True если обработка прошла успешно
    """
    gemini_logger = get_gemini_logger()

    try:
        # Загружаем данные тендера
        with open(tender_json_path, "r", encoding="utf-8") as f:
            tender_data = json.load(f)

        tender_id = extract_tender_id(tender_json_path, tender_data)
        gemini_logger.info(f"🧠 Начинаю AI обработку тендера {tender_id}")

        # Настраиваем интеграцию
        redis_client = None
        if async_processing:
            redis_config = redis_config or {}
            redis_client = GeminiIntegration.setup_redis_client(
                host=redis_config.get("host", "localhost"),
                port=redis_config.get("port", 6379),
                db=redis_config.get("db", 0),
            )

            if not redis_client:
                gemini_logger.warning("⚠️ Redis недоступен, переключаюсь на синхронную обработку")
                async_processing = False

        integration = GeminiIntegration(redis_client=redis_client)

        # Создаем данные для positions файлов
        lots_data = integration.create_positions_file_data(tender_id, tender_data)

        if not lots_data:
            gemini_logger.warning("⚠️ Не найдены данные лотов для AI обработки")
            return True

        gemini_logger.info(f"📊 Найдено {len(lots_data)} лотов для обработки")

        if async_processing:
            # Асинхронная обработка через Redis
            success = integration.queue_tender_lots_async(tender_id, lots_data)

            if success:
                gemini_logger.info(f"✅ Все {len(lots_data)} лотов поставлены в очередь Redis")
                gemini_logger.info("ℹ️ Для отслеживания прогресса используйте статус-команды")
                return True
            else:
                gemini_logger.error("❌ Не удалось поставить все лоты в очередь")
                return False
        else:
            # Синхронная обработка
            gemini_logger.info("🔄 Выполняю синхронную AI обработку...")
            results = integration.process_tender_lots_sync(tender_id, lots_data)

            # Анализируем результаты
            successful = sum(1 for r in results if r.get("status") == "completed")
            failed = len(results) - successful

            gemini_logger.info(f"📈 AI обработка завершена: {successful} успешно, {failed} ошибок")

            # Сохраняем результаты AI обработки
            results_path = tender_json_path.parent / f"{tender_id}_gemini_results.json"
            with open(results_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)

            gemini_logger.info(f"💾 Результаты AI обработки сохранены: {results_path.name}")

            return failed == 0

    except Exception as e:
        gemini_logger.error(f"❌ Ошибка в AI обработке: {e}")
        return False


def extract_tender_id(json_path: Path, tender_data: Dict) -> str:
    """
    Извлекает ID тендера из различных источников.

    Args:
        json_path: Путь к JSON файлу
        tender_data: Данные тендера

    Returns:
        ID тендера
    """
    # Пытаемся получить ID из данных
    tender_id = tender_data.get("tender_id") or tender_data.get("db_id")

    # Если не найден, используем имя файла
    if not tender_id:
        tender_id = json_path.stem

    return str(tender_id)


def get_processing_status(tender_id: str, lot_ids: List[str], redis_config: Optional[Dict] = None) -> Dict:
    """
    Получает статус AI обработки для тендера.

    Args:
        tender_id: ID тендера
        lot_ids: Список ID лотов
        redis_config: Конфигурация Redis

    Returns:
        Словарь со статусами лотов
    """
    redis_client = None
    if redis_config:
        redis_client = GeminiIntegration.setup_redis_client(
            host=redis_config.get("host", "localhost"),
            port=redis_config.get("port", 6379),
            db=redis_config.get("db", 0),
        )

    if not redis_client:
        return {"error": "Redis недоступен"}

    integration = GeminiIntegration(redis_client=redis_client)
    return integration.get_processing_status(tender_id, lot_ids)


def main():
    """Консольный интерфейс для запуска обработки с Gemini"""
    parser = argparse.ArgumentParser(description="Обработка тендеров с Gemini AI")

    subparsers = parser.add_subparsers(dest="command", help="Команды")

    # Команда обработки файла
    process_parser = subparsers.add_parser("process", help="Обработать XLSX файл")
    process_parser.add_argument("xlsx_file", help="Путь к XLSX файлу")
    process_parser.add_argument("--async", action="store_true", help="Асинхронная обработка")
    process_parser.add_argument("--redis-host", default="localhost", help="Хост Redis")
    process_parser.add_argument("--redis-port", type=int, default=6379, help="Порт Redis")
    process_parser.add_argument("--redis-db", type=int, default=0, help="База Redis")

    # Команда проверки статуса
    status_parser = subparsers.add_parser("status", help="Проверить статус обработки")
    status_parser.add_argument("tender_id", help="ID тендера")
    status_parser.add_argument("lot_ids", nargs="+", help="ID лотов")
    status_parser.add_argument("--redis-host", default="localhost", help="Хост Redis")
    status_parser.add_argument("--redis-port", type=int, default=6379, help="Порт Redis")
    status_parser.add_argument("--redis-db", type=int, default=0, help="База Redis")

    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Настройка логирования
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        get_gemini_logger().setLevel(logging.DEBUG)

    redis_config = {
        "host": getattr(args, "redis_host", "localhost"),
        "port": getattr(args, "redis_port", 6379),
        "db": getattr(args, "redis_db", 0),
    }

    try:
        if args.command == "process":
            success = parse_file_with_gemini(
                xlsx_path=args.xlsx_file, async_processing=getattr(args, "async", False), redis_config=redis_config
            )
            return 0 if success else 1

        elif args.command == "status":
            statuses = get_processing_status(args.tender_id, args.lot_ids, redis_config)
            print(json.dumps(statuses, ensure_ascii=False, indent=2))
            return 0

    except KeyboardInterrupt:
        print("\n🛑 Прервано пользователем")
        return 1
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
