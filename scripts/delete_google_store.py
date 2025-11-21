#!/usr/bin/env python3
"""
Скрипт для удаления Google File Search Store и всех его документов.

Использование:
    python scripts/delete_google_store.py

Примечание:
    - Использует REST API для force delete
    - Удаляет хранилище 'Tenders Catalog Store' вместе со всеми документами
    - Требует GOOGLE_API_KEY в .env файле
"""
import os
import sys
import requests
from pathlib import Path
from dotenv import load_dotenv

# Добавляем корневую директорию проекта в путь
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from google import genai

# Загружаем переменные окружения
load_dotenv(project_root / ".env")

STORE_DISPLAY_NAME = "Tenders Catalog Store"


def find_store(client, display_name):
    """Найти хранилище по display_name"""
    for store in client.file_search_stores.list():
        if store.display_name == display_name:
            return store
    return None


def delete_store_rest_api(store_name, api_key, timeout=10.0):
    """Удалить хранилище через REST API с force=true"""
    url = f"https://generativelanguage.googleapis.com/v1beta/{store_name}?force=true"
    headers = {"x-goog-api-key": api_key}

    try:
        response = requests.delete(url, headers=headers, timeout=timeout)
        return response
    except requests.exceptions.RequestException as e:
        print(f"❌ Ошибка сети при удалении: {e}")
        return None


def main():
    # Проверяем API ключ
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ Ошибка: GOOGLE_API_KEY не установлен в .env")
        return 1

    client = genai.Client(api_key=api_key)

    print("=" * 80)
    print("🗑️  УДАЛЕНИЕ GOOGLE FILE SEARCH STORE")
    print("=" * 80)

    # Ищем хранилище
    print(f"\n🔍 Поиск хранилища: '{STORE_DISPLAY_NAME}'...")
    target_store = find_store(client, STORE_DISPLAY_NAME)

    if not target_store:
        print(f"⚠️  Хранилище '{STORE_DISPLAY_NAME}' не найдено")
        print("✅ Ничего удалять не нужно")
        return 0

    print(f"✅ Найдено хранилище: {target_store.name}")

    # Получаем информацию о документах
    try:
        documents = list(client.file_search_stores.documents.list(parent=target_store.name))
        print(f"📄 Документов в хранилище: {len(documents)}")
    except Exception as e:
        print(f"⚠️  Не удалось получить список документов: {e}")
        documents = []

    # Подтверждение удаления
    print("\n⚠️  ВНИМАНИЕ: Это действие необратимо!")
    print(f"   Будет удалено хранилище и {len(documents)} документов")

    confirm = input("\nПродолжить удаление? (yes/no): ").strip().lower()
    if confirm not in ['yes', 'y']:
        print("❌ Удаление отменено")
        return 0

    # Удаляем через REST API
    print("\n🗑️  Удаление хранилища через REST API...")
    response = delete_store_rest_api(target_store.name, api_key)

    if response and response.status_code == 200:
        print("✅ Хранилище успешно удалено!")
        print(f"   Удалено документов: {len(documents)}")

        # Проверяем удаление
        print("\n🔍 Проверка удаления...")
        verify_store = find_store(client, STORE_DISPLAY_NAME)
        if verify_store is None:
            print("✅ Подтверждено: хранилище удалено")
        else:
            print("⚠️  Хранилище все еще существует")

        return 0
    elif response:
        print(f"❌ Ошибка при удалении: {response.status_code}")
        print(f"   Response: {response.text}")
        return 1
    else:
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n❌ Удаление прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Непредвиденная ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
