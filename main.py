"""Основной модуль веб-сервиса для обработки тендерных файлов.

Этот модуль запускает FastAPI приложение и определяет следующие API эндпоинты:
- POST /parse-tender/: Принимает XLSX файл, создает фоновую задачу для его
  парсинга и немедленно возвращает ID задачи.
- GET /tasks/{task_id}/status: Позволяет отслеживать статус выполнения
  фоновой задачи (processing, completed, failed).
- GET /health: Проверяет работоспособность сервиса.

Для управления фоновыми задачами используется встроенный механизм FastAPI.
Статусы задач хранятся в Redis для обеспечения надежности и масштабируемости.
"""

import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

import redis
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile

from app.parse import parse_file
from app.celery_app import celery_app
from app.workers.gemini.tasks import process_tender_positions, process_tender_batch

# --- ЦЕНТРАЛИЗОВАННАЯ НАСТРОЙКА ПРИЛОЖЕНИЯ ---

# Загружаем переменные окружения из файла .env в корне проекта
load_dotenv()

# 1. Настройка логирования
log_dir = Path("logs")
os.makedirs(log_dir, exist_ok=True)

# Читаем уровень логирования из .env (по умолчанию INFO)
log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
log_level = log_levels.get(log_level_str, logging.INFO)

# Конфигурируем logging ОДИН РАЗ для всего приложения
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "parser_service.log", mode="w", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)

# Получаем именованный логгер для текущего модуля (main)
log = logging.getLogger(__name__)


# 2. Настройка подключения к Redis
# Данные для подключения также берутся из переменных окружения
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    password=os.getenv("REDIS_PASSWORD"),
    decode_responses=True,  # Автоматически декодировать ответы из байтов в строки
)

# --- КОНЕЦ БЛОКА НАСТРОЙКИ ---


# Настройка FastAPI приложения
app = FastAPI(
    title="Tender Parser Service",
    description="Сервис для асинхронной обработки тендерных XLSX файлов.",
    version="2.0.0",
)

# Директория для временного хранения загруженных файлов
UPLOAD_DIRECTORY = Path("temp_uploads")
os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)


def run_parsing_in_background(task_id: str, file_path: str):
    """
    Выполняет парсинг в фоновом режиме и обновляет статус задачи в Redis.

    Args:
        task_id (str): Уникальный идентификатор задачи.
        file_path (str): Путь к временному файлу для обработки.
    """
    log.info(f"Task {task_id}: Обработка файла {file_path} началась в фоне.")

    status_key = f"task_status:{task_id}"

    # Устанавливаем статус "в обработке" и время жизни ключа (например, 1 час)
    status_processing = json.dumps({"status": "processing"})
    redis_client.set(status_key, status_processing, ex=3600)

    try:
        parse_file(file_path)
        status_completed = json.dumps({"status": "completed"})
        redis_client.set(status_key, status_completed, ex=3600)
        log.info(f"Task {task_id}: Обработка успешно завершена.")
    except Exception as e:
        log.error(f"Task {task_id}: Произошла ошибка - {e}", exc_info=True)
        status_failed = json.dumps({"status": "failed", "error": str(e)})
        redis_client.set(status_key, status_failed, ex=3600)


@app.post("/parse-tender/", status_code=202, tags=["Tender Processing"])
async def create_parsing_task(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Принимает файл, создает для него уникальную задачу и запускает
    обработку в фоновом режиме, немедленно возвращая ID задачи.
    """
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Неверный формат файла. Пожалуйста, загрузите XLSX или XLS файл.",
        )

    task_id = str(uuid.uuid4())
    temp_file_path = UPLOAD_DIRECTORY / f"{task_id}_{file.filename}"
    log.info(f"Task {task_id}: Получен файл {file.filename}. Сохранение в: {temp_file_path}")

    try:
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        log.error(f"Task {task_id}: Не удалось сохранить файл: {e}")
        raise HTTPException(status_code=500, detail="Не удалось сохранить файл на сервере.")
    finally:
        file.file.close()

    # Добавляем задачу в фоновое выполнение
    background_tasks.add_task(run_parsing_in_background, task_id, str(temp_file_path))

    return {"task_id": task_id, "message": "Задача по обработке файла принята."}


@app.get("/tasks/{task_id}/status", tags=["Task Status"])
async def get_task_status(task_id: str):
    """
    Возвращает текущий статус задачи по ее ID из Redis.
    """
    status_key = f"task_status:{task_id}"
    task_json = redis_client.get(status_key)

    if not task_json:
        raise HTTPException(status_code=404, detail="Задача с таким ID не найдена.")

    return json.loads(task_json)


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Простая проверка работоспособности сервиса."""
    return {"status": "ok"}


@app.post("/parse-tender-ai/", status_code=202, tags=["AI Processing"])
async def create_ai_parsing_task(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    """
    Принимает файл, парсит его стандартным способом, а затем запускает 
    AI обработку через Celery для извлечения ключевых параметров.
    """
    if not file.filename or not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(
            status_code=400,
            detail="Неверный формат файла. Пожалуйста, загрузите XLSX или XLS файл.",
        )

    task_id = str(uuid.uuid4())
    temp_file_path = UPLOAD_DIRECTORY / f"{task_id}_{file.filename}"
    log.info(f"AI Task {task_id}: Получен файл {file.filename} для AI обработки")

    try:
        # Сохраняем файл
        with open(temp_file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Сначала выполняем стандартный парсинг
        log.info(f"AI Task {task_id}: Запускаю стандартный парсинг")
        parse_file(str(temp_file_path))
        
        # После парсинга ищем созданные файлы positions в директориях
        lots_data = []
        
        # Ищем в основных директориях
        positions_dirs = [
            Path("tenders_positions"),
            Path("pending_sync_positions")
        ]
        
        positions_files = []
        for pos_dir in positions_dirs:
            if pos_dir.exists():
                positions_files.extend(pos_dir.glob("*_positions.md"))
        
        # Сортируем по времени создания (новые сначала)
        positions_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        # Берем недавно созданные файлы (в течение последних 30 секунд)
        import time
        current_time = time.time()
        recent_files = [
            f for f in positions_files 
            if current_time - f.stat().st_mtime < 30
        ]
        
        log.info(f"AI Task {task_id}: Найдено {len(recent_files)} недавно созданных файлов positions")
        
        for positions_file in recent_files:
            # Извлекаем lot_id из имени файла (например: temp_1754203333_5037_594277_positions.md)
            stem = positions_file.stem  # без .md
            if stem.endswith("_positions"):
                lot_id = stem.replace("_positions", "").split("_")[-1]  # последняя часть
                lots_data.append({
                    "lot_id": lot_id,
                    "positions_file_path": str(positions_file.absolute())
                })
                log.info(f"AI Task {task_id}: Добавлен лот {lot_id} с файлом {positions_file.name}")
        
            if lots_data:
                # Получаем API ключ из окружения
                api_key = os.getenv("GOOGLE_API_KEY")
                if not api_key:
                    raise Exception("GOOGLE_API_KEY не найден в переменных окружения")
                
                # Запускаем AI обработку через Celery
                log.info(f"AI Task {task_id}: Запускаю AI обработку для {len(lots_data)} лотов")
                celery_task = process_tender_batch.delay(task_id, lots_data, api_key)
                
                return {
                "task_id": task_id,
                "celery_task_id": celery_task.id,
                "message": f"Стандартный парсинг завершен. AI обработка запущена для {len(lots_data)} лотов.",
                "lots_count": len(lots_data)
            }
        else:
            return {
                "task_id": task_id,
                "message": "Стандартный парсинг завершен, но не найдены файлы позиций для AI обработки.",
                "lots_count": 0
            }
            
    except Exception as e:
        log.error(f"AI Task {task_id}: Ошибка: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка при обработке файла: {str(e)}")
    finally:
        file.file.close()


@app.post("/process-positions/", status_code=202, tags=["AI Processing"])
async def process_single_positions_file(tender_id: str, lot_id: str, positions_file_path: str):
    """
    Запускает AI обработку для отдельного файла позиций через Celery.
    """
    if not Path(positions_file_path).exists():
        raise HTTPException(status_code=404, detail="Файл позиций не найден")
    
    # Запускаем задачу через Celery
    celery_task = process_tender_positions.delay(tender_id, lot_id, positions_file_path)
    
    log.info(f"Запущена AI обработка для {tender_id}_{lot_id}, Celery task: {celery_task.id}")
    
    return {
        "task_id": celery_task.id,
        "tender_id": tender_id,
        "lot_id": lot_id,
        "message": "AI обработка позиций запущена"
    }


@app.get("/celery-tasks/{task_id}/status", tags=["AI Processing"])
async def get_celery_task_status(task_id: str):
    """
    Возвращает статус Celery задачи по ее ID.
    """
    try:
        task_result = celery_app.AsyncResult(task_id)
        
        if task_result.state == 'PENDING':
            response = {
                'state': task_result.state,
                'status': 'Task is waiting to be processed'
            }
        elif task_result.state == 'PROCESSING':
            response = {
                'state': task_result.state,
                'status': 'Task is being processed',
                'meta': task_result.info
            }
        elif task_result.state == 'SUCCESS':
            response = {
                'state': task_result.state,
                'status': 'Task completed successfully',
                'result': task_result.result
            }
        else:  # FAILURE
            response = {
                'state': task_result.state,
                'status': 'Task failed',
                'error': str(task_result.info)
            }
        
        return response
        
    except Exception as e:
        log.error(f"Ошибка получения статуса задачи {task_id}: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при получении статуса задачи")


@app.get("/celery-workers/status", tags=["Monitoring"])
async def get_celery_workers_status():
    """
    Возвращает статус всех активных Celery воркеров.
    """
    try:
        # Получаем информацию о воркерах
        inspect = celery_app.control.inspect()
        
        active_workers = inspect.active()
        registered_tasks = inspect.registered()
        stats = inspect.stats()
        
        return {
            "active_workers": active_workers or {},
            "registered_tasks": registered_tasks or {},
            "stats": stats or {},
            "total_workers": len(active_workers) if active_workers else 0
        }
        
    except Exception as e:
        log.error(f"Ошибка получения статуса воркеров: {e}")
        return {
            "error": str(e),
            "active_workers": {},
            "total_workers": 0
        }
