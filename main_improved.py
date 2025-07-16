"""
Основной модуль веб-сервиса для обработки тендерных файлов.

Этот модуль запускает FastAPI приложение и определяет следующие API эндпоинты:
- POST /parse-tender/: Принимает XLSX файл, создает фоновую задачу для его
  парсинга и немедленно возвращает ID задачи.
- GET /tasks/{task_id}/status: Позволяет отслеживать статус выполнения
  фоновой задачи (processing, completed, failed).
- GET /health: Проверяет работоспособность сервиса.

Для управления фоновыми задачами используется встроенный механизм BackgroundTasks.
Статусы задач хранятся в памяти (для демонстрационных целей).
"""
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Импорты внутри пакета app
from app.config import settings, validate_required_settings
from app.parse import parse_file
from app.validation import sanitize_filename, validate_upload_file

# Валидация конфигурации при запуске
try:
    validate_required_settings(settings)
except ValueError as e:
    logging.warning(f"Configuration warning: {e}")

# ВАЖНО: Это простое хранилище в памяти. Если вы перезапустите сервер,
# все статусы пропадут. Для продакшена лучше использовать
# более надежное решение, например, Redis или отдельную таблицу в БД.
tasks_db: Dict[str, Dict[str, Any]] = {}

# Настройка FastAPI приложения
app = FastAPI(
    title=settings.app_title,
    description=settings.app_description,
    version=settings.app_version,
    debug=settings.debug,
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Создание директории для загрузок
UPLOAD_DIRECTORY = Path(settings.upload_directory)
UPLOAD_DIRECTORY.mkdir(exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()), format=settings.log_format
)
log = logging.getLogger(__name__)


def run_parsing_in_background(task_id: str, file_path: str) -> None:
    """
    Выполняет парсинг в фоновом режиме и обновляет статус задачи.

    Args:
        task_id: Уникальный идентификатор задачи
        file_path: Путь к файлу для обработки
    """
    log.info(f"Task {task_id}: Обработка файла {file_path} началась в фоне.")
    tasks_db[task_id] = {"status": "processing", "file_path": file_path}
    try:
        parse_file(file_path)
        tasks_db[task_id].update(
            {"status": "completed", "message": "Файл успешно обработан"}
        )
        log.info(f"Task {task_id}: Обработка успешно завершена.")
    except Exception as e:
        log.error(f"Task {task_id}: Произошла ошибка - {e}", exc_info=True)
        tasks_db[task_id].update(
            {
                "status": "failed",
                "error": str(e),
                "message": "Ошибка при обработке файла",
            }
        )
    finally:
        # Очистка временного файла
        try:
            Path(file_path).unlink(missing_ok=True)
            log.info(f"Task {task_id}: Временный файл удален")
        except Exception as e:
            log.warning(f"Task {task_id}: Не удалось удалить временный файл: {e}")


