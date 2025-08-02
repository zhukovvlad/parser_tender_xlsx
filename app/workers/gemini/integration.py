# app/workers/gemini/integration.py

import os
from pathlib import Path
from typing import Dict, List, Optional, Any

from ...gemini_module.constants import TENDER_CATEGORIES, TENDER_CONFIGS, FALLBACK_CATEGORY
from .manager import GeminiManager
from ...gemini_module.logger import get_gemini_logger

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
                "fallback_category": FALLBACK_CATEGORY
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
                "fallback_category": FALLBACK_CATEGORY
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
                return json.loads(result_json.decode('utf-8'))
            
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
                return json.loads(status_json.decode('utf-8'))
            
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
