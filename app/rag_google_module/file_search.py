# app/rag_google_module/file_search.py

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List, Optional

from google import genai
from google.api_core import exceptions as google_exceptions
from google.genai import types

from .client_manager import ClientManager
from .config import RagConfig
from .logger import get_rag_logger
from .response_parser import SearchResponseParser
from .retry import retry_on_server_error


class FileSearchClient:
    """
    Асинхронный клиент для Google File Search API.
    Использует "корпусный" RAG (File Search store).
    """

    def __init__(self, config: Optional[RagConfig] = None):
        self.config = config or RagConfig.from_env()
        self.client_manager = ClientManager(self.config.api_key)
        self.response_parser = SearchResponseParser()
        self.logger = get_rag_logger("file_search_client")
        
        self._store_name = ""
        
        self.logger.info(
            f"FileSearchClient инициализирован. Store ID: {self.config.store_id}, "
            f"Model: {self.config.model_name}"
        )

    async def initialize_store(self):
        """Проверяет наличие 'File Search store' или создает новый."""
        self.logger.info(
            f"Инициализация File Search Store (display_name: '{self.config.store_display_name}')..."
        )

        async with self.client_manager.get_client() as client:
            try:
                await self._find_or_create_store(client)
            except google_exceptions.PermissionDenied as e:
                self.logger.critical(
                    "КРИТИЧЕСКАЯ ОШИБКА (403): У API-ключа нет прав. "
                    f"Детали: {e}"
                )
                raise
            except Exception as e:
                self.logger.critical(f"Ошибка инициализации Store: {e}")
                raise

    async def _find_or_create_store(self, client):
        """Find existing store or create new one."""
        self.logger.debug("Проверяем существующие Store...")
        stores_pager = await client.file_search_stores.list()

        async for store in stores_pager:
            if store.display_name == self.config.store_display_name:
                self.logger.info(f"✓ Найден Store: '{store.display_name}' ({store.name})")
                self._store_name = store.name
                return

        self.logger.info("Создаем новый Store...")
        store = await client.file_search_stores.create(
            config={"display_name": self.config.store_display_name},
        )
        self.logger.info(f"✓ Store создан: '{store.display_name}' ({store.name})")
        self._store_name = store.name

    async def add_batch_to_store(self, records: List[Dict]):
        """Загружает батч в File Search Store."""
        if not self._store_name:
            raise RuntimeError("Store не инициализирован. Вызовите initialize_store().")
        if not records:
            self.logger.warning("Пустой батч.")
            return

        temp_file_path = self._create_temp_json_file(records)
        
        async with self.client_manager.get_client() as client:
            try:
                await self._upload_and_wait(client, temp_file_path, len(records))
            finally:
                self._cleanup_temp_file(temp_file_path)

    def _create_temp_json_file(self, data: List[Dict]) -> str:
        """Create temporary JSON file."""
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".json", encoding="utf-8"
        ) as temp_f:
            json.dump(data, temp_f, ensure_ascii=False, indent=2)
            return temp_f.name

    async def _upload_and_wait(self, client, file_path: str, count: int):
        """Upload file and wait for indexing."""
        self.logger.debug(f"Загрузка {count} записей в Store...")
        
        operation = await client.file_search_stores.upload_to_file_search_store(
            file=file_path,
            file_search_store_name=self._store_name,
            config={
                "chunking_config": {
                    "white_space_config": {
                        "max_tokens_per_chunk": self.config.max_tokens_per_chunk,
                        "max_overlap_tokens": self.config.max_overlap_tokens,
                    }
                }
            },
        )

        await self._wait_for_operation(operation, client)
        self.logger.info(f"Батч ({count} записей) добавлен.")

    def _cleanup_temp_file(self, file_path: str):
        """Remove temporary file."""
        if os.path.exists(file_path):
            os.remove(file_path)
            self.logger.debug(f"Временный файл удален: {file_path}")

    async def _wait_for_operation(self, operation, client):
        """Ожидает завершения LRO."""
        timeout_iterations = max(1, self.config.operation_timeout // 5)
        
        for _ in range(timeout_iterations):
            updated_operation = await client.operations.get(operation)
            if updated_operation.done:
                if updated_operation.error:
                    raise RuntimeError(f"Operation failed: {updated_operation.error}")
                return
            await asyncio.sleep(5)
        
        raise TimeoutError(f"Таймаут операции {operation.name}")

    @retry_on_server_error(max_attempts=3)
    async def search(self, query: str) -> Optional[List[Dict[str, Any]]]:
        """Выполняет RAG-поиск по корпусу."""
        if not self._store_name:
            raise RuntimeError("Store не инициализирован. Вызовите initialize_store().")

        self.logger.debug(f"RAG-поиск: {query[:50]}...")

        system_prompt = self._build_search_prompt(query)

        async with self.client_manager.get_client() as client:
            response = await client.models.generate_content(
                model=self.config.model_name,
                contents=[system_prompt],
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=[self._store_name]
                            )
                        )
                    ],
                ),
            )

            results = self.response_parser.parse_search_results(response.text)
            
            if not results:
                self.logger.warning(f"Нет результатов для: {query[:50]}...")
            else:
                self.logger.info(f"Найдено {len(results)} совпадений.")
            
            return results

    def _build_search_prompt(self, query: str) -> str:
        """Build search prompt for model."""
        return f"""
Ты — поисковая система по каталогу строительных работ.
Используй File Search tool для поиска в прикрепленном корпусе.
Найди до ТРЕХ (3) самых релевантных строк для запроса: "{query}"

Верни ТОЛЬКО JSON-массив:
[
    {{"catalog_id": 123, "score": 0.95}},
    {{"catalog_id": 456, "score": 0.80}}
]

Если ничего не найдено, верни пустой список [].
"""
