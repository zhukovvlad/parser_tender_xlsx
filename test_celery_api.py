#!/usr/bin/env python3
"""
Тестирование Celery API интеграции
"""

import json
import time

import requests


def test_ai_processing():
    """Тестируем AI обработку файла через Celery"""

    print("🧪 Тестирование Celery AI обработки...")

    # Отправляем файл на AI обработку
    with open("tenders_xlsx/42.xlsx", "rb") as f:
        files = {"file": ("42.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = requests.post("http://localhost:8000/parse-tender-ai/", files=files)

    if response.status_code == 202:
        task_info = response.json()
        task_id = task_info["task_id"]
        celery_task_id = task_info["celery_task_id"]
        print(f"🚀 AI задача отправлена:")
        print(f"  Task ID: {task_id}")
        print(f"  Celery Task ID: {celery_task_id}")
        print(f'  Лотов для обработки: {task_info["lots_count"]}')
        print()

        # Проверяем статус Celery задачи
        for i in range(30):  # 60 секунд максимум
            status_response = requests.get(f"http://localhost:8000/celery-tasks/{celery_task_id}/status")
            if status_response.status_code == 200:
                status_data = status_response.json()
                state = status_data["state"]

                if state == "PENDING":
                    print(f"⏳ Статус {i+1}: Ожидание запуска...")
                elif state == "PROCESSING":
                    meta = status_data.get("result", {})
                    stage = meta.get("stage", "unknown")
                    progress = meta.get("progress", 0)
                    processed = meta.get("processed_lots", 0)
                    total = meta.get("total_lots", 0)
                    print(f"🔄 Статус {i+1}: {stage} - {progress}% ({processed}/{total})")
                elif state == "SUCCESS":
                    print(f"✅ Обработка завершена успешно!")
                    result = status_data.get("result", {})
                    if "batch_result" in result:
                        batch = result["batch_result"]
                        print(f"📊 Результаты batch обработки:")
                        print(f'  Всего лотов: {batch.get("total_lots", 0)}')
                        print(f'  Запущено задач: {batch.get("dispatched_tasks", 0)}')
                        print(f'  Статус: {batch.get("status", "unknown")}')
                        print(f'  Сообщение: {batch.get("message", "")}')

                        # Показываем ID подзадач для отслеживания
                        subtask_ids = batch.get("subtask_ids", [])
                        if subtask_ids:
                            print(
                                f"  ID подзадач: {subtask_ids[:3]}..."
                                if len(subtask_ids) > 3
                                else f"  ID подзадач: {subtask_ids}"
                            )

                        # Для асинхронной архитектуры показываем как проверить результаты
                        if subtask_ids:
                            print(f"  💡 Для проверки результатов используйте:")
                            print(f"     curl http://localhost:8000/celery-tasks/{subtask_ids[0]}/status")
                    break
                elif state == "FAILURE":
                    print(f"❌ Ошибка обработки:")
                    error_info = status_data.get("result", {})
                    print(f'  Ошибка: {error_info.get("error", "Unknown error")}')
                    break
            else:
                print(f"⚠️  Ошибка получения статуса: {status_response.status_code}")
            time.sleep(2)
    else:
        print(f"❌ Ошибка запроса: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    test_ai_processing()
