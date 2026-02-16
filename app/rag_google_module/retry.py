"""Retry decorator for API calls."""

import asyncio
from functools import wraps
from typing import Callable, TypeVar

from google.genai import errors

T = TypeVar("T")


def retry_on_server_error(max_attempts: int = 3):
    """Retry decorator for Google API ServerError."""
    
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except errors.ServerError as e:
                    if attempt == max_attempts - 1:
                        raise
                    await asyncio.sleep(2 * (attempt + 1))
            return None
        return wrapper
    return decorator
