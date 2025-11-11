# app/rag_google_module/file_search.py

import os
import json
import tempfile
import asyncio
from typing import List, Dict, Any, Optional

from google import genai
from google.api_core import exceptions as google_exceptions

from .logger import get_rag_logger

class FileSearchClient:
    """
    Асинхронный клиент для Google File Search API.
    Использует НОВЫЙ "бескорпусный" RAG-пайплайн:
    1. Загружает файл.
    2. Передает файл и запрос напрямую в model.generate_content().
    """

    def __init__(self):
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY не установлен в .env")
        
        self.client = genai.Client(api_key=self.api_key)
        self.logger = get_rag_logger("file_search_client")
        
        # Наш "индекс" - это просто объект загруженного файла
        self._catalog_file = None 
        # Модель, которую мы будем использовать для RAG (конфигурируемая через env)
        self._model_name = os.getenv("GOOGLE_RAG_MODEL", "gemini-1.5-pro-latest")
        
        self.logger.info(f"FileSearchClient (RAG v3, model-based) инициализирован с моделью {self._model_name}.")

    async def _upload_catalog(self, jsonl_data: List[Dict]) -> genai.types.File:
        """
        (Приватный) Загружает наш JSONL-каталог в Google Files.
        """
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix=".jsonl", encoding="utf-8") as temp_f:
            for item in jsonl_data:
                temp_f.write(json.dumps(item, ensure_ascii=False) + '\n')
            temp_file_path = temp_f.name

        self.logger.info("Временный JSONL файл каталога создан. Загружаю...")
        try:
            # Загружаем файл через aio namespace
            uploaded_file = await self.client.aio.files.upload(
                path=temp_file_path, 
                display_name="catalog_positions.jsonl"
            )
            self.logger.info(f"Каталог успешно загружен, File ID: {uploaded_file.name}")
            return uploaded_file
        finally:
            os.remove(temp_file_path)

    async def initialize_catalog(self, jsonl_data: List[Dict]):
        """
        (НОВЫЙ) Загружает и кэширует наш файл каталога.
        Это замена `get_or_create_corpus`.
        """
        self.logger.info(f"Инициализация каталога... Загружаю {len(jsonl_data)} записей.")
        self._catalog_file = await self._upload_catalog(jsonl_data)
        
        # Ожидаем, пока файл станет доступен для использования
        await self._wait_for_file_active(self._catalog_file.name)

    async def _wait_for_file_active(self, file_name: str, timeout: int = 300):
        """Ожидает, пока файл не станет ACTIVE."""
        self.logger.debug(f"Ожидание индексации файла {file_name}...")
        for _ in range(timeout // 5):
            try:
                file_obj = await self.client.aio.files.get(name=file_name)
                if file_obj.state.name == "ACTIVE":
                    self.logger.info(f"Файл {file_name} успешно проиндексирован (ACTIVE).")
                    return
                if file_obj.state.name == "FAILED":
                    self.logger.error(f"Индексация файла {file_name} провалена (FAILED).")
                    raise RuntimeError(f"File indexing failed: {file_name}")
            except google_exceptions.NotFound:
                self.logger.debug(f"Файл {file_name} еще не виден, ждем...")
            
            await asyncio.sleep(5)
            
        raise TimeoutError(f"Таймаут ожидания индексации файла {file_name}")

    async def search(self, query: str) -> Optional[Dict[str, Any]]:
        """
        (НОВЫЙ) Выполняет RAG-поиск, передавая файл и запрос в модель.
        """
        if not self._catalog_file:
            self.logger.error("Каталог не инициализирован. Вызовите initialize_catalog() перед поиском.")
            raise RuntimeError("Catalog not initialized")

        self.logger.debug(f"RAG-поиск (model-based). Запрос: {query[:50]}...")

        # Это системный промпт, который превращает модель в "поисковик"
        system_prompt = f"""
        Ты — поисковая система по каталогу строительных работ.
        Тебе предоставлен файл каталога в формате JSONL.
        Каждая строка — это одна работа с "catalog_id" и "context_string".
        Твоя задача — найти ОДНУ (1) САМУЮ релевантную строку из файла, которая
        наиболее точно соответствует запросу пользователя.

        ЗАПРОС: "{query}"

        Твой ответ ДОЛЖЕН БЫТЬ ТОЛЬКО JSON-объектом, который ты нашел в файле.
        Не добавляй НИКАКОГО пояснительного текста.
        Если ты ничего не нашел, верни пустой JSON-объект {{}}.
        """
        
        try:
            # (ИЗМЕНЕНИЕ) Главный вызов!
            # Мы передаем и файл, и промпт в contents через aio namespace.
            response = await self.client.aio.models.generate_content(
                model=self._model_name,
                contents=[self._catalog_file, system_prompt],
                # Просим модель вернуть чистый JSON
                config={"response_mime_type": "application/json"}
            )
            
            # Парсим JSON-ответ от модели
            result_json = json.loads(response.text)
            
            if not result_json or "catalog_id" not in result_json:
                self.logger.warning(f"RAG-поиск не дал релевантных результатов для: {query[:50]}...")
                return None

            self.logger.info(f"RAG-поиск нашел совпадение: catalog_id={result_json.get('catalog_id')}")
            return result_json

        except Exception as e:
            self.logger.exception(f"Ошибка RAG-поиска (model-based): {e}")
            return None