# app/parse_with_gemini.py

"""
Модифицированная версия parse.py с интеграцией Gemini AI обработки.

Этот файл расширяет существующий функционал parse.py, добавляя:
1. Интеграцию с GeminiWorker / TenderProcessor для AI-анализа лотов
2. Поддержку асинхронной обработки через Redis (через ваш workers.gemini)
3. Возможность синхронной и асинхронной обработки
4. Улучшенное логирование и обработку ошибок

Примечания по стилю / безопасные изменения:
- НЕ настраиваем logging.basicConfig на уровне модуля (чтобы не ломать конфиг сервиса/воркера).
- НЕ вызываем повторный load_dotenv внутри функций.
- Чиним mkdir для путей сохранения.
- Подправлен импорт GeminiIntegration (точный путь в пакете app.workers.gemini).
- В CLI оставлены оба флага: --async и --async-mode (оба мапятся в async_mode) для обратной совместимости.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.gemini_module.logger import get_gemini_logger
from app.workers.gemini.integration import GeminiIntegration

# Загружаем переменные окружения из .env файла один раз — при импорте модуля
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv не установлен, пропускаем

# Логгер модуля (использует глобальную конфигурацию приложения)
log = logging.getLogger(__name__)


# Импорт интеграции Gemini (воркерная обёртка) и логгера модуля

# Импорт существующей функциональности базового парсера
# (если нужно вызывать существующий parse_file, импортируйте тут)
# from .parse import parse_file as original_parse_file  # <- не используется


def parse_file_with_gemini(
    xlsx_path: str,
    enable_ai: bool = False,
    async_processing: bool = False,
    redis_config: Optional[Dict] = None,
) -> bool:
    """
    Выполняет стандартную обработку XLSX, затем опционально запускает AI обработку (Gemini).

    Args:
        xlsx_path: Путь к XLSX файлу
        enable_ai: Включить AI обработку (требует GOOGLE_API_KEY)
        async_processing: Использовать асинхронную обработку через Redis (см. workers.gemini)
        redis_config: Конфигурация Redis для async режима

    Returns:
        True если обработка прошла успешно (даже без AI), False при фатальной ошибке базового парсинга
    """
    gemini_logger = get_gemini_logger()

    # Проверяем возможность AI обработки
    gemini_enabled = bool(os.getenv("GOOGLE_API_KEY"))
    ai_will_be_used = bool(enable_ai and gemini_enabled)

    if enable_ai and not gemini_enabled:
        gemini_logger.warning("⚠️ AI обработка запрошена, но GOOGLE_API_KEY не найден. Продолжаю без AI.")
    elif not enable_ai:
        log.info("AI обработка отключена (enable_ai=False)")
    else:
        log.info("AI обработка включена: GOOGLE_API_KEY найден, enable_ai=True")

    # Выполняем стандартную обработку с получением ID
    log.info("🔄 Выполняю стандартную обработку файла…")

    try:
        # ВСЕГДА создаем positions файлы - они нужны для AI обработки
        # Передаем информацию о том, будет ли AI использоваться
        db_id, lot_ids_map, tender_data = parse_with_ids(
            xlsx_path, 
            create_reports=True,
            will_use_ai=ai_will_be_used
        )

        if not db_id:
            log.error("❌ Не удалось получить ID от Go-сервера")
            return False

        log.info("✅ Стандартная обработка завершена. Tender DB ID: %s", db_id)
        log.debug("📋 Получены ID лотов: %s", lot_ids_map)
    except Exception:
        log.exception("❌ Ошибка в стандартной обработке")
        return False

    # Если AI не будет использоваться, завершаем
    if not ai_will_be_used:
        log.info("ℹ️ Обработка завершена без AI анализа")
        return True

    # Проверяем, что это не временный ID (fallback режим)
    if str(db_id).startswith("temp_"):
        gemini_logger.warning("⚠️ Получен временный ID — AI обработка недоступна")
        gemini_logger.info("ℹ️ AI обработка доступна только для тендеров с реальными ID")
        gemini_logger.info("ℹ️ Доступны базовые _positions файлы")
        return True

    # Запускаем AI обработку с реальными ID
    return process_tender_with_gemini_ids(db_id, lot_ids_map, tender_data, async_processing, redis_config)


def parse_with_ids(
    xlsx_path: str, 
    create_reports: bool = True,
    will_use_ai: bool = False
) -> tuple[Optional[str], Optional[Dict[str, int]], Optional[Dict]]:
    """
    Выполняет стандартную обработку и возвращает реальные ID и данные.

    Args:
        xlsx_path: Путь к XLSX файлу
        create_reports: Создавать ли positions файлы (обычно True — нужны для AI)
        will_use_ai: Будет ли использоваться AI обработка (влияет на создание MD/chunks)

    Returns:
        Кортеж (db_id, lot_ids_map, tender_data) или (None, None, None) при ошибке
    """
    import openpyxl
    from openpyxl.worksheet.worksheet import Worksheet

    from .excel_parser.postprocess import (
        normalize_lots_json_structure,
        replace_div0_with_null,
    )
    from .excel_parser.read_executer_block import read_executer_block
    from .excel_parser.read_headers import read_headers
    from .excel_parser.read_lots_and_boundaries import read_lots_and_boundaries

    source_path = Path(xlsx_path)
    if not source_path.exists():
        log.error("Файл не найден: %s", xlsx_path)
        return None, None, None

    # Этап 1: Парсинг XLSX
    log.info("🔄 Парсинг XLSX файла…")
    wb = None
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
    except Exception:
        log.exception("❌ Ошибка парсинга XLSX")
        return None, None, None
    finally:
        try:
            if wb is not None:
                wb.close()
        except Exception:
            pass

    # Этап 2: Регистрация на Go-сервере
    log.info("🔄 Регистрация тендера на Go-сервере…")

    try:
        db_id, lot_ids_map = _import_full_tender_via_go(processed_data)
    except Exception as e:
        log.error(f"❌ Ошибка регистрации тендера на Go-сервере: {e}")
        return None, None, None

    # (опционально) сохраняем базовый JSON локально, если включён SAVE_DEBUG_FILES
    if os.getenv("SAVE_DEBUG_FILES", "false").lower() == "true":
        try:
            out_dir = Path("tenders_json")
            out_dir.mkdir(parents=True, exist_ok=True)
            base_json_path = out_dir / f"{db_id}_base.json"
            with open(base_json_path, "w", encoding="utf-8") as f:
                json.dump(processed_data, f, ensure_ascii=False, indent=2)
            log.info("💾 Базовый JSON сохранён: %s", base_json_path)
        except Exception:
            log.warning("⚠️ Не удалось сохранить базовый JSON", exc_info=True)

    # Этап 3: Создание файлов с реальными ID
    # Согласно диаграмме пайплайна:  # noqa: RUF001
    # 1. Positions файлы (для AI)
    # 2. Полный MD с описанием тендера (json_to_markdown)
    # 3. Обогащенный MD с ключевыми параметрами + AI данными
    # 4. Chunks для векторной БД
    if create_reports:
        log.info("🔄 Создание локальных артефактов…")  # noqa: RUF001
        try:
            from .markdown_utils.positions_report import generate_reports_for_all_lots
            from .markdown_utils.json_to_markdown import generate_markdown_for_lots

            # 3.1 ВСЕГДА создаем positions файлы (нужны для AI обработки)
            output_dir = Path("tenders_positions")
            output_dir.mkdir(parents=True, exist_ok=True)
            base_name = db_id  # Используем реальный DB ID

            _ = generate_reports_for_all_lots(processed_data, output_dir, base_name, lot_ids_map)
            log.info("✅ Positions файлы созданы с реальными ID")  # noqa: RUF001

            # 3.2 ВСЕГДА создаем полный MD с описанием тендера (БЕЗ AI данных)
            # Это базовый MD из JSON - шаг 2 в диаграмме
            log.info("🔄 Создание полного MD с описанием тендера (из JSON)...")  # noqa: RUF001
            lot_markdowns, _initial_metadata = generate_markdown_for_lots(processed_data)
            
            # Сохраняем базовый полный MD для каждого лота
            base_md_dir = Path("tenders_md_base")
            base_md_dir.mkdir(parents=True, exist_ok=True)
            
            for lot_key, markdown_lines in lot_markdowns.items():
                real_lot_id = lot_ids_map.get(lot_key)
                if real_lot_id:
                    base_md_path = base_md_dir / f"{db_id}_{real_lot_id}_base.md"
                    with open(base_md_path, "w", encoding="utf-8") as f:
                        f.write("\n".join(markdown_lines))
                    log.info(f"📄 Сохранен базовый MD: {base_md_path.name}")  # noqa: RUF001
            
            log.info("✅ Полный MD с описанием тендера создан")  # noqa: RUF001

            # 3.3 Создаем обогащенный MD и chunks
            # Если AI НЕ будет использоваться - создаем сразу с заглушкой
            # Если AI будет - создание отложится до получения реальных AI данных
            if not will_use_ai:
                log.info("🔄 AI не будет использоваться - создаем обогащенный MD с заглушкой")  # noqa: RUF001
                from .markdown_utils.ai_enhanced_reports import regenerate_reports_with_ai_data
                
                # Создаем заглушку для AI результатов
                ai_stub_results = []
                for _lot_key, lot_db_id in lot_ids_map.items():
                    ai_stub_results.append({
                        "lot_id": lot_db_id,
                        "category": "Test mode",
                        "ai_data": {"message": "No data. Test mode"},
                        "processed_at": "",
                        "status": "stub"
                    })
                
                # Создаем обогащенный MD с заглушкой
                success = regenerate_reports_with_ai_data(
                    tender_data=processed_data,
                    ai_results=ai_stub_results,
                    db_id=str(db_id),
                    lot_ids_map=lot_ids_map
                )
                
                if success:
                    log.info("✅ Обогащенный MD и chunks созданы с заглушкой AI данных")
                else:
                    log.warning("⚠️ Ошибка создания обогащенного MD с заглушкой")
            else:
                log.info("ℹ️ AI будет использоваться - обогащенный MD будет создан после получения AI результатов")
                
        except Exception:
            log.exception("❌ Ошибка создания файлов (не критично)")
    else:
        log.info("ℹ️ Пропускаю создание файлов")

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

    При async_processing=True запускает Celery задачи (асинхронная обработка).
    При async_processing=False выполняет синхронную обработку напрямую.
    """
    gemini_logger = get_gemini_logger()
    gemini_logger.info("🧠 Начинаю AI обработку тендера %s (async=%s)", tender_db_id, async_processing)

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        gemini_logger.warning("⚠️ GOOGLE_API_KEY не задан — AI недоступен")
        return True  # продолжаем как «без AI»

    positions_dir = Path("tenders_positions")

    # Асинхронная обработка через Celery
    if async_processing:
        gemini_logger.info("🔄 Режим: асинхронная обработка через Celery")
        try:
            celery_tasks_queued = 0
            gemini_logger.info("🔍 Ищу файлы позиций в %s для лотов: %s", positions_dir, lot_ids_map)

            for lot_key, lot_db_id in lot_ids_map.items():
                positions_file = positions_dir / f"{tender_db_id}_{lot_db_id}_positions.md"

                if positions_file.exists():
                    gemini_logger.info("🔄 Запускаю Celery задачу для лота %s (файл: %s)", lot_db_id, positions_file.name)

                    # Импортируем и запускаем Celery задачу
                    from app.workers.gemini.tasks import process_tender_positions

                    task = process_tender_positions.delay(
                        tender_id=str(tender_db_id),
                        lot_id=str(lot_db_id),
                        positions_file_path=str(positions_file),
                        api_key=api_key,
                    )
                    gemini_logger.info("✅ Celery задача запущена: %s для лота %s", task.id, lot_db_id)
                    celery_tasks_queued += 1
                else:
                    gemini_logger.warning("⚠️ Файл позиций не найден для лота %s: %s", lot_db_id, positions_file)

            if celery_tasks_queued > 0:
                gemini_logger.info("🚀 Запущено %d Celery задач для AI обработки лотов", celery_tasks_queued)
                gemini_logger.info("ℹ️ Результаты будут отправлены на Go сервер автоматически при завершении задач")
                return True
            else:
                gemini_logger.warning("⚠️ Не найдено файлов позиций для AI обработки")
                return False

        except Exception as e:
            gemini_logger.error("❌ Ошибка при запуске Celery задач: %s", e)
            gemini_logger.info("🔄 Переходим к резервному синхронному режиму")
            # Fallthrough к синхронной обработке

    # Синхронная обработка
    gemini_logger.info("🔄 Режим: синхронная обработка")
    try:
        integration = GeminiIntegration(api_key=api_key)
        lots_data = integration.create_positions_file_data(tender_db_id, tender_data, lot_ids_map)

        if not lots_data:
            gemini_logger.warning("⚠️ Не найдено файлов позиций для синхронной обработки")
            return False

        gemini_logger.info("📋 Запускаю синхронную AI обработку для %d лотов", len(lots_data))
        results = integration.process_tender_lots_sync(tender_db_id, lots_data)

        # Отправляем результаты в БД
        successful_sends = 0
        for result in results:
            if result.get("status") == "success":
                from app.json_to_server.ai_results_client import (
                    save_ai_results_offline,
                    send_lot_ai_results,
                )

                ok, status_code, _ = send_lot_ai_results(
                    tender_id=result.get("tender_id"),
                    lot_id=result.get("lot_id"),
                    category=result.get("category", ""),
                    ai_data=result.get("ai_data", {}),
                    processed_at=result.get("processed_at", ""),
                )

                if ok:
                    gemini_logger.info(
                        "💾 AI результаты отправлены на Go для %s_%s (status=%s)",
                        result.get("tender_id"),
                        result.get("lot_id"),
                        status_code,
                    )
                    successful_sends += 1
                else:
                    offline_path = save_ai_results_offline(
                        tender_id=result.get("tender_id"),
                        lot_id=result.get("lot_id"),
                        category=result.get("category", ""),
                        ai_data=result.get("ai_data", {}),
                        processed_at=result.get("processed_at", ""),
                        reason="request_failed",
                    )
                    gemini_logger.warning("📦 Go недоступен. AI результаты сохранены оффлайн: %s", offline_path)

        gemini_logger.info(
            "✅ Синхронная обработка завершена. Отправлено в БД: %d/%d",
            successful_sends,
            len([r for r in results if r.get("status") == "success"]),
        )
        return True

    except Exception as fallback_error:
        gemini_logger.error("❌ Ошибка синхронной обработки: %s", fallback_error)
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
    Получает статус AI обработки для тендера (через Redis-интеграцию Gemini).
    """
    try:
        integration = GeminiIntegration.from_redis_config(redis_config or {})
    except Exception:
        return {"error": "Redis недоступен или неверная конфигурация"}

    return integration.get_processing_status(tender_id, lot_ids)


def _import_full_tender_via_go(processed_data: dict) -> tuple[str, dict[str, int]]:
    """
    Шлёт json_1 в Go `/api/v1/import-tender`, возвращает (db_id, lot_ids_map).
    Использует Idempotency-Key для предотвращения дублирования при повторных запросах.
    Бросает исключение при ошибке.
    """
    go_url = os.getenv("GO_SERVER_API_ENDPOINT")
    api_key = os.getenv("GO_SERVER_API_KEY")
    if not go_url:
        raise RuntimeError("GO_SERVER_API_ENDPOINT не настроен")

    base = go_url.rstrip("/")
    # Поддержка как полного пути, так и базового /api/v1
    if base.endswith("/import-tender"):
        url = base
    else:
        url = f"{base}/import-tender"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Добавляем Idempotency-Key для предотвращения дублирования при retry
    try:
        import hashlib
        import json as _json
        
        # Создаем стабильный хеш на основе содержимого данных
        idem_key = hashlib.sha256(
            _json.dumps(processed_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        headers["Idempotency-Key"] = idem_key
        log.debug(f"Idempotency-Key: {idem_key[:16]}...")
    except Exception:
        log.warning("⚠️ Не удалось вычислить Idempotency-Key; продолжаю без него", exc_info=True)

    timeout = float(os.getenv("GO_HTTP_TIMEOUT", "60"))

    try:
        resp = requests.post(
            url,
            json=processed_data,
            headers=headers,
            timeout=(5, timeout),
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Go import network error: {e}") from e
    if resp.status_code >= 400:
        raise RuntimeError(f"Go import failed: {resp.status_code} {resp.text}")

    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"Go import: не-JSON ответ: {resp.text[:500]}")

    # Проверка и приведение db_id
    db_id_val = data.get("db_id")
    if not db_id_val:
        raise RuntimeError("Go import: empty db_id")
    db_id = str(db_id_val)

    # Приведение lot_ids
    raw_lots = data.get("lots_id") or {}
    lots_map = {}
    for k, v in raw_lots.items():
        try:
            lots_map[str(k)] = int(v)
        except (TypeError, ValueError):
            log.warning("Некорректный lot_id для %r: %r", k, v)

    return db_id, lots_map


def main():
    """Консольный интерфейс для запуска обработки с Gemini"""
    parser = argparse.ArgumentParser(description="Обработка тендеров с Gemini AI")

    subparsers = parser.add_subparsers(dest="command", help="Команды")

    # Команда обработки файла
    process_parser = subparsers.add_parser("process", help="Обработать XLSX файл")
    process_parser.add_argument("xlsx_file", help="Путь к XLSX файлу")
    process_parser.add_argument("--ai", action="store_true", help="Включить AI обработку")
    # Back-compat + новый флаг
    process_parser.add_argument(
        "--async", dest="async_mode", action="store_true", help="Асинхронная обработка (DEPRECATED, use --async-mode)"
    )
    process_parser.add_argument("--async-mode", dest="async_mode", action="store_true", help="Асинхронная обработка")
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

    # Настройка логирования только в CLI-режиме (не ломаем конфиг сервиса/воркера)
    log_level = os.getenv("LOG_LEVEL", "INFO").upper() if not args.verbose else "DEBUG"
    gemini_log_level = os.getenv("GEMINI_LOG_LEVEL", "INFO").upper() if not args.verbose else "DEBUG"

    logging.getLogger().setLevel(getattr(logging, log_level, logging.INFO))
    logging.getLogger("app").setLevel(getattr(logging, log_level, logging.INFO))
    get_gemini_logger().setLevel(getattr(logging, gemini_log_level, logging.INFO))

    # Формат логов
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
                async_processing=getattr(args, "async_mode", False),
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
