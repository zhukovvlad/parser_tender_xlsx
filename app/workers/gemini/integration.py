# app/workers/gemini/integration.py

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...gemini_module.constants import FALLBACK_CATEGORY, TENDER_CATEGORIES, TENDER_CONFIGS
from ...gemini_module.logger import get_gemini_logger
from .manager import GeminiManager

try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class GeminiIntegration:
    """
    Интеграционный класс для встраивания Gemini обработки в существующий пайплайн.
    """

    def __init__(self, api_key: Optional[str] = None, redis_client: Optional[Any] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.redis_client = redis_client
        self.logger = get_gemini_logger()

        if not self.api_key:
            self.logger.warning("⚠️ GOOGLE_API_KEY не найден - AI обработка будет недоступна")

        # Инициализируем менеджер, если есть API ключ
        self.manager = None
        if self.api_key:
            self.manager = GeminiManager(self.api_key, redis_client)

    def process_tender_lots_sync(self, tender_id: str, lots_data: List[Dict]) -> List[Dict]:
        """
        Синхронная обработка всех лотов тендера.
        """
        if not self.manager:
            self.logger.error("❌ Менеджер не инициализирован (нет API ключа)")
            return []

        results = []

        for lot_data in lots_data:
            lot_id = lot_data.get("lot_id")
            positions_file = lot_data.get("positions_file_path")

            if not positions_file or not Path(positions_file).exists():
                self.logger.warning(f"⚠️ Файл позиций не найден для лота {lot_id}: {positions_file}")
                continue

            # Подготавливаем задачу
            task = {
                "tender_id": tender_id,
                "lot_id": lot_id,
                "positions_file_path": positions_file,
                "categories": TENDER_CATEGORIES,
                "configs": TENDER_CONFIGS,
                "fallback_category": FALLBACK_CATEGORY,
            }

            # Обрабатываем синхронно
            result = self.manager.process_sync(task)
            results.append(result)

        self.logger.info(f"✅ Синхронная обработка завершена: {len(results)} лотов")
        return results

    def queue_tender_lots_async(self, tender_id: str, lots_data: List[Dict], queue_name: str = "ai_tasks") -> bool:
        """
        Асинхронная обработка - добавляет все лоты в очередь Redis.
        """
        if not self.manager:
            self.logger.error("❌ Менеджер не инициализирован (нет API ключа)")
            return False

        if not self.redis_client:
            self.logger.error("❌ Redis не настроен для асинхронной обработки")
            return False

        queued_count = 0

        for lot_data in lots_data:
            lot_id = lot_data.get("lot_id")
            positions_file = lot_data.get("positions_file_path")

            if not positions_file or not Path(positions_file).exists():
                self.logger.warning(f"⚠️ Файл позиций не найден для лота {lot_id}: {positions_file}")
                continue

            # Подготавливаем задачу
            task = {
                "tender_id": tender_id,
                "lot_id": lot_id,
                "positions_file_path": positions_file,
                "categories": TENDER_CATEGORIES,
                "configs": TENDER_CONFIGS,
                "fallback_category": FALLBACK_CATEGORY,
            }

            # Добавляем в очередь
            if self.manager.queue_task(task, queue_name):
                queued_count += 1

        self.logger.info(f"✅ В очередь добавлено: {queued_count} лотов")
        return queued_count > 0

    def get_lot_result(self, tender_id: str, lot_id: str) -> Optional[Dict]:
        """
        Получает результат обработки лота из Redis.
        """
        if not self.redis_client:
            return None

        try:
            result_key = f"result:{tender_id}_{lot_id}"
            result_json = self.redis_client.get(result_key)

            if result_json:
                import json

                return json.loads(result_json.decode("utf-8"))

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения результата: {e}")

        return None

    def get_lot_status(self, tender_id: str, lot_id: str) -> Optional[Dict]:
        """
        Получает статус обработки лота из Redis.
        """
        if not self.redis_client:
            return None

        try:
            status_key = f"status:{tender_id}_{lot_id}"
            status_json = self.redis_client.get(status_key)

            if status_json:
                import json

                return json.loads(status_json.decode("utf-8"))

        except Exception as e:
            self.logger.error(f"❌ Ошибка получения статуса: {e}")

        return None

    @staticmethod
    def setup_redis_client(host: str = "localhost", port: int = 6379, db: int = 0) -> Optional[Any]:
        """
        Настраивает подключение к Redis.

        Args:
            host: Хост Redis
            port: Порт Redis
            db: База данных Redis

        Returns:
            Redis клиент или None если подключение неудачное
        """
        if not REDIS_AVAILABLE:
            return None

        try:
            import redis

            client = redis.Redis(host=host, port=port, db=db, decode_responses=False)
            client.ping()
            return client
        except Exception:
            return None

    def create_positions_file_data(
        self, tender_db_id: str, tender_data: Dict, lot_ids_map: Dict[str, int]
    ) -> List[Dict]:
        """
        Создает структуру данных для AI обработки лотов на основе реальных ID из БД.

        Args:
            tender_db_id: Реальный ID тендера из БД
            tender_data: Данные тендера из JSON
            lot_ids_map: Маппинг "lot_1" -> реальный_lot_db_id

        Returns:
            Список словарей с данными лотов для AI обработки
        """
        lots_data = []

        # Извлекаем лоты из tender_data
        lots = tender_data.get("lots", {})

        for lot_key, lot_data in lots.items():
            # Получаем реальный ID лота из маппинга
            real_lot_id = lot_ids_map.get(lot_key)

            if not real_lot_id:
                self.logger.warning(f"⚠️ Не найден реальный ID для лота {lot_key}")
                continue

            # Формируем возможные пути к файлу positions
            # Сначала ищем в финальной директории, потом в pending
            positions_paths = [
                Path("tenders_positions") / f"{tender_db_id}_{real_lot_id}_positions.md",
                Path("pending_sync_positions") / f"{tender_db_id}_{real_lot_id}_positions.md",
            ]

            positions_file_path = None
            for path in positions_paths:
                if path.exists():
                    positions_file_path = path
                    break

            if not positions_file_path:
                self.logger.warning(
                    f"⚠️ Файл positions не найден для лота {real_lot_id}. Проверены пути: {[str(p) for p in positions_paths]}"
                )
                continue

            lots_data.append(
                {
                    "lot_id": str(real_lot_id),
                    "positions_file_path": str(positions_file_path),
                    "lot_key": lot_key,  # Для отладки
                    "lot_title": lot_data.get("lot_title", ""),
                }
            )

        self.logger.info(f"📋 Подготовлено {len(lots_data)} лотов для AI обработки")
        return lots_data
