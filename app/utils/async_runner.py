# app/utils/async_runner.py

import asyncio
import threading
from typing import Any, Coroutine


def run_async(coro: Coroutine[Any, Any, Any]) -> Any:
    """
    Безопасно запускает async-код из синхронного контекста.

    Решает проблему запуска async функций в синхронном коде, особенно
    когда event loop может быть уже запущен (например, в Celery воркерах).

    Логика работы:
    --------------
    1. Проверяет, запущен ли event loop в текущем потоке
    2. Если НЕТ → использует asyncio.run() (стандартный способ)
    3. Если ДА → создает отдельный поток с новым event loop

    Args:
        coro: Coroutine объект (результат вызова async функции)
            Например: run_async(my_async_func())

    Returns:
        Any: Результат выполнения корутины

    Raises:
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

    Note:
        Создание нового потока имеет overhead (~1-2ms), но это приемлемо
        для большинства случаев. Для высокочастотных вызовов рассмотрите
        миграцию на полностью async архитектуру.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Нет event loop → можно спокойно asyncio.run
        return asyncio.run(coro)

    # Event loop уже есть → запускаем в отдельном потоке
    result: Any = None
    error: Exception | None = None

    def runner():
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except Exception as e:
            error = e

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error

    return result
