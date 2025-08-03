#!/usr/bin/env python3
"""
Тестирование Celery API интеграции
"""

import requests
import json
import time

def test_ai_processing():
    """Тестируем AI обработку файла через Celery"""
    
    print("🧪 Тестирование Celery AI обработки...")
    
    # Отправляем файл на AI обработку
    with open('tenders_xlsx/42.xlsx', 'rb') as f:
        files = {'file': ('42.xlsx', f, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}
        response = requests.post('http://localhost:8000/parse-tender-ai/', files=files)

    if response.status_code == 202:
        task_info = response.json()
        task_id = task_info['task_id']
        celery_task_id = task_info['celery_task_id']
        print(f'🚀 AI задача отправлена:')
        print(f'  Task ID: {task_id}')
        print(f'  Celery Task ID: {celery_task_id}')
        print(f'  Лотов для обработки: {task_info["lots_count"]}')
        print()
        
        # Проверяем статус Celery задачи
        for i in range(30):  # 60 секунд максимум
            status_response = requests.get(f'http://localhost:8000/celery-tasks/{celery_task_id}/status')
            if status_response.status_code == 200:
                status_data = status_response.json()
                state = status_data['state']
                
                if state == 'PENDING':
                    print(f'⏳ Статус {i+1}: Ожидание запуска...')
                elif state == 'PROCESSING':
                    meta = status_data.get('result', {})
                    stage = meta.get('stage', 'unknown')
                    progress = meta.get('progress', 0)
                    processed = meta.get('processed_lots', 0)
                    total = meta.get('total_lots', 0)
                    print(f'🔄 Статус {i+1}: {stage} - {progress}% ({processed}/{total})')
                elif state == 'SUCCESS':
                    print(f'✅ Обработка завершена успешно!')
                    result = status_data.get('result', {})
                    if 'batch_result' in result:
                        batch = result['batch_result']
                        print(f'📊 Результаты batch обработки:')
                        print(f'  Всего лотов: {batch.get("total_lots", 0)}')
                        print(f'  Успешно: {batch.get("successful_lots", 0)}')
                        print(f'  Ошибок: {batch.get("failed_lots", 0)}')
                        
                        # Показываем результат первого лота
                        if batch.get('results'):
                            first_result = batch['results'][0]
                            if first_result.get('status') == 'success':
                                print(f'  Категория: {first_result.get("category", "unknown")}')
                                ai_data = first_result.get('ai_data', {})
                                print(f'  Извлечено полей: {len(ai_data)}')
                    break
                elif state == 'FAILURE':
                    print(f'❌ Ошибка обработки:')
                    error_info = status_data.get('result', {})
                    print(f'  Ошибка: {error_info.get("error", "Unknown error")}')
                    break
            else:
                print(f'⚠️  Ошибка получения статуса: {status_response.status_code}')
            time.sleep(2)
    else:
        print(f'❌ Ошибка запроса: {response.status_code}')
        print(response.text)

if __name__ == "__main__":
    test_ai_processing()
