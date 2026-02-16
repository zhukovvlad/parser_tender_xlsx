# app/go_module/sync_wrapper.py

"""
Синхронные обертки для асинхронного GoApiClient.

Назначение:
-----------
Используются в синхронном коде для вызова асинхронных методов GoApiClient:
- parse_with_gemini.py: Основной модуль парсинга тендеров
- app/workers/gemini/tasks.py: Celery задачи для AI обработки

Архитектура:
------------
Каждая функция:
1. Определяет внутреннюю async функцию
2. Инициализирует GoApiClient (создается новый для каждого вызова)
3. Выполняет асинхронный вызов Go API
4. Закрывает HTTP соединения автоматически (через context manager в GoApiClient)
5. Возвращает результат через run_async()

Управление Event Loop:
---------------------
Используется утилита run_async() из app.utils.async_runner, которая:
- Если event loop НЕ запущен → использует asyncio.run()
- Если event loop УЖЕ запущен → создает отдельный поток с новым loop

Это критично для Celery воркеров, где может быть активный event loop.

Используемые функции:
--------------------
1. import_tender_sync():
   - Импортирует полный тендер с лотами в Go БД (Процесс 1)
   - Триггерит индексацию новых позиций при необходимости
   - Используется: parse_with_gemini.py

2. update_lot_ai_results_sync():
   - Обновляет AI-результаты для конкретного лота (Процесс 1)
   - Сохраняет категорию, смету, таблицы работ и другие данные от Gemini
   - Используется: workers/gemini/tasks.py, parse_with_gemini.py

Обработка ошибок:
----------------
- Все исключения логируются с полным контекстом
- Пробрасываются как RuntimeError для retry в Celery
- Ошибки индексации не прерывают импорт тендера

Производительность:
------------------
- Каждый вызов создает новый HTTP клиент (httpx.AsyncClient)
- Клиенты автоматически закрываются через async context manager
- Нет утечек соединений или памяти
- Подходит для редких вызовов (1-2 раза на тендер)

Будущие оптимизации:
-------------------
- Миграция на async Celery tasks для нативной поддержки async/await
- Connection pooling для частых запросов
- Batch операции для множественных обновлений
"""

import logging
from typing import Any, Dict, Tuple

from app.utils.async_runner import run_async

from .go_client import GoApiClient

log = logging.getLogger(__name__)


def import_tender_sync(tender_data: Dict[str, Any]) -> Tuple[str, Dict[str, int]]:
    """
    Синхронная обертка для GoApiClient.import_full_tender().

    Отправляет полный JSON тендера на Go-сервер для регистрации в БД (Процесс 1).
    При наличии новых позиций автоматически триггерит задачу индексации.

    Workflow:
    ---------
    1. Отправляет tender_data в Go API (/import-tender)
    2. Go создает записи: tenders, lots, position_items
    3. Получает tender_db_id и маппинг lot_ids
    4. Проверяет флаг new_catalog_items_pending
    5. Если есть новые позиции → запускает run_indexing_task.delay()

    Args:
        tender_data: Полный JSON тендера, содержащий:
            - tender_id: ID в ETP системе
            - lots: список лотов с позициями
            - metadata: дополнительные данные (заказчик, сроки и т.д.)

    Returns:
        Tuple[str, Dict[str, int]]:
            - tender_db_id: Database ID созданного тендера (строка)
            - lot_ids_map: {external_lot_id: db_lot_id} маппинг
              Например: {"lot_1": 42, "lot_2": 43}

    Raises:
        RuntimeError: При ошибках сети, таймаутах или проблемах Go сервера
        ValueError: Если Go вернул некорректный ответ (отсутствует tender_db_id)

    Example:
        >>> data = {"tender_id": "123", "lots": [...]}
        >>> tender_id, lots_map = import_tender_sync(data)
        >>> print(f"Created tender {tender_id}, lots: {lots_map}")

    Note:
        - Используется увеличенный таймаут (600s) для больших тендеров
        - Ошибки индексации не прерывают импорт
        - Запускает Celery задачу индексации асинхронно
    """

    async def _async_import():
        client = GoApiClient()
        log.debug("Синхронная обертка: импорт тендера через GoApiClient")
        response = await client.import_full_tender(tender_data)

        # Валидация ответа
        if not response:
            raise ValueError("Пустой ответ от Go-сервера")

        log.debug(f"Ответ от Go-сервера: {response}")

        # Поддержка разных форматов ответа
        tender_db_id = response.get("tender_db_id") or response.get("db_id")
        if not tender_db_id:
            raise ValueError(f"Go-сервер не вернул tender_db_id. Ответ: {response}")

        lot_ids_map = response.get("lot_ids_map") or response.get("lots_id") or {}

        # (НОВОЕ) Проверяем флаг для event-driven индексации
        new_catalog_items = response.get("new_catalog_items_pending", False)

        log.info(f"✅ Тендер импортирован: db_id={tender_db_id}, лотов={len(lot_ids_map)}")

        # RAG индексация отключена (можно включить обратно, раскомментировав блок ниже)
        # # (НОВОЕ) Если есть новые pending позиции, запускаем индексацию
        # if new_catalog_items:
        #     log.info("🔔 Обнаружены новые 'pending' позиции, запускаем индексацию...")
        #     try:
        #         # Ленивый импорт чтобы избежать циклических зависимостей
        #         from app.workers.rag_catalog.tasks import run_indexing_task
        #
        #         # Запускаем задачу асинхронно
        #         run_indexing_task.delay()
        #         log.info("✅ Задача индексации отправлена в очередь Celery")
        #     except Exception as e:
        #         log.warning(f"⚠️ Не удалось запустить задачу индексации: {e}", exc_info=True)
        #         # Не прерываем импорт из-за ошибки индексации

        return str(tender_db_id), lot_ids_map

    try:
        return run_async(_async_import())
    except Exception as e:
        log.exception(f"❌ Ошибка импорта тендера: {e}")
        raise RuntimeError(f"Не удалось импортировать тендер: {e}") from e


def update_lot_ai_results_sync(
    lot_db_id: str,
    category: str,
    ai_data: Dict[str, Any],
    processed_at: str = "",
    tender_id: str = "",  # Добавлен для совместимости
) -> Dict[str, Any]:
    """
    Синхронная обертка для GoApiClient.update_lot_key_parameters().

    Обновляет AI-результаты (ключевые параметры) для лота в БД (Процесс 1).
    Сохраняет данные обработки Gemini: категорию, смету, таблицы работ и другие параметры.

    Workflow:
    ---------
    1. Формирует payload в формате lot_key_parameters
    2. Отправляет в Go API (POST /lots/{lot_db_id}/ai-results)
    3. Go обновляет поле lot_key_parameters в таблице lots
    4. Возвращает подтверждение

    Args:
        lot_db_id: Database ID лота (НЕ external_id!)
            Получается из lot_ids_map после import_tender_sync()
        category: Категория работ, определенная Gemini AI
            Например: "Мостостроение", "Котлован", "Свайные работы"
        ai_data: Словарь с результатами AI обработки:
            - cmu_table: таблица работ с позициями
            - smeta_summary: итоги по смете
            - key_metrics: ключевые метрики
            - и другие поля, специфичные для категории
        processed_at: ISO 8601 timestamp момента обработки
            Формат: "2024-12-16T14:30:00Z"
        tender_id: ID тендера в ETP (опционально, для совместимости)

    Returns:
        Dict[str, Any]: Ответ от Go сервера
            Обычно: {"status": "ok"} или {"updated": true}

    Raises:
        RuntimeError: При ошибках HTTP, таймаутах, проблемах Go сервера
        ValueError: Если lot_db_id не существует в БД

    Example:
        >>> update_lot_ai_results_sync(
        ...     lot_db_id="42",
        ...     category="Мостостроение",
        ...     ai_data={"cmu_table": [...], "smeta_summary": {...}},
        ...     processed_at="2024-12-16T14:30:00Z"
        ... )

    Note:
        - Вызывается после успешной обработки лота Gemini AI
        - Используется в Celery задачах (workers/gemini/tasks.py)
        - Может быть вызвана повторно для обновления данных
    """

    async def _async_update():
        client = GoApiClient()
        log.debug(f"Синхронная обертка: обновление AI результатов для лота {lot_db_id}")

        # Формируем payload в формате, который ожидает Go-сервер (старый формат)
        ai_payload = {
            "lot_key_parameters": {
                "ai": {
                    "source": "gemini",
                    "category": category,
                    "data": ai_data or {},
                    "processed_at": processed_at,
                }
            }
        }

        # Добавляем IDs если они предоставлены (для совместимости)
        if tender_id:
            ai_payload["tender_id"] = str(tender_id)
        ai_payload["lot_id"] = str(lot_db_id)

        response = await client.update_lot_key_parameters(lot_db_id, ai_payload)

        log.info(f"✅ AI результаты обновлены для лота {lot_db_id}")
        return response

    try:
        return run_async(_async_update())
    except Exception as e:
        log.exception(f"❌ Ошибка обновления AI результатов для лота {lot_db_id}: {e}")
        raise RuntimeError(f"Не удалось обновить AI результаты: {e}") from e
