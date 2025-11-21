#!/usr/bin/env python3
"""
Скрипт для просмотра Google File Search Store и списка документов в нем.

Использование:
    python scripts/show_google_stores.py
"""
import asyncio
import os
import sys
from pathlib import Path
from google import genai
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
project_root = Path(__file__).parent.parent
env_path = project_root / ".env"
print(f"Loading .env from: {env_path}")
load_dotenv(env_path)

# Убедитесь, что ваш API-ключ установлен как переменная окружения GOOGLE_API_KEY
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("Ошибка: Переменная окружения GOOGLE_API_KEY не установлена.")
    sys.exit(1)

print("API Key loaded successfully from environment.")

# Создаем клиент
client = genai.Client(api_key=api_key)

STORE_DISPLAY_NAME = "Tenders Catalog Store"

async def main():
    try:
        print("Список всех доступных хранилищ (Async):")
        target_store = None
        stores_pager = await client.aio.file_search_stores.list()
        async for store in stores_pager:
            print(f"- Name: {store.name}, Display Name: {store.display_name}")
            if store.display_name == STORE_DISPLAY_NAME:
                target_store = store
                
        if target_store:
            print(f"Хранилище найдено: {target_store.name}")
            print("\n--- Документы в хранилище ---")
            
            # Получаем список документов
            docs_pager = await client.aio.file_search_stores.documents.list(parent=target_store.name)
            async for doc in docs_pager:
                print(f"  - Документ: {doc.name}")
                print(f"    Отображаемое имя: {doc.display_name}")
        else:
            print(f"Хранилище с именем '{STORE_DISPLAY_NAME}' не найдено.")

    except Exception as e:
        print(f"Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())

