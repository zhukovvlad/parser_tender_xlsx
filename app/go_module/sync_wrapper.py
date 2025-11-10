# app/go_module/sync_wrapper.py

"""
Синхронные обертки для асинхронного GoApiClient.

Используются в синхронном коде (parse_with_gemini.py, Celery tasks)
для вызова асинхронных методов GoApiClient через asyncio.run().

Каждая функция:
1. Создает event loop через asyncio.run()
2. Инициализирует GoApiClient
3. Выполняет асинхронный вызов
4. Закрывает клиент
5. Возвращает результат

ВАЖНО: Эти обертки создают новый event loop для каждого вызова,
что безопасно для синхронного кода, но неэффективно для множественных
вызовов. Для оптимизации рассмотрите переход на async/await в воркерах.
"""

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from .go_client import GoApiClient

log = logging.getLogger(__name__)


def import_tender_sync(tender_data: Dict[str, Any]) -> Tuple[str, Dict[str, int]]:
    """
    Синхронная обертка для GoApiClient.import_full_tender().
    
    Отправляет полный JSON тендера на Go-сервер для регистрации в БД.
    
    Args:
        tender_data: Словарь с полными данными тендера
        
    Returns:
        Tuple[str, Dict[str, int]]: (tender_db_id, lot_ids_map)
        - tender_db_id: ID тендера из БД (строка)
        - lot_ids_map: Словарь {lot_key: lot_db_id}
        
    Raises:
        RuntimeError: При ошибках сети или сервера
        ValueError: При некорректном ответе от сервера
    """
    async def _async_import():
        client = GoApiClient()
        try:
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
            
            log.info(f"✅ Тендер импортирован: db_id={tender_db_id}, лотов={len(lot_ids_map)}")
            return str(tender_db_id), lot_ids_map
            
        finally:
            await client.close()
    
    try:
        return asyncio.run(_async_import())
    except Exception as e:
        log.error(f"❌ Ошибка импорта тендера: {e}")
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
    
    Обновляет AI-результаты для лота в БД.
    
    Args:
        lot_db_id: ID лота в БД
        category: Категория тендера (определенная AI)
        ai_data: Словарь с AI-результатами
        processed_at: ISO timestamp обработки (опционально)
        tender_id: ID тендера (опционально, для совместимости)
        
    Returns:
        Dict: Ответ от сервера (обычно {"status": "ok"})
        
    Raises:
        RuntimeError: При ошибках сети или сервера
    """
    async def _async_update():
        client = GoApiClient()
        try:
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
            
        finally:
            await client.close()
    
    try:
        return asyncio.run(_async_update())
    except Exception as e:
        log.error(f"❌ Ошибка обновления AI результатов для лота {lot_db_id}: {e}")
        raise RuntimeError(f"Не удалось обновить AI результаты: {e}") from e


def import_tender_with_fallback(
    tender_data: Dict[str, Any],
    source_filename: str = "",
) -> Tuple[bool, Optional[str], Optional[Dict[str, int]]]:
    """
    Синхронная обертка с поддержкой fallback режима (временные ID).
    
    Расширенная версия import_tender_sync() с логикой временных ID
    для совместимости со старым register_tender_in_go().
    
    Args:
        tender_data: Словарь с данными тендера
        source_filename: Имя исходного файла (для генерации temp ID)
        
    Returns:
        Tuple[bool, Optional[str], Optional[Dict]]:
        - success: True если успешно (даже с temp ID)
        - tender_db_id: ID тендера или temp ID
        - lot_ids_map: Словарь ID лотов или temp ID
        
    Note:
        Эта функция НЕ генерирует временные ID при сбое, а просто
        пробрасывает исключение. Fallback логика должна быть реализована
        на уровне вызывающего кода.
    """
    try:
        tender_db_id, lot_ids_map = import_tender_sync(tender_data)
        return True, tender_db_id, lot_ids_map
    except Exception as e:
        log.error(f"❌ Импорт тендера не удался: {e}")
        # Вместо генерации temp ID, пробрасываем ошибку
        # Вызывающий код решит, нужен ли fallback
        raise
