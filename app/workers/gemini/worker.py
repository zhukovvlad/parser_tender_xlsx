# app/workers/gemini/worker.py

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from ...gemini_module.processor import TenderProcessor
from ...gemini_module.logger import get_gemini_logger


class GeminiWorker:
    """
    Воркер для обработки AI-задач с использованием TenderProcessor.
    Интегрируется в существующий пайплайн обработки тендеров.
    """
    
    def __init__(self, api_key: str):
        self.processor = TenderProcessor(api_key)
        self.logger = get_gemini_logger()
        
    def process_positions_file(self, tender_id: str, lot_id: str, positions_file_path: str, 
                              categories: list, configs: dict, fallback_category: str = "не найдено") -> Dict:
        """
        Обрабатывает файл _positions.md для конкретного лота.
        
        Args:
            tender_id: ID тендера в базе данных
            lot_id: ID лота в базе данных  
            positions_file_path: Путь к файлу _positions.md
            categories: Список категорий для классификации
            configs: Конфигурации для извлечения JSON
            fallback_category: Категория по умолчанию
        
        Returns:
            Dict с результатами обработки
        """
        positions_file = Path(positions_file_path)
        
        try:
            if not positions_file.exists():
                raise FileNotFoundError(f"Файл позиций не найден: {positions_file_path}")
            
            self.logger.info(f"Начинаю AI-обработку лота {tender_id}_{lot_id}")
            
            # Загружаем файл в Gemini
            self.processor.upload(str(positions_file))
            
            # Классификация документа
            category = self.processor.classify(categories)
            self.logger.info(f"📂 Категория: {category}")
            
            # Извлечение структурированных данных
            json_data = {}
            if category in configs:
                json_data = self.processor.extract_json(category, configs)
                self.logger.info(f"📋 Извлечены данные: {len(json_data)} полей")
            else:
                self.logger.warning(f"⚠️ Конфигурация для категории '{category}' не найдена")
                category = fallback_category
            
            # Подготовка результата
            result = {
                "tender_id": tender_id,
                "lot_id": lot_id,
                "category": category,
                "ai_data": json_data,
                "processed_at": datetime.now().isoformat(),
                "status": "success",
                "file_path": str(positions_file)
            }
            
            self.logger.info(f"✅ Лот {tender_id}_{lot_id} успешно обработан")
            return result
            
        except Exception as e:
            error_result = {
                "tender_id": tender_id,
                "lot_id": lot_id,
                "category": fallback_category,
                "ai_data": {},
                "processed_at": datetime.now().isoformat(),
                "status": "error",
                "error": str(e),
                "file_path": str(positions_file)
            }
            
            self.logger.error(f"❌ Ошибка обработки лота {tender_id}_{lot_id}: {e}")
            return error_result
        
        finally:
            # Очистка временных файлов в процессоре
            try:
                self.processor.cleanup()
            except:
                pass
    
    def batch_process(self, tasks: list) -> list:
        """
        Обрабатывает пакет задач последовательно.
        
        Args:
            tasks: Список задач, каждая с полями:
                   tender_id, lot_id, positions_file_path, categories, configs
        
        Returns:
            Список результатов обработки
        """
        results = []
        
        self.logger.info(f"🔄 Начинаю batch обработку {len(tasks)} задач")
        
        for i, task in enumerate(tasks, 1):
            self.logger.info(f"📝 Обрабатываю задачу {i}/{len(tasks)}")
            
            result = self.process_positions_file(
                tender_id=task.get("tender_id"),
                lot_id=task.get("lot_id"),
                positions_file_path=task.get("positions_file_path"),
                categories=task.get("categories", []),
                configs=task.get("configs", {}),
                fallback_category=task.get("fallback_category", "не найдено")
            )
            
            results.append(result)
        
        success_count = sum(1 for r in results if r.get("status") == "success")
        self.logger.info(f"✅ Batch обработка завершена: {success_count}/{len(tasks)} успешно")
        
        return results
    
    def cleanup_temp_files(self, temp_dir: Optional[str] = None):
        """
        Очищает временные файлы воркера.
        
        Args:
            temp_dir: Папка для очистки (по умолчанию используется системная временная)
        """
        try:
            if temp_dir:
                temp_path = Path(temp_dir)
                if temp_path.exists():
                    import shutil
                    shutil.rmtree(temp_path)
                    self.logger.info(f"🗑️ Временная папка {temp_dir} очищена")
            
            # Очистка в процессоре
            self.processor.cleanup()
            
        except Exception as e:
            self.logger.warning(f"⚠️ Ошибка при очистке временных файлов: {e}")
    
    def get_status(self) -> Dict:
        """
        Возвращает текущий статус воркера.
        
        Returns:
            Словарь со статусом воркера
        """
        try:
            # Проверяем доступность процессора
            is_ready = hasattr(self.processor, 'model') and self.processor.model is not None
            
            return {
                "worker_type": "gemini",
                "status": "ready" if is_ready else "not_ready",
                "processor_ready": is_ready,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "worker_type": "gemini", 
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
