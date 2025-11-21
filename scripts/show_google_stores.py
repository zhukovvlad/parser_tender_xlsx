#!/usr/bin/env python3
"""
Скрипт для просмотра Google File Search Store и списка документов в нем.

Использование:
    python scripts/show_google_stores.py
"""
import os
import sys
from pathlib import Path
from google import genai
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

# Убедитесь, что ваш API-ключ установлен как переменная окружения GOOGLE_API_KEY
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("Ошибка: Переменная окружения GOOGLE_API_KEY не установлена.")
    sys.exit(1)

# Создаем клиент, передавая ключ напрямую
client = genai.Client(api_key=api_key)

STORE_DISPLAY_NAME = "Tenders Catalog Store"

try:
    print(f"Поиск хранилища с именем: '{STORE_DISPLAY_NAME}'...")
    target_store = None
    for store in client.file_search_stores.list():
        if store.display_name == STORE_DISPLAY_NAME:
            target_store = store
            break

    if target_store:
        print(f"Хранилище найдено: {target_store.name}")
        print("\n--- Документы в хранилище ---")
        
        # Получаем список документов в найденном хранилище
        documents = client.file_search_stores.documents.list(parent=target_store.name)
        
        doc_count = 0
        for doc in documents:
            doc_count += 1
            print(f"  - Документ: {doc.name}")
            print(f"    Отображаемое имя: {doc.display_name}")
            # Можно добавить вывод другой метаинформации, если она есть
            # print(f"    Метаданные: {doc.custom_metadata}")

        if doc_count == 0:
            print("В хранилище нет документов.")

        print("\n--------------------------")

    else:
        print(f"Хранилище с именем '{STORE_DISPLAY_NAME}' не найдено.")

    print("\nГотово.")

except Exception as e:
    print(f"Произошла ошибка: {e}")