@app.post("/parse-tender/", status_code=202, tags=["Tender Processing"])
async def create_parsing_task(
    background_tasks: BackgroundTasks, file: UploadFile = File(...)
):
    """
    Принимает файл, создает для него уникальную задачу и запускает
    обработку в фоновом режиме, немедленно возвращая ID задачи.

    Args:
        background_tasks: FastAPI background tasks
        file: Загружаемый XLSX файл

    Returns:
        Dict с task_id и сообщением

    Raises:
        HTTPException: При ошибках валидации или сохранения файла
    """
    # Валидация файла
    file_metadata = await validate_upload_file(
        file, settings.max_file_size, settings.allowed_extensions
    )

    task_id = str(uuid.uuid4())
    safe_filename = sanitize_filename(file.filename or "unknown.xlsx")
    temp_file_path = UPLOAD_DIRECTORY / f"{task_id}_{safe_filename}"

    log.info(
        f"Task {task_id}: Получен файл {file.filename} "
        f"(размер: {file_metadata['size']} байт, хэш: {file_metadata['hash'][:8]}...)"
    )

    try:
        # Сохранение файла
        with open(temp_file_path, "wb") as buffer:
            await file.seek(0)  # Убеждаемся, что начинаем с начала файла
            shutil.copyfileobj(file.file, buffer)

        log.info(f"Task {task_id}: Файл сохранен в: {temp_file_path}")

    except Exception as e:
        log.error(f"Task {task_id}: Не удалось сохранить файл: {e}")
        raise HTTPException(
            status_code=500, detail="Не удалось сохранить файл на сервере."
        )
    finally:
        file.file.close()

    # Добавление задачи в фоновую обработку
    background_tasks.add_task(run_parsing_in_background, task_id, str(temp_file_path))

    # Сохранение начального статуса
    tasks_db[task_id] = {
        "status": "queued",
        "file_name": safe_filename,
        "file_size": file_metadata["size"],
        "file_hash": file_metadata["hash"],
        "created_at": str(uuid.uuid1().time),
        "message": "Задача добавлена в очередь на обработку",
    }

    return {
        "task_id": task_id,
        "message": "Задача по обработке файла принята.",
        "file_info": {
            "name": safe_filename,
            "size": file_metadata["size"],
            "hash": file_metadata["hash"][:16],  # Короткий хэш для отображения
        },
    }


@app.get("/tasks/{task_id}/status", tags=["Task Status"])
async def get_task_status(task_id: str):
    """
    Возвращает текущий статус задачи по ее ID.

    Args:
        task_id: Уникальный идентификатор задачи

    Returns:
        Dict со статусом задачи

    Raises:
        HTTPException: Если задача не найдена
    """
    task = tasks_db.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача с таким ID не найдена.")

    # Не возвращаем file_path в публичном API
    public_task = {k: v for k, v in task.items() if k != "file_path"}
    return public_task


@app.get("/tasks", tags=["Task Status"])
async def list_tasks(limit: int = 50):
    """
    Возвращает список последних задач.

    Args:
        limit: Количество задач для возврата (максимум 100)

    Returns:
        Dict со списком задач
    """
    limit = min(limit, 100)  # Ограничение на количество задач

    # Сортировка по времени создания (новые первыми)
    sorted_tasks = sorted(
        tasks_db.items(),
        key=lambda x: x[1].get("created_at", "0"),
        reverse=True,
    )

    limited_tasks = dict(sorted_tasks[:limit])

    # Убираем file_path из публичного API
    public_tasks = {
        task_id: {k: v for k, v in task.items() if k != "file_path"}
        for task_id, task in limited_tasks.items()
    }

    return {"tasks": public_tasks, "total": len(tasks_db), "showing": len(public_tasks)}


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """
    Комплексная проверка работоспособности сервиса.

    Returns:
        Dict со статусом сервиса и дополнительной информацией
    """
    health_info = {
        "status": "ok",
        "version": settings.app_version,
        "tasks": {
            "total": len(tasks_db),
            "processing": len(
                [t for t in tasks_db.values() if t.get("status") == "processing"]
            ),
            "completed": len(
                [t for t in tasks_db.values() if t.get("status") == "completed"]
            ),
            "failed": len(
                [t for t in tasks_db.values() if t.get("status") == "failed"]
            ),
        },
        "config": {
            "max_file_size_mb": settings.max_file_size / (1024 * 1024),
            "allowed_extensions": settings.allowed_extensions,
            "upload_directory": str(UPLOAD_DIRECTORY),
            "debug_mode": settings.debug,
        },
    }

    # Проверка доступности директории загрузок
    if not UPLOAD_DIRECTORY.exists():
        health_info["status"] = "warning"
        health_info["warnings"] = ["Upload directory does not exist"]

    return health_info


@app.get("/", tags=["Root"])
async def root():
    """Корневой эндпоинт с информацией о сервисе."""
    return {
        "service": settings.app_title,
        "version": settings.app_version,
        "description": settings.app_description,
        "docs_url": "/docs",
        "health_url": "/health",
    }