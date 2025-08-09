"""Основной модуль FastAPI-сервиса для асинхронной обработки тендерных XLSX файлов.

Сервис предоставляет API для загрузки и постановки в очередь задач обработки
тендерных файлов, с возможностью включения AI-анализа. Статусы и прогресс
хранятся в Redis, а обработка выполняется воркерами Celery.

Основные возможности:
- Загрузка XLSX-файла и запуск фоновой задачи в Celery с единым task_id.
- Получение статуса задачи (детально из Redis или общая стадия из Celery backend).
- Проверка состояния сервиса и воркеров.
- Безопасный запуск AI-обработки позиций по идентификатору файла.
- Централизованная конфигурация через переменные окружения и Pydantic Settings.
"""

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiofiles
import redis.asyncio as aioredis
from anyio import to_thread
from celery.result import AsyncResult
from dotenv import load_dotenv
from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.responses import JSONResponse

from app.celery_app import celery_app
from app.utils.file_validation import validate_excel_upload_file
from app.workers.gemini.tasks import process_tender_positions
from app.workers.parser.tasks import run_parsing_in_background

load_dotenv()


# --------------------
# Settings & Logging
# --------------------
class Settings(BaseSettings):
    """Конфигурация сервиса: пути, Redis, TTL статусов, ключи AI и версия приложения."""

    app_name: str = "Tender Parser Service"
    version: str = "2.1.0"

    base_dir: Path = Path(__file__).resolve().parent
    upload_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "temp_uploads")
    positions_dir: Path = Field(default_factory=lambda: Path(__file__).resolve().parent / "positions")

    redis_url: str | None = os.getenv("REDIS_URL")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", 6379))
    redis_password: str | None = os.getenv("REDIS_PASSWORD")

    status_ttl_seconds: int = int(os.getenv("STATUS_TTL_SECONDS", "7200"))
    google_api_key: str | None = os.getenv("GOOGLE_API_KEY")

    # Pydantic v2 стиль конфигурации:
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",  # чтобы не падать на лишних переменных окружения
    )


S = Settings()
S.upload_dir.mkdir(parents=True, exist_ok=True)
S.positions_dir.mkdir(parents=True, exist_ok=True)

log_level = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler()],  # Отдаём логи в stdout — лучше для контейнеров
    force=True,
)
logger = logging.getLogger("api")


