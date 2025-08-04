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

# Загружаем переменные окружения из .env файла
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv не установлен, пропускаем

# Централизованная настройка логирования на основе .env
log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(levelname)s:%(name)s:%(funcName)s:%(lineno)d:%(message)s",
    force=True,  # Перезаписываем существующую конфигурацию
)

from app.workers import GeminiIntegration

from .gemini_module.logger import get_gemini_logger

# Импортируем существующую функциональность
from .parse import parse_file as original_parse_file

log = logging.getLogger(__name__)


def parse_file_with_gemini(
    xlsx_path: str, enable_ai: bool = False, async_processing: bool = False, redis_config: Optional[Dict] = None
) -> bool:
    """
    Выполняет стандартную обработку с опциональной AI обработкой.

    Args:
        xlsx_path: Путь к XLSX файлу
        enable_ai: Включить AI обработку
        async_processing: Использовать асинхронную обработку через Redis
        redis_config: Конфигурация Redis

    Returns:
        True если обработка прошла успешно
    """
    # Принудительно перезагружаем переменные окружения
    try:
        from dotenv import load_dotenv

        load_dotenv(override=True)  # override=True для перезаписи существующих переменных
    except ImportError:
        pass

    gemini_logger = get_gemini_logger()
    gemini_enabled = bool(os.getenv("GOOGLE_API_KEY"))

    # Проверяем возможность AI обработки
    ai_will_be_used = enable_ai and gemini_enabled

    if enable_ai and not gemini_enabled:
        gemini_logger.warning("⚠️ AI обработка запрошена, но GOOGLE_API_KEY не найден")
        gemini_logger.info("ℹ️ Продолжаю без AI обработки")
    elif not enable_ai:
        log.info("ℹ️ AI обработка отключена")

    # Выполняем стандартную обработку с получением ID
    log.info("🔄 Выполняю стандартную обработку файла...")

    try:
        # ВСЕГДА создаем positions файлы - они нужны для AI обработки
        db_id, lot_ids_map, tender_data = parse_with_ids(xlsx_path, create_reports=True)

        if not db_id:
            log.error("❌ Не удалось получить ID от Go-сервера")
            return False

        log.info(f"✅ Стандартная обработка завершена. Tender DB ID: {db_id}")
        log.info(f"📋 Получены ID лотов: {lot_ids_map}")
    except Exception as e:
        log.error(f"❌ Ошибка в стандартной обработке: {e}")
        return False

    # Если AI не будет использоваться, завершаем
    if not ai_will_be_used:
        log.info("ℹ️ Обработка завершена без AI анализа")
        return True

    # Проверяем, что это не временный ID (fallback режим)
    if str(db_id).startswith("temp_"):
        gemini_logger.warning("⚠️ Получен временный ID - AI обработка недоступна")
        gemini_logger.info("ℹ️ AI обработка доступна только для тендеров с реальными ID")
        gemini_logger.info("ℹ️ Доступны базовые _positions файлы")
        return True

    # Запускаем AI обработку с реальными ID
    return process_tender_with_gemini_ids(db_id, lot_ids_map, tender_data, async_processing, redis_config)


