#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Smoke-тест Search Indexer Worker.

Обрабатывает TEST_BATCH_SIZE pending_indexing позиций:
  1. Генерирует embedding (Gemini gemini-embedding-001, 768-d).
  2. Проверяет дубликаты (cosine distance < 0.15).
  3. Активирует (status → 'active').

Запуск:
    python test_search_indexer.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Размер тестового батча
TEST_BATCH_SIZE = 20
os.environ["SEARCH_INDEXER_BATCH_SIZE"] = str(TEST_BATCH_SIZE)

from app.workers.search_indexer.worker import SearchIndexerWorker


async def main() -> None:
    worker = SearchIndexerWorker()

    print("=" * 60)
    print(f"  SMOKE TEST: Search Indexer Worker ({TEST_BATCH_SIZE} позиций, unit-aware)")
    print("=" * 60)

    # 1. Инициализация
    print("\n[1/3] Инициализация (DB Pool + Gemini Embedding Client)...")

    try:
        await worker.initialize()
        print("      ✅ Worker инициализирован")
        # 2. Проверяем сколько pending_indexing ДО запуска
        before, active_before, indexing_before = await worker.fetch_indexing_stats()
        print("\n[2/3] Текущее состояние БД:")
        print(f"      pending_indexing = {before}")
        print(f"      active           = {active_before}")
        print(f"      indexing         = {indexing_before}")

        # 3. Запуск индексации
        print(f"\n[3/3] Запуск run_indexing() для батча из {TEST_BATCH_SIZE} записей...")
        result = await worker.run_indexing()

        print(f"\n{'=' * 60}")
        print("\n  РЕЗУЛЬТАТ:")
        print(f"    Обработано:  {result['processed']}")
        print(f"    Дубликатов:  {result['duplicates']}")
        print(f"    Пропущено:  {result.get('skipped', 0)}")
        print("=" * 60)

        # 4. Проверяем состояние ПОСЛЕ
        after, active_after, indexing_after = await worker.fetch_indexing_stats()
        pool = worker.get_pool()
        async with pool.acquire() as conn:
            merges = await conn.fetchval(
                "SELECT count(*) FROM suggested_merges"
            )

            # Показываем первые 3 активированные записи с embedding
            samples = await conn.fetch("""
                SELECT id, standard_job_title,
                       (embedding IS NOT NULL) as has_embedding,
                       status
                FROM catalog_positions
                WHERE status = 'active'
                ORDER BY updated_at DESC
                LIMIT 3
            """)

        print("\n  Состояние ПОСЛЕ:")
        print(f"    pending_indexing = {after}  (было {before})")
        print(f"    active           = {active_after}  (было {active_before})")
        print(f"    indexing         = {indexing_after}")
        print(f"    suggested_merges = {merges}")

        if samples:
            print("\n  Примеры активированных записей:")
            for s in samples:
                print(
                    f"    id={s['id']:>5d}  "
                    f"has_embedding={s['has_embedding']}  "
                    f"title={s['standard_job_title'][:60]!r}"
                )

    finally:
        # Гарантируем закрытие пула и освобождение ресурсов
        await worker.shutdown()
        print("\n✅ Тест завершён (shutdown выполнен).")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nПрервано пользователем")
        sys.exit(1)
