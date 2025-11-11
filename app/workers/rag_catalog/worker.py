# -*- coding: utf-8 -*-
# app/workers/rag_catalog/worker.py

import os
from .logger import get_rag_logger
from ...go_module.go_client import GoApiClient
from ...rag_google_module.file_search import FileSearchClient

# Пороги схожести (вынести в .env)
MATCHING_THRESHOLD = float(os.getenv("RAG_MATCHING_THRESHOLD", "0.95"))
SUGGEST_THRESHOLD = float(os.getenv("RAG_SUGGEST_THRESHOLD", "0.98"))

class RagWorker:
    """
    Асинхронная бизнес-логика для RAG-воркера.
    Использует GoApiClient для работы с БД и FileSearchClient для AI-поиска.
    """

    def __init__(self):
        self.logger = get_rag_logger("worker")
        self.go_client = GoApiClient()
        self.file_search = FileSearchClient()
        self.is_catalog_initialized = False

    async def initialize_catalog_cache(self):
        """
        "Прогревает" FileSearchClient, загружая в него
        полный каталог из Go-бэкенда.
        """
        self.logger.info("Инициализация кэша каталога RAG...")
        try:
            # 1. Получаем ВЕСЬ каталог из Go
            # (Предполагаем, что get_unindexed_items с limit=0 вернет все)
            all_items = await self.go_client.get_unindexed_catalog_items(limit=0)
            
            if not all_items:
                self.logger.warning("Каталог в Go-БД пуст. RAG-поиск не будет работать.")
                self.is_catalog_initialized = False
                return

            # 2. Готовим JSONL
            jsonl_data = [
                {"catalog_id": item["catalog_id"], "context_string": item["rich_context_string"]}
                for item in all_items
            ]

            # 3. "Скармливаем" его FileSearchClient
            await self.file_search.initialize_catalog(jsonl_data) #
            
            # 4. (Опционально) Сообщаем Go, что все проиндексировано
            indexed_ids = [item["catalog_id"] for item in all_items]
            await self.go_client.post_catalog_indexed(indexed_ids) #

            self.is_catalog_initialized = True
            self.logger.info(f"Кэш каталога RAG успешно инициализирован ({len(jsonl_data)} записей).")

        except Exception as e:
            self.is_catalog_initialized = False
            self.logger.critical(f"Не удалось инициализировать кэш каталога RAG: {e}", exc_info=True)

    async def run_matcher(self) -> dict:
        """
        Выполняет Процесс 2: Сопоставление NULL-позиций.
        """
        if not self.is_catalog_initialized:
            raise RuntimeError("Каталог RAG не инициализирован. Процесс 2 не может быть запущен.")

        self.logger.info("Процесс 2: Поиск необработанных position_items...")
        
        # 1. Получаем 'NULL'-позиции от Go
        unmatched_items = await self.go_client.get_unmatched_positions(limit=100)
        
        if not unmatched_items:
            return {"status": "success", "matched": 0, "processed": 0, "message": "Необработанные позиции не найдены."}

        self.logger.info(f"Найдено {len(unmatched_items)} позиций для сопоставления.")
        matched_count = 0
        
        for item in unmatched_items:
            # item = { "position_item_id": 9999, "hash": "...", "rich_context_string": "..." }
            try:
                # 2. Ищем в Google File Search
                search_query = item["rich_context_string"]
                search_result = await self.file_search.search(search_query) #
                
                # 3. Анализируем результат
                if not search_result or "catalog_id" not in search_result:
                    self.logger.warning(f"Не найдено совпадение для item {item['position_item_id']}")
                    continue
                    
                # (Здесь можно добавить логику проверки схожести, 
                # если File Search вернет score)
                matched_catalog_id = search_result["catalog_id"]
                
                self.logger.info(f"Найдено совпадение! Item {item['position_item_id']} -> Catalog {matched_catalog_id}")

                # 4. Отправляем результат в Go
                await self.go_client.post_position_match({ #
                    "position_item_id": item["position_item_id"],
                    "catalog_position_id": matched_catalog_id,
                    "hash": item["hash"]
                })
                matched_count += 1
                
            except Exception as e:
                self.logger.error(f"Ошибка при обработке item {item.get('position_item_id')}: {e}")

        return {"status": "success", "processed": len(unmatched_items), "matched": matched_count}

    async def run_cleaner(self, force_reindex: bool = False) -> dict:
        """
        Выполняет Процесс 3: Очистка и дедупликация каталога.
        """
        # --- Часть А: Пере-индексация ---
        # Если force_reindex=True, мы полностью перестраиваем индекс
        if force_reindex:
            self.logger.warning("Принудительная полная пере-индексация каталога RAG...")
            await self.initialize_catalog_cache()
        else:
            # (В будущем) Здесь можно добавить логику частичной 
            # до-индексации (если FileSearch это позволит)
            pass

        # --- Часть Б: Поиск дубликатов ---
        self.logger.info("Процесс 3 (Б): Поиск дубликатов в каталоге...")
        
        # (Логика поиска дубликатов)
        # Эта логика сложна: она должна итерировать по всему каталогу
        # и для каждого элемента искать похожие на него.
        # ...
        # (для item in await self.go_client.get_unindexed_catalog_items(limit=0))
        #   (search_result = await self.file_search.search(item["rich_context_string"]))
        #   (if search_result["catalog_id"] != item["catalog_id"])
        #     (await self.go_client.post_suggest_merge(...))
        
        suggested_count = 0 # Заглушка
        self.logger.info(f"Процесс 3 (Б): Завершено. Предложено слияний: {suggested_count}")

        return {"status": "success", "reindexed": force_reindex, "suggested_merges": suggested_count}