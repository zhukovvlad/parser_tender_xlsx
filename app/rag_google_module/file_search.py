# app/rag_google_module/file_search.py

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List, Optional

from google import genai
from google.api_core import exceptions as google_exceptions
from google.genai import types

from .logger import get_rag_logger


class FileSearchClient:
    """
    Асинхронный клиент для Google File Search API.
    (ИЗМЕНЕНИЕ) Использует "корпусный" RAG (File Search store).
    """

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY не установлен в .env")

        self.client = genai.Client(api_key=self.api_key)
        self.logger = get_rag_logger("file_search_client")

        # Наш "индекс" - это ID постоянного хранилища (корпуса)
        self.store_id = os.getenv("GOOGLE_RAG_STORE_ID", "rag-catalog-store")
        self._store_name = ""  # Будет заполнен при инициализации

        # Модель, которую мы будем использовать для RAG
        self._model_name = os.getenv("GOOGLE_RAG_MODEL", "gemini-2.5-flash")

        self.logger.info(
            f"FileSearchClient (RAG v4, corpus-based) инициализирован."
            f" Store ID: {self.store_id}, Model: {self._model_name}"
        )

    async def initialize_store(self):
        """
        Проверяет наличие 'File Search store' или создает новый.
        Сначала ищет существующий по display_name, если не найден - создает новый.
        """
        self.logger.info(f"Инициализация File Search Store (display_name: 'Tenders Catalog Store')...")
        
        try:
            # --- ШАГАН 1: Пытаемся найти существующий Store ---
            self.logger.debug("Проверяем существующие Store...")
            stores_pager = await self.client.aio.file_search_stores.list()
            
            # Ищем Store с нужным display_name
            async for store in stores_pager:
                if store.display_name == "Tenders Catalog Store":
                    self.logger.info(f"✓ Найден существующий Store: '{store.display_name}' (name: {store.name})")
                    self._store_name = store.name
                    self.logger.info(f"✓ Переиспользуем существующий Store вместо создания нового")
                    return
            
            # --- ШАГАН 2: Если не нашли - создаем новый ---
            self.logger.info("Существующий Store не найден. Создаем новый...")
            store = await self.client.aio.file_search_stores.create(
                config={"display_name": "Tenders Catalog Store"},
            )
            self.logger.info(f"✓ Новый Store '{store.display_name}' создан. Store name: {store.name}")
            self._store_name = store.name

        except google_exceptions.PermissionDenied as e:
            self.logger.critical(
                f"КРИТИЧЕСКАЯ ОШИБКА (403): У API-ключа нет прав (Permission Denied) "
                f"на создание или получение Store. "
                f"Проверьте права ключа в Google AI Studio."
            )
            self.logger.critical(f"Детали ошибки: {e}")
            raise

        except Exception as e:
            self.logger.critical(f"Неизвестная ошибка инициализации File Search Store: {e}")
            raise

    async def add_batch_to_store(self, jsonl_data: List[Dict]):
        """
        (НОВЫЙ) Загружает ОДИН батч в File Search Store.
        Использует JSON формат для простоты и совместимости.
        """
        if not self._store_name:
            raise RuntimeError("File Search Store не инициализирован. Вызовите initialize_store().")
        if not jsonl_data:
            self.logger.warning("add_batch_to_store получил пустой список.")
            return

        # Создаем временный JSON файл
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as temp_f:
            # Записываем как массив JSON объектов
            json.dump(jsonl_data, temp_f, ensure_ascii=False, indent=2)
            temp_file_path = temp_f.name

        self.logger.debug(f"Временный JSON файл ({len(jsonl_data)} записей) создан. Загружаю в Store...")
        try:
            # Загружаем напрямую в File Search Store
            # JSON автоматически распознается по расширению .json
            operation = await self.client.aio.file_search_stores.upload_to_file_search_store(
                file=temp_file_path,
                file_search_store_name=self._store_name,
                config={
                    "chunking_config": {
                        "white_space_config": {
                            "max_tokens_per_chunk": 512,
                            "max_overlap_tokens": 0,
                        }
                    }
                },
            )

            # Ожидаем завершения индексации этого батча
            # API возвращает объект операции, передаем его напрямую
            operation_name = operation.name if hasattr(operation, 'name') else str(operation)
            self.logger.debug(f"Ожидание индексации батча (Operation: {operation_name})...")
            await self._wait_for_operation(operation)
            self.logger.info(f"Батч ({len(jsonl_data)} записей) успешно добавлен в File Search Store.")

        except Exception as e:
            # В случае ошибки удаляем временный файл
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
            raise
        finally:
            # Всегда удаляем временный файл после загрузки
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)
                self.logger.debug(f"Временный файл удален: {temp_file_path}")

    async def _wait_for_operation(self, operation, timeout: int = 600):
        """Ожидает завершения LRO (Long-Running Operation)."""
        for _ in range(timeout // 5):
            # Обновляем состояние операции
            updated_operation = await self.client.aio.operations.get(operation)
            if updated_operation.done:
                if updated_operation.error:
                    self.logger.error(f"Ошибка операции {operation.name if hasattr(operation, 'name') else operation}: {updated_operation.error}")
                    raise RuntimeError(f"Operation failed: {updated_operation.error}")
                return
            await asyncio.sleep(5)
        raise TimeoutError(f"Таймаут ожидания операции {operation.name if hasattr(operation, 'name') else operation}")

    async def search(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """
        (НОВЫЙ) Выполняет RAG-поиск по КОРПУСУ.
        Возвращает список (топ-3) релевантных результатов.
        """
        if not self._store_name:
            self.logger.error("Каталог не инициализирован. Вызовите initialize_store() перед поиском.")
            raise RuntimeError("Catalog not initialized")

        self.logger.debug(f"RAG-поиск (corpus-based). Запрос: {query[:50]}...")

        # Системный промпт, который заставляет модель искать и возвращать JSON
        system_prompt = f"""
        Ты — поисковая система по каталогу строительных работ.
        Используй File Search tool для поиска в прикрепленном корпусе.
        Твоя задача — найти до ТРЕХ (3) самых релевантных строк, которые
        наиболее точно соответствуют запросу пользователя.

        ЗАПРОС: "{query}"

        Проанализируй результаты поиска и верни ТОЛЬКО JSON-массив (список),
        где каждый элемент содержит:
        - "catalog_id" (из метаданных найденного чанка)
        - "score" (твоя оценка схожести от 0.0 до 1.0)

        Пример ответа:
        [
            {{"catalog_id": 123, "score": 0.95}},
            {{"catalog_id": 456, "score": 0.80}}
        ]

        Если ничего не найдено, верни пустой список [].
        """

        try:
            # (ИЗМЕНЕНИЕ) Главный вызов!
            response = await self.client.aio.models.generate_content(
                model=self._model_name,
                contents=[system_prompt],  # Передаем только промпт
                # Указываем наш корпус как инструмент
                config=types.GenerateContentConfig(
                    tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[self._store_name]))],
                    # Просим модель вернуть чистый JSON
                    response_mime_type="application/json",
                ),
            )

            # Парсим JSON-ответ от модели
            result_json = json.loads(response.text)

            # Ожидаем список, но если модель вернула один объект - оборачиваем
            if isinstance(result_json, dict):
                result_json = [result_json]

            if not result_json:
                self.logger.warning(f"RAG-поиск не дал релевантных JSON-результатов для: {query[:50]}...")
                return []

            valid_results = []
            for item in result_json:
                if "catalog_id" in item:
                    # Добавляем 'score' по умолчанию, если модель его не вернула
                    if "score" not in item:
                        item["score"] = 0.0  # Безопасный дефолт
                    valid_results.append(item)

            self.logger.info(f"RAG-поиск нашел {len(valid_results)} совпадений.")
            return valid_results

        except json.JSONDecodeError as e:
            # Пустой ответ от модели - нормальная ситуация, когда Store пустой или нет совпадений
            self.logger.debug(f"RAG-поиск: пустой ответ от модели (Store может быть пустым). Query: {query[:50]}...")
            return []
        except Exception as e:
            self.logger.error(f"Ошибка RAG-поиска (corpus-based): {e}")
            return []