# --------------------
# Redis helper (async)
# --------------------
async def make_redis_async():
    if S.redis_url:
        return aioredis.from_url(
            S.redis_url,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
            health_check_interval=30,
        )
    return aioredis.Redis(
        host=S.redis_host,
        port=S.redis_port,
        password=S.redis_password,
        decode_responses=True,
        socket_timeout=3,
        socket_connect_timeout=3,
        health_check_interval=30,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan-хендлер для старта/остановки приложения.

    При старте:
        - создаёт асинхронный клиент Redis и кладёт его в app.state.redis.
    При остановке:
        - корректно закрывает соединение с Redis.
    """
    app.state.redis = await make_redis_async()
    try:
        yield
    finally:
        # shutdown
        try:
            await app.state.redis.close()
        except Exception:
            pass


app = FastAPI(
    title=S.app_name,
    description="Сервис для асинхронной обработки тендерных XLSX файлов.",
    version=S.version,
    lifespan=lifespan,
)


class ParseAccepted(BaseModel):
    """Ответ при успешной постановке файла в очередь.

    Attributes:
        task_id: Единый идентификатор задачи (такой же у Celery).
        message: Человекочитаемое уведомление.
        enable_ai: Признак включения AI-режима.
        filename: Имя загруженного файла.
    """

    task_id: str
    message: str
    enable_ai: bool
    filename: str


class TaskStatus(BaseModel):
    """Унифицированный статус задачи для клиента.

    Attributes:
        state: Текущее состояние Celery (PENDING/STARTED/…).
        status: Краткое описание стадии/статуса.
        result: Результат при SUCCESS (если есть).
        error: Текст ошибки при FAILURE (если есть).
    """

    state: str
    status: str
    result: dict | None = None
    error: str | None = None


class PositionsRequest(BaseModel):
    """Запрос на AI-обработку файла позиций по безопасному идентификатору.

    Attributes:
        tender_id: Идентификатор тендера.
        lot_id: Идентификатор лота.
        file_id: Безопасный ID файла (без абсолютных путей).
    """

    tender_id: str
    lot_id: str
    file_id: str  # безопасный идентификатор без путей


@app.post("/parse-tender/", status_code=202, tags=["Tender Processing"], response_model=ParseAccepted)
async def create_parsing_task_celery(
    file: UploadFile = File(...),
    enable_ai: bool = Form(default=False),
):
    """Загружает XLSX и ставит фоновую задачу на парсинг.

    - Валидирует и сохраняет файл во временную директорию.
    - Создаёт единый task_id и передаёт его Celery (apply_async(task_id=...)).
    - Возвращает клиенту task_id и базовую информацию.
    """
    external_id = str(uuid.uuid4())
    temp_file_path = S.upload_dir / f"{external_id}.xlsx"

    try:
        # валидация + чтение в память (ваш валидатор может делать и MIME/размерные проверки)
        file_bytes = await validate_excel_upload_file(file)

        # асинхронно пишем на диск
        async with aiofiles.open(temp_file_path, "wb") as f:
            await f.write(file_bytes)

        # единый task_id для клиента и Celery
        run_parsing_in_background.apply_async(
            args=[external_id, str(temp_file_path), enable_ai],
            task_id=external_id,
            headers={"x-request-id": external_id},  # трейсинг (опционально)
        )

        logger.info("Task %s queued (AI=%s)", external_id, enable_ai)
        return ParseAccepted(
            task_id=external_id,
            message=f"Задача по обработке файла принята ({'с AI' if enable_ai else 'без AI'})",
            enable_ai=enable_ai,
            filename=file.filename,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Upload error: %s", e)
        if temp_file_path.exists():
            try:
                await to_thread.run_sync(temp_file_path.unlink)
            except Exception:
                logger.warning("Temp cleanup failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Ошибка при загрузке файла")
    finally:
        # закрыть файловый дескриптор UploadFile
        try:
            await file.close()
        except Exception:
            pass


@app.get("/tasks/{task_id}/status", tags=["Task Status"], response_model=TaskStatus)
async def get_unified_status(task_id: str):
    """Возвращает статус задачи.

    Сначала пытается получить детальный статус из Redis (progress/stage),
    при отсутствии — берёт состояние из Celery result backend.
    """
    try:
        # сначала — детальный статус из Redis, если есть (async клиент)
        status_key = f"task_status:{task_id}"
        try:
            status_json = await app.state.redis.get(status_key)
        except Exception as e:
            logger.warning("Redis недоступен: %s", e)
            status_json = None

        if status_json:
            payload = json.loads(status_json)
            # нормируем ответ
            return TaskStatus(
                state=payload.get("status", "processing").upper(),
                status=payload.get("stage", payload.get("status", "processing")),
                result=None,
                error=payload.get("error"),
            )

        # если нет — статус из Celery backend по тому же UUID (в тред)
        task_result: AsyncResult = await to_thread.run_sync(celery_app.AsyncResult, task_id)
        state = await to_thread.run_sync(lambda: task_result.state)
        info = await to_thread.run_sync(lambda: task_result.info)
        result = await to_thread.run_sync(lambda: task_result.result)

        if state == "PENDING" and not result:
            raise HTTPException(status_code=404, detail="Task not found")

        if state == "PENDING":
            return TaskStatus(state=state, status="Task is waiting to be processed")
        elif state == "STARTED":
            return TaskStatus(state=state, status="Task is being processed")
        elif state == "SUCCESS":
            return TaskStatus(state=state, status="Task completed successfully", result=result)
        elif state == "FAILURE":
            return TaskStatus(state=state, status="Task failed", error=str(info))
        else:
            return TaskStatus(state=state, status="Unknown state")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Status check error for %s: %s", task_id, e)
        raise HTTPException(status_code=500, detail="Ошибка при получении статуса задачи")


@app.get("/health", tags=["Monitoring"])
async def health_check():
    """Простой health-check.

    Проверяет доступность Redis (PING) и количество активных воркеров Celery.
    """
    redis_ok = False
    workers = 0

    try:
        redis_ok = bool(await app.state.redis.ping())
    except Exception:
        redis_ok = False

    try:
        # celery inspect.* блокирующие — уводим в тред
        pong = await to_thread.run_sync(celery_app.control.ping, timeout=1)
        workers = len(pong) if pong else 0
    except Exception:
        workers = 0

    return {"status": "ok", "redis": redis_ok, "celery_workers": workers}


@app.post("/process-positions/", status_code=202, tags=["AI Processing"])  # обрат-совместимость, но безопаснее
async def process_single_positions_file(payload: PositionsRequest = Body(...)):
    """Безопасно запускает AI-обработку файла позиций.

    Принимает `file_id`, резолвит путь внутри директории позиций,
    валидирует наличие файла и ставит задачу в Celery.
    """
    logger.info(
        "AI positions processing request: tender_id=%s lot_id=%s file_id=%s",
        payload.tender_id,
        payload.lot_id,
        payload.file_id,
    )

    if not S.google_api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY не настроен")

    # Безопасное формирование пути по file_id
    safe_path = (S.positions_dir / f"{payload.file_id}.json").resolve()
    if not safe_path.is_file() or S.positions_dir not in safe_path.parents:
        raise HTTPException(status_code=404, detail="Файл позиций не найден")

    celery_task = process_tender_positions.apply_async(
        args=[payload.tender_id, payload.lot_id, str(safe_path), S.google_api_key]
    )

    return JSONResponse(
        status_code=202,
        content={
            "task_id": celery_task.id,
            "tender_id": payload.tender_id,
            "lot_id": payload.lot_id,
            "message": "AI обработка позиций запущена",
        },
    )


@app.get("/celery-workers/status", tags=["Monitoring"])
async def get_celery_workers_status():
    """Возвращает информацию о воркерах Celery (active/registered/stats).

    Вызовы inspect.* блокирующие, поэтому выполняются в пуле потоков.
    """
    try:
        inspect = celery_app.control.inspect()
        active_workers = await to_thread.run_sync(inspect.active)
        registered_tasks = await to_thread.run_sync(inspect.registered)
        stats = await to_thread.run_sync(inspect.stats)

        return {
            "active_workers": active_workers or {},
            "registered_tasks": registered_tasks or {},
            "stats": stats or {},
            "total_workers": len(active_workers) if active_workers else 0,
        }

    except Exception as e:
        logger.exception("Celery workers status error: %s", e)
        return {"error": str(e), "active_workers": {}, "total_workers": 0}
