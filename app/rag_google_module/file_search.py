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

        # Apply retry decorator once (not per-call) for search API requests
        self._execute_search_request = retry_on_server_error(max_attempts=self.config.max_retries)(
            self._execute_search_request
        )

        self.logger.info(
            f"FileSearchClient инициализирован. Store ID: {self.config.store_id}, " f"Model: {self.config.model_name}"
        )

    async def initialize_store(self):
        """Проверяет наличие 'File Search store' или создает новый."""
        self.logger.info(f"Инициализация File Search Store (display_name: '{self.config.store_display_name}')...")

        async with self.client_manager.get_client() as client:
            try:
                await self._find_or_create_store(client)
            except google_exceptions.PermissionDenied as e:
                self.logger.critical("КРИТИЧЕСКАЯ ОШИБКА (403): У API-ключа нет прав. " f"Детали: {e}")
                raise
            except Exception as e:
                self.logger.critical(f"Ошибка инициализации Store: {e}")
                raise

    async def _find_or_create_store(self, client):
        """Find existing store or create new one (prefer store_id over display_name)."""
        self.logger.debug("Проверяем существующие Store...")
        stores_pager = await client.file_search_stores.list()

        # Собираем совпадения по id и display_name
        match_by_id = None
        matches_by_name = []

        async for store in stores_pager:
            if self.config.store_id and store.name.split("/")[-1] == self.config.store_id:
                match_by_id = store
                break
            if store.display_name == self.config.store_display_name:
                matches_by_name.append(store)

        # Предпочитаем совпадение по id
        if match_by_id:
            self.logger.info(f"✓ Найден Store по ID: '{match_by_id.display_name}' ({match_by_id.name})")
            self._store_name = match_by_id.name
            return

        if matches_by_name:
            if len(matches_by_name) > 1:
                names = [s.name for s in matches_by_name]
                self.logger.warning(
                    f"Найдено {len(matches_by_name)} Store с display_name "
                    f"'{self.config.store_display_name}': {names}. Используем первый."
                )
            chosen = matches_by_name[0]
            self.logger.info(f"✓ Найден Store: '{chosen.display_name}' ({chosen.name})")
            self._store_name = chosen.name
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
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as temp_f:
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

    async def search(self, query: str, max_results: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        """Выполняет RAG-поиск по корпусу.

        Args:
            query: Поисковый запрос.
            max_results: Максимальное количество результатов (по умолчанию из RagConfig).
        """
        if not self._store_name:
            raise RuntimeError("Store не инициализирован. Вызовите initialize_store().")

        self.logger.debug(f"RAG-поиск: {query[:50]}...")

        limit = max_results or self.config.max_search_results
        system_prompt = self._build_search_prompt(query, max_results=limit)

        response = await self._execute_search_request(system_prompt)

        try:
            response_text = response.text or ""
        except (ValueError, AttributeError):
            self.logger.warning("Модель не вернула текст для запроса: %s", query[:50])
            response_text = ""

        results = self.response_parser.parse_search_results(response_text)

        if not results:
            self.logger.warning(f"Нет результатов для: {query[:50]}...")
        else:
            self.logger.info(f"Найдено {len(results)} совпадений.")

        return results

    async def _execute_search_request(self, system_prompt: str):
        """Execute a single search request against the model (retry-decorated in __init__)."""
        async with self.client_manager.get_client() as client:
            return await client.models.generate_content(
                model=self.config.model_name,
                contents=[system_prompt],
                config=types.GenerateContentConfig(
                    tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[self._store_name]))],
                ),
            )

    def _build_search_prompt(self, query: str, *, max_results: int = 3) -> str:
        """Build search prompt for model."""
        return f"""
Ты — поисковая система по каталогу строительных работ.
Используй File Search tool для поиска в прикрепленном корпусе.
Найди до {max_results} самых релевантных строк для запроса: "{query}"

Верни ТОЛЬКО JSON-массив (максимум {max_results} элементов):
[
    {{"catalog_id": 123, "score": 0.95}},
    {{"catalog_id": 456, "score": 0.80}}
]

Если ничего не найдено, верни пустой список [].
"""
