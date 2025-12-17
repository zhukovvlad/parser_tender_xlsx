# app/workers/gemini/manager.py

import json
import time
from datetime import datetime
from typing import Any, Optional

try:
    import redis  # noqa: F401

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from ...gemini_module.logger import get_gemini_logger  # noqa: E402
from .worker import GeminiWorker  # noqa: E402


class GeminiManager:
    """
    Менеджер для Gemini воркера с поддержкой Redis очередей и retry-механизмом.
    """

    def __init__(self, api_key: str, redis_client: Optional[Any] = None):
        self.worker = GeminiWorker(api_key)
        self.redis = redis_client if REDIS_AVAILABLE else None
        self.logger = get_gemini_logger()
        self.max_retries = 3
        self.running = False

        if not REDIS_AVAILABLE and redis_client:
            self.logger.warning("⚠️ Redis не установлен, но redis_client передан. Работаю в fallback режиме.")

    def run_queue_worker(self, queue_name: str = "ai_tasks"):
        """
        Основной цикл воркера для обработки задач из Redis очереди.
        """
        if not self.redis:
            self.logger.error("❌ Redis не настроен. Невозможно запустить queue worker.")
            return

        self.running = True
        self.logger.info(f"🚀 Запускаю Gemini воркер очереди '{queue_name}'...")

        while self.running:
            try:
                # Забираем задачу из очереди (блокирующий вызов с таймаутом)
                task_data = self.redis.blpop([queue_name], timeout=5)

                if not task_data:
                    continue

                queue_name_from_redis, task_json = task_data
                task = json.loads(task_json.decode("utf-8"))

                self.logger.info(f"📥 Получена задача: {task.get('tender_id')}_{task.get('lot_id')}")

                # Обрабатываем задачу с retry
                result = self._process_with_retry(task)

                # Сохраняем результат
                self._save_result(task, result)

            except KeyboardInterrupt:
                self.logger.info("🛑 Получен сигнал остановки")
                self.running = False
            except Exception as e:
                self.logger.error(f"❌ Ошибка в цикле воркера: {e}")
                time.sleep(1)

        self.logger.info("✅ Воркер остановлен")

    def _process_with_retry(self, task: dict) -> dict:
        """Обрабатывает задачу с retry механизмом"""
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.info(f"🔄 Попытка {attempt}/{self.max_retries}")

                result = self.worker.process_positions_file(
                    tender_id=task.get("tender_id"),
                    lot_id=task.get("lot_id"),
                    positions_file_path=task.get("positions_file_path"),
                    categories=task.get("categories", []),
                    configs=task.get("configs", {}),
                    fallback_category=task.get("fallback_category", "не найдено"),
                )

                if result.get("status") == "success":
                    return result
                else:
                    last_error = result.get("error", "Unknown error")

            except Exception as e:
                last_error = str(e)
                self.logger.warning(f"⚠️ Попытка {attempt} неудачна: {e}")

                if attempt < self.max_retries:
                    # Экспоненциальная задержка
                    delay = 2 ** (attempt - 1)
                    time.sleep(delay)

        # Все попытки исчерпаны
        return {
            "tender_id": task.get("tender_id"),
            "lot_id": task.get("lot_id"),
            "status": "failed",
            "error": f"Исчерпаны все попытки. Последняя ошибка: {last_error}",
            "processed_at": datetime.now().isoformat(),
        }

    def _save_result(self, task: dict, result: dict):
        """Сохраняет результат обработки"""
        try:
            if self.redis:
                # Сохраняем в Redis с TTL 24 часа
                result_key = f"result:{task.get('tender_id')}_{task.get('lot_id')}"
                self.redis.setex(result_key, 86400, json.dumps(result, ensure_ascii=False))

                # Обновляем статус задачи
                self._update_task_status(task, result.get("status", "unknown"))

            self.logger.info(f"💾 Результат сохранен для {task.get('tender_id')}_{task.get('lot_id')}")

        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения результата: {e}")

    def _update_task_status(self, task: dict, status: str):
        """Обновляет статус задачи в Redis"""
        try:
            status_key = f"status:{task.get('tender_id')}_{task.get('lot_id')}"
            status_data = {"status": status, "updated_at": datetime.now().isoformat(), "worker": "gemini"}
            self.redis.setex(status_key, 86400, json.dumps(status_data))
        except Exception as e:
            self.logger.warning(f"⚠️ Не удалось обновить статус: {e}")

    def process_sync(self, task: dict) -> dict:
        """
        Синхронная обработка одной задачи без использования Redis.
        """
        return self.worker.process_positions_file(
            tender_id=task.get("tender_id"),
            lot_id=task.get("lot_id"),
            positions_file_path=task.get("positions_file_path"),
            categories=task.get("categories", []),
            configs=task.get("configs", {}),
            fallback_category=task.get("fallback_category", "не найдено"),
        )

    def queue_task(self, task: dict, queue_name: str = "ai_tasks") -> bool:
        """
        Добавляет задачу в очередь Redis.
        """
        if not self.redis:
            self.logger.error("❌ Redis не настроен. Невозможно добавить задачу в очередь.")
            return False

        try:
            task_json = json.dumps(task, ensure_ascii=False)
            self.redis.rpush(queue_name, task_json)

            self.logger.info(
                f"📤 Задача добавлена в очередь '{queue_name}': {task.get('tender_id')}_{task.get('lot_id')}"
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Не удалось добавить задачу в очередь: {e}")
            return False

    def stop(self):
        """Останавливает воркер"""
        self.running = False
