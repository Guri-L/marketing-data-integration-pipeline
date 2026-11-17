"""Retry with exponential backoff and jitter for transient failures."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from functools import wraps
from typing import TypeVar

from .exceptions import TransientExtractionError
from .logging_utils import get_logger

T = TypeVar("T")
log = get_logger("retry")


def retry(
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    retry_on: tuple[type[BaseException], ...] = (TransientExtractionError,),
    sleep: Callable[[float], None] | None = None,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Retry ``retry_on`` errors; anything else propagates immediately."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except retry_on as exc:
                    if attempt == attempts:
                        log.error("%s failed after %d attempts: %s", func.__name__, attempts, exc)
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                    delay *= random.uniform(0.5, 1.0)
                    log.warning(
                        "%s attempt %d/%d failed (%s); retrying in %.1fs",
                        func.__name__, attempt, attempts, exc, delay,
                    )
                    (sleep or time.sleep)(delay)
            raise AssertionError("unreachable")  # pragma: no cover

        return wrapper

    return decorator
