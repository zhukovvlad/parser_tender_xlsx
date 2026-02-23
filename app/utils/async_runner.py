# app/utils/async_runner.py

import asyncio
import concurrent.futures
import logging
import os
import threading
from typing import Any, Coroutine, Optional

_logger = logging.getLogger(__name__)

# Persistent event loop per process.
# Avoids the problem of asyncio.run() creating and destroying loops,
# which breaks asyncpg connection pools bound to a previous loop.
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()
_pid: int | None = None


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """
    Returns a persistent event loop running in a background thread.

    Creates a new loop if:
    - No loop exists yet
    - The current process is a fork (PID changed)
    - The loop was closed

    Thread-safe via threading.Lock.
    """
    global _loop, _thread, _pid
    with _lock:
        current_pid = os.getpid()
        if (
            _loop is not None
            and _pid == current_pid
            and not _loop.is_closed()
            and _thread is not None
            and _thread.is_alive()
        ):
            return _loop

        # Cleanup old loop if same PID (closed loop, not fork).
        # After fork the old loop belongs to the parent — do NOT touch it.
        if _loop is not None and _pid == current_pid:
            try:
                if not _loop.is_closed():
                    _loop.call_soon_threadsafe(_loop.stop)
                    if _thread is not None and _thread.is_alive():
                        _thread.join(timeout=5)
                    _loop.close()
            except Exception:
                _logger.debug(
                    "Error during old event loop cleanup", exc_info=True
                )

        # New process (fork) or stale loop — create fresh
        _loop = asyncio.new_event_loop()
        _pid = current_pid
        _thread = threading.Thread(
            target=_loop.run_forever,
            daemon=True,
            name="async_runner",
        )
        _thread.start()
        return _loop


def run_async(
    coro: Coroutine[Any, Any, Any],
    timeout: Optional[float] = None,
) -> Any:
    """
    Безопасно запускает async-код из синхронного контекста.

    Использует persistent event loop в фоновом потоке, что решает
    проблему asyncpg/aiohttp pools, привязанных к event loop:
    - asyncio.run() создаёт и ЗАКРЫВАЕТ loop каждый раз
    - Pools, созданные в одном loop, не работают в другом
    - Persistent loop живёт всё время жизни процесса

    Fork-safe: при fork (Celery prefork) создаётся новый loop
    для дочернего процесса (определяется по PID).

    Args:
        coro: Coroutine объект (результат вызова async функции)
            Например: run_async(my_async_func())
        timeout: Максимальное время ожидания результата (секунды).
            None — ждать бесконечно (поведение по умолчанию).

    Returns:
        Any: Результат выполнения корутины

    Raises:
        TimeoutError: Если корутина не завершилась за timeout секунд.
        Exception: Пробрасывает любые исключения из корутины

    Example:
        >>> async def fetch_data():
        ...     return {"status": "ok"}
        >>> result = run_async(fetch_data())
        >>> print(result)  # {"status": "ok"}

    Use Cases:
        - Вызов async Go API из синхронных Celery задач
        - Интеграция async библиотек в синхронный код
        - Работа с async context managers в синхронных функциях
    """
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise TimeoutError(
            f"run_async: coroutine did not complete within {timeout}s"
        ) from None
