#!/usr/bin/env python3
"""
Скрипт для просмотра детальной информации о Google File Search Store
и его документах (батчах с catalog записями).

Использование:
    python scripts/show_store_details.py
"""
import os
import sys
import json
import tempfile
from pathlib import Path
from google import genai
from dotenv import load_dotenv

# Загружаем переменные окружения
project_root = Path(__file__).parent.parent
load_dotenv(project_root / ".env")

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("❌ Ошибка: GOOGLE_API_KEY не установлен")
    sys.exit(1)

client = genai.Client(api_key=api_key)
STORE_DISPLAY_NAME = "Tenders Catalog Store"

def print_separator(char="=", length=80):
    print(char * length)

def print_header(text):
    print_separator()
    print(f"  {text}")
    print_separator()

try:
    print_header("📚 ИНФОРМАЦИЯ О GOOGLE FILE SEARCH STORE")
    
    # Поиск хранилища
    print(f"\n🔍 Поиск хранилища: '{STORE_DISPLAY_NAME}'...")
    target_store = None
    
    for store in client.file_search_stores.list():
        if store.display_name == STORE_DISPLAY_NAME:
            target_store = store
            break
    
    if not target_store:
        print(f"❌ Хранилище '{STORE_DISPLAY_NAME}' не найдено")
        sys.exit(1)
    
    # Информация о Store
    print("\n✅ Хранилище найдено!")
    print(f"   Name: {target_store.name}")
    print(f"   Display Name: {target_store.display_name}")
    print(f"   Create Time: {target_store.create_time}")
    print(f"   Update Time: {target_store.update_time}")
    
    # Получаем документы
    print_header("📄 ДОКУМЕНТЫ В ХРАНИЛИЩЕ")
    
    documents = list(client.file_search_stores.documents.list(parent=target_store.name))
    
    if not documents:
        print("\n⚠️  В хранилище нет документов")
    else:
        print(f"\n📊 Всего документов: {len(documents)}")
        print()
        
        # Подсчитываем общее количество записей
        total_records = 0
        
        for idx, doc in enumerate(documents, 1):
            print(f"\n--- Документ #{idx} ---")
            print(f"  Name: {doc.name}")
            print(f"  Display Name: {doc.display_name}")
            print(f"  Create Time: {doc.create_time}")
            print(f"  Update Time: {doc.update_time}")
            
            # Если есть custom_metadata
            if hasattr(doc, 'custom_metadata') and doc.custom_metadata:
                print(f"  Custom Metadata: {doc.custom_metadata}")
            
            # Пытаемся прочитать содержимое из временного файла (если он еще существует)
            temp_file_name = doc.display_name.replace('.json', '')
            temp_file_path = os.path.join(tempfile.gettempdir(), f"{temp_file_name}.json")
            
            if os.path.exists(temp_file_path):
                try:
                    with open(temp_file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        print(f"  📝 Записей в батче: {len(data)}")
                        total_records += len(data)
                        
                        # Показываем первую запись как пример
                        if data:
                            first_record = data[0]
                            print("  📌 Пример записи:")
                            print(f"     catalog_id: {first_record.get('catalog_id')}")
                            context = first_record.get('context_string', '')
                            # Декодируем unicode для читабельности
                            if context:
                                # Берем первые 100 символов для краткости
                                preview = context[:100] + "..." if len(context) > 100 else context
                                print(f"     context: {preview}")
                except (json.JSONDecodeError, OSError) as e:
                    print(f"  ⚠️  Не удалось прочитать файл: {e}")
            else:
                print(f"  ⚠️  Временный файл не найден: {temp_file_path}")
        
        print_separator()
        print("📊 ИТОГОВАЯ СТАТИСТИКА:")
        print(f"   Документов (батчей): {len(documents)}")
        print(f"   Записей из каталога: {total_records if total_records > 0 else 'Н/Д'}")
        print_separator()

    print("\n✅ Готово!")

except Exception as e:
    print(f"\n❌ Ошибка: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
