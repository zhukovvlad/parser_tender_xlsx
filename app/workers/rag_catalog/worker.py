# -*- coding: utf-8 -*-
# app/workers/rag_catalog/worker.py

import os
from typing import Any, Dict

from ...go_module.go_client import GoApiClient
from ...rag_google_module.file_search import FileSearchClient
from .logger import get_rag_logger

# Пороги схожести (вынести в .env)
MATCHING_THRESHOLD = float(os.getenv("RAG_MATCHING_THRESHOLD", "0.95"))
SUGGEST_THRESHOLD = float(os.getenv("RAG_SUGGEST_THRESHOLD", "0.98"))

# Размер батча для пагинации
CLEANER_BATCH_SIZE = int(os.getenv("RAG_CLEANER_BATCH_SIZE", "1000"))
# (ИЗМЕНЕНИЕ) Матчер теперь тоже использует пагинацию
MATCHER_BATCH_SIZE = int(os.getenv("RAG_MATCHER_BATCH_SIZE", "100"))


class RagWorker:
    """
    Асинхронная бизнес-логика для RAG-воркера.
    (ИЗМЕНЕНИЕ) Работает с "корпусным" FileSearchClient.
    """

    def __init__(self):
        self.logger = get_rag_logger("worker")
        self.go_client = GoApiClient()
        self.file_search = FileSearchClient()
        self.is_catalog_initialized = False  # (Теперь означает 'store_ready')

    async def initialize_store(self):
        """
        (НОВЫЙ) Инициализирует File Search Store при старте воркера.
        """
        self.logger.info("Инициализация RAG Worker... Проверка File Search Store...")
        try:
            await self.file_search.initialize_store()
            self.is_catalog_initialized = True
            self.logger.info("File Search Store готов. RAG Worker инициализирован.")
        except Exception as e:
            self.is_catalog_initialized = False
            self.logger.critical(f"Не удалось инициализировать File Search Store: {e}", exc_info=True)
            # Воркер не сможет работать, если Store не готов
            raise

    async def run_matcher(self) -> dict:
        """
        Выполняет Процесс 2: Сопоставление NULL-позиций.
        """
        if not self.is_catalog_initialized:
            raise RuntimeError("File Search Store не инициализирован. Процесс 2 не может быть запущен.")

        self.logger.info("Процесс 2: Поиск необработанных position_items...")

        # 1. Получаем 'NULL'-позиции от Go
        unmatched_items = await self.go_client.get_unmatched_positions(limit=MATCHER_BATCH_SIZE)

        if not unmatched_items:
            return {"status": "success", "matched": 0, "processed": 0, "message": "Необработанные позиции не найдены."}

        self.logger.info(f"Найдено {len(unmatched_items)} позиций для сопоставления.")
        matched_count = 0

        for item in unmatched_items:
            # DTO: { "position_item_id": 9999 (из position_items), "hash": "...", "rich_context_string": "..." }
            try:
                # 2. Ищем в File Search (по корпусу)
                search_query = item["rich_context_string"]
                search_results = await self.file_search.search(search_query)

                # 3. Анализируем результат
                if not search_results:
                    self.logger.warning(f"Не найдено совпадение для item {item['position_item_id']}")
                    continue

                # Берем лучший результат (первый в списке)
                best_match = search_results[0]

                if "catalog_id" not in best_match or "score" not in best_match:
                    self.logger.warning(f"Некорректный формат ответа для item {item['position_item_id']}")
                    continue

                # 4. Проверяем порог схожести
                if best_match["score"] < MATCHING_THRESHOLD:
                    self.logger.info(
                        f"Найдено совпадение (ID {best_match['catalog_id']}), "
                        f"но score ({best_match['score']}) ниже порога ({MATCHING_THRESHOLD}). Пропуск."
                    )
                    continue

                matched_catalog_id = best_match["catalog_id"]
                self.logger.info(f"Найдено совпадение! Item {item['position_item_id']} -> Catalog {matched_catalog_id}")

                # 5. Отправляем результат в Go
                await self.go_client.post_position_match(
                    {
                        "position_item_id": item["position_item_id"],
                        "catalog_position_id": matched_catalog_id,
                        "hash": item["hash"],
                    }
                )
                matched_count += 1

            except Exception as e:
                self.logger.error(f"Ошибка при обработке item {item.get('position_item_id')}: {e}")

        return {"status": "success", "processed": len(unmatched_items), "matched": matched_count}

    async def run_indexer(self) -> Dict[str, Any]:
        """
        Выполняет Процесс 3А: Индексация 'pending' позиций.
        (ПУБЛИЧНЫЙ МЕТОД) Вызывается event-driven после импорта тендера.
        """
        if not self.is_catalog_initialized:
            raise RuntimeError("File Search Store не инициализирован. Процесс 3А не может быть запущен.")

        self.logger.info("Процесс 3А: Запуск инкрементальной индексации 'pending'...")
        current_offset = 0
        total_indexed = 0
        total_batches = 0

        while True:
            self.logger.debug(f"Запрос батча {CLEANER_BATCH_SIZE} 'pending' позиций, offset={current_offset}...")

            try:
                # 1. Получаем 'pending' батч
                items_batch = await self.go_client.get_unindexed_catalog_items(
                    limit=CLEANER_BATCH_SIZE, offset=current_offset
                )
            except Exception as e:
                self.logger.error(f"Ошибка получения 'pending' батча: {e}", exc_info=True)
                break

            if not items_batch:
                self.logger.info("'Pending' батчи закончились. Индексация (Часть А) завершена.")
                break

            # 2. Готовим JSONL для RAG
            jsonl_data = []
            indexed_ids = []
            for item in items_batch:
                # DTO: { "catalog_id": 123, "rich_context_string": "..." }
                catalog_id = item["catalog_id"]
                jsonl_data.append(
                    {
                        "catalog_id": catalog_id,
                        "context_string": item["rich_context_string"],
                    }
                )
                indexed_ids.append(catalog_id)

            try:
                # 3. Добавляем батч в File Search Store
                await self.file_search.add_batch_to_store(jsonl_data)

                # 4. Сообщаем Go, что этот батч стал 'active'
                await self.go_client.post_catalog_indexed(indexed_ids)

                total_indexed += len(indexed_ids)
                total_batches += 1
                current_offset += CLEANER_BATCH_SIZE

            except Exception as e:
                self.logger.error(
                    f"Критическая ошибка при индексации батча (offset {current_offset}): {e}", exc_info=True
                )
                # Прерываем, чтобы не пытаться индексировать снова
                break

        return {"batches_processed": total_batches, "items_indexed": total_indexed}

    async def run_deduplicator(self) -> Dict[str, Any]:
        """
        Выполняет Процесс 3Б: Поиск дубликатов среди 'active' позиций.
        (ПУБЛИЧНЫЙ МЕТОД) Запускается по расписанию (ночная задача).
        """
        if not self.is_catalog_initialized:
            raise RuntimeError("File Search Store не инициализирован. Процесс 3Б не может быть запущен.")

        self.logger.info("Процесс 3Б: Запуск поиска дубликатов в 'active'...")
        current_offset = 0
        total_processed = 0
        total_suggestions = 0

        while True:
            self.logger.debug(f"Запрос батча {CLEANER_BATCH_SIZE} 'active' позиций, offset={current_offset}...")

            try:
                # 1. Получаем 'active' батч
                items_batch = await self.go_client.get_all_active_catalog_items(
                    limit=CLEANER_BATCH_SIZE, offset=current_offset
                )
            except Exception as e:
                self.logger.error(f"Ошибка получения 'active' батча: {e}", exc_info=True)
                break

            if not items_batch:
                self.logger.info("Обработка дубликатов (Часть Б) завершена.")
                break

            # 3. Итерируем по батчу
            for item in items_batch:
                try:
                    # DTO: { "position_item_id": 123 (это catalog_id), "rich_context_string": "..." }
                    item_id = item["position_item_id"]
                    context_str = item["rich_context_string"]

                    # 4. "Поиск самого себя" в КОРПУСЕ
                    search_results = await self.file_search.search(context_str)

                    if not search_results:
                        self.logger.warning(f"RAG-поиск (дедупликация) не вернул результатов для ID {item_id}")
                        continue

                    # 5. Итерируем по результатам, чтобы найти ДРУГУЮ запись
                    for match in search_results:
                        matched_id = match.get("catalog_id")
                        score = match.get("score", 0.0)

                        # Пропускаем "самого себя"
                        if str(item_id) == str(matched_id):
                            continue

                        # Если нашли ДРУГУЮ запись с высоким score
                        if score > SUGGEST_THRESHOLD:
                            self.logger.info(f"Обнаружен дубликат! {item_id} -> {matched_id} (Score: {score:.4f})")

                            # 6. Предлагаем слияние
                            await self.go_client.post_suggest_merge(
                                main_id=int(matched_id), duplicate_id=int(item_id), score=score
                            )
                            total_suggestions += 1
                            # Нашли лучший дубликат, переходим к следующему item
                            break

                except Exception as e:
                    self.logger.error(f"Ошибка RAG-поиска (дедупликация) для ID {item.get('position_item_id')}: {e}")
                    continue

            # 7. Увеличиваем offset для следующего батча
            current_offset += CLEANER_BATCH_SIZE
            total_processed += len(items_batch)

        return {"items_processed": total_processed, "suggestions_found": total_suggestions}
