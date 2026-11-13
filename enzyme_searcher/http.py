"""Retries with exponential backoff and a thread-safe rate limiter."""
from __future__ import annotations

import functools
import logging
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)


def with_retries(attempts: int = 5, base_delay: float = 1.0, max_delay: float = 60.0,
                 exceptions: tuple[type[BaseException], ...] = (Exception,),
                 sleep: Callable[[float], None] | None = None):
    """Retry the decorated call, waiting base_delay * 2^n seconds (capped) between attempts."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        log.error("%s failed after %d attempts: %s", fn.__name__, attempt, exc)
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                    log.warning("%s failed (%s); retry %d/%d in %.1fs",
                                fn.__name__, exc, attempt, attempts - 1, delay)
                    (sleep or time.sleep)(delay)
        return wrapper
    return decorator


class RateLimiter:
    """Allow at most `per_second` calls per second across threads."""

    def __init__(self, per_second: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = 1.0 / per_second
        self.clock, self.sleep = clock, sleep
        self._last = -1e9
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self.clock()
            remaining = self._last + self.interval - now
            if remaining > 0:
                self.sleep(remaining)
                now += remaining
            self._last = now