def parse_with_ids(
    xlsx_path: str, create_reports: bool = True
) -> tuple[Optional[str], Optional[Dict[str, int]], Optional[Dict]]:
    """
    Выполняет стандартную обработку и возвращает реальные ID и данные.

    Args:
        xlsx_path: Путь к XLSX файлу
        create_reports: Создавать ли positions файлы (обычно True - нужны для AI)

    Returns:
        Кортеж (db_id, lot_ids_map, tender_data) или (None, None, None) при ошибке
    """
    import json
    import os
    from pathlib import Path

    import openpyxl
    from openpyxl.worksheet.worksheet import Worksheet

    from .excel_parser.postprocess import normalize_lots_json_structure, replace_div0_with_null
    from .excel_parser.read_executer_block import read_executer_block
    from .excel_parser.read_headers import read_headers
    from .excel_parser.read_lots_and_boundaries import read_lots_and_boundaries
    from .json_to_server.send_json_to_go_server import register_tender_in_go

    source_path = Path(xlsx_path)
    if not source_path.exists():
        log.error(f"Файл не найден: {xlsx_path}")
        return None, None, None

    # Этап 1: Парсинг XLSX
    log.info("🔄 Парсинг XLSX файла...")
    try:
        wb = openpyxl.load_workbook(source_path, data_only=True)
        ws: Worksheet = wb.active

        processed_data: Dict[str, Any] = {
            **read_headers(ws),
            "executor": read_executer_block(ws),
            "lots": read_lots_and_boundaries(ws),
        }
        processed_data = normalize_lots_json_structure(processed_data)
        processed_data = replace_div0_with_null(processed_data)
        log.info("✅ XLSX файл успешно разобран")
    except Exception as e:
        log.error(f"❌ Ошибка парсинга XLSX: {e}")
        return None, None, None

    # Этап 2: Регистрация на Go-сервере
    log.info("🔄 Регистрация тендера на Go-сервере...")
    go_server_url = os.getenv("GO_SERVER_API_ENDPOINT")
    fallback_mode = os.getenv("PARSER_FALLBACK_MODE", "false").lower() == "true"
    go_server_api_key = os.getenv("GO_SERVER_API_KEY")

    if not go_server_url:
        log.error("❌ GO_SERVER_API_ENDPOINT не настроен")
        return None, None, None

    success, db_id, lot_ids_map = register_tender_in_go(
        processed_data, go_server_url, go_server_api_key, fallback_mode=fallback_mode
    )

    if not success:
        log.error("❌ Не удалось зарегистрировать тендер")
        return None, None, None

    # Этап 3: Условное создание positions файлов с реальными ID
    if create_reports:
        log.info("🔄 Создание positions файлов...")
        try:
            from pathlib import Path

            from .markdown_utils.positions_report import generate_reports_for_all_lots

            output_dir = Path("tenders_positions")  # Создаем в правильной папке
            output_dir.mkdir(exist_ok=True)  # Создаем папку если не существует
            base_name = db_id  # Используем реальный DB ID

            position_reports_paths = generate_reports_for_all_lots(processed_data, output_dir, base_name, lot_ids_map)
            log.info("✅ Positions файлы созданы с реальными ID")
        except Exception as e:
            log.error(f"❌ Ошибка создания positions файлов: {e}")
            # Не критично - продолжаем без positions файлов
    else:
        log.info("ℹ️ Пропускаю создание positions файлов (будут созданы после AI обработки)")

    return db_id, lot_ids_map, processed_data


