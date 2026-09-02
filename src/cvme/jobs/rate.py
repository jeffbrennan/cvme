"""Small, shared rate limiter for polite sequential HTTP access."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    """Maintain a minimum interval between request starts.

    ``clock`` and ``sleep`` are injectable so the timing behavior can be tested
    without making the test suite wait in real time.
    """

    interval_seconds: float
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_request: float | None = field(default=None, init=False)

    def wait(self) -> None:
        now = self.clock()
        if self._last_request is not None:
            remaining = self.interval_seconds - (now - self._last_request)
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self._last_request = now