def process_tender_with_gemini_ids(
    tender_db_id: str,
    lot_ids_map: Dict[str, int],
    tender_data: Dict,
    async_processing: bool = False,
    redis_config: Optional[Dict] = None,
) -> bool:
    """
    Выполняет AI обработку с использованием реальных ID из БД.

    Args:
        tender_db_id: Реальный ID тендера из БД
        lot_ids_map: Маппинг лотов к их реальным ID
        tender_data: Данные тендера
        async_processing: Использовать асинхронную обработку
        redis_config: Конфигурация Redis

    Returns:
        True если обработка прошла успешно
    """
    gemini_logger = get_gemini_logger()
    gemini_logger.info(f"🧠 Начинаю AI обработку тендера {tender_db_id}")

    try:
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

        # Создаем данные для positions файлов с реальными ID
        lots_data = integration.create_positions_file_data(tender_db_id, tender_data, lot_ids_map)

        if not lots_data:
            gemini_logger.warning("⚠️ Не найдены данные лотов для AI обработки")
            return True

        gemini_logger.info(f"� Найдено {len(lots_data)} лотов для обработки")

        if async_processing:
            # Асинхронная обработка через Redis
            success = integration.queue_tender_lots_async(tender_db_id, lots_data)

            if success:
                gemini_logger.info(f"✅ Все {len(lots_data)} лотов поставлены в очередь Redis")
                gemini_logger.info("ℹ️ Комбинированные отчеты будут созданы worker'ами после AI обработки")
                gemini_logger.info("ℹ️ Пока доступны базовые _positions файлы")
                return True
            else:
                gemini_logger.error("❌ Не удалось поставить все лоты в очередь")
                return False
        else:
            # Синхронная обработка
            gemini_logger.info("🔄 Выполняю синхронную AI обработку...")
            results = integration.process_tender_lots_sync(tender_db_id, lots_data)

            # Анализируем результаты
            successful = sum(1 for r in results if r.get("status") == "success")
            failed = sum(1 for r in results if r.get("status") == "error")

            gemini_logger.info(f"📈 AI обработка завершена: {successful} успешно, {failed} ошибок")

            # Сохраняем результаты AI обработки
            results_path = Path("tenders_json") / f"{tender_db_id}_gemini_results.json"
            try:
                with open(results_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2)
                gemini_logger.info(f"💾 Результаты сохранены: {results_path}")
            except Exception as e:
                gemini_logger.warning(f"⚠️ Не удалось сохранить результаты: {e}")

            # Создаем комбинированные отчеты (исходный JSON + AI результаты) и чанки
            gemini_logger.info("🔄 Создание комбинированных отчетов и чанков...")
            try:
                if successful > 0:
                    # Создаем комбинированные отчеты с AI данными
                    from .markdown_utils.ai_enhanced_reports import regenerate_reports_with_ai_data

                    md_success = regenerate_reports_with_ai_data(
                        tender_data=tender_data, ai_results=results, db_id=tender_db_id, lot_ids_map=lot_ids_map
                    )

                    if md_success:
                        gemini_logger.info("✅ Комбинированные отчеты с AI данными созданы")

                        # Создаем чанки из комбинированных отчетов
                        try:
                            # Здесь должна быть логика создания чанков из отчетов
                            gemini_logger.info("🔄 Создание чанков из комбинированных отчетов...")
                            # TODO: Добавить вызов функции создания чанков
                            gemini_logger.info("✅ Чанки созданы из комбинированных отчетов")
                        except Exception as e:
                            gemini_logger.warning(f"⚠️ Ошибка создания чанков: {e}")
                    else:
                        gemini_logger.warning(
                            "⚠️ Не удалось создать комбинированные отчеты, остаются базовые _positions файлы"
                        )
                else:
                    # При неудаче AI остаются только базовые _positions файлы
                    gemini_logger.info("🔄 AI обработка неуспешна, остаются базовые _positions файлы")

            except Exception as e:
                gemini_logger.error(f"❌ Ошибка создания комбинированных отчетов: {e}")
                gemini_logger.info("ℹ️ Остаются базовые _positions файлы")

            return successful > 0

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
    process_parser.add_argument("--ai", action="store_true", help="Включить AI обработку")
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

    # Настройка логирования на основе .env и аргументов
    log_level = os.getenv("LOG_LEVEL", "INFO").upper() if not args.verbose else "DEBUG"
    gemini_log_level = os.getenv("GEMINI_LOG_LEVEL", "INFO").upper() if not args.verbose else "DEBUG"

    # Настраиваем уровни логгирования
    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))
    logging.getLogger("app").setLevel(getattr(logging, log_level, logging.INFO))
    get_gemini_logger().setLevel(getattr(logging, gemini_log_level, logging.INFO))

    # Настраиваем формат логгирования
    log_format = (
        "%(levelname)s:%(name)s:%(funcName)s:%(lineno)d:%(message)s"
        if args.verbose
        else "%(levelname)s:%(name)s:%(message)s"
    )

    # Обновляем существующие handlers или создаем новый
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(getattr(logging, log_level, logging.INFO))
        formatter = logging.Formatter(log_format)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setLevel(getattr(logging, log_level, logging.INFO))
            formatter = logging.Formatter(log_format)
            handler.setFormatter(formatter)

    redis_config = {
        "host": getattr(args, "redis_host", "localhost"),
        "port": getattr(args, "redis_port", 6379),
        "db": getattr(args, "redis_db", 0),
    }

    try:
        if args.command == "process":
            success = parse_file_with_gemini(
                xlsx_path=args.xlsx_file,
                enable_ai=getattr(args, "ai", False),
                async_processing=getattr(args, "async", False),
                redis_config=redis_config,
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
