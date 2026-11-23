"""Small bounded in-memory sliding-window rate limiter for a single API process."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque


class SlidingWindowRateLimiter:
    """Thread-safe limiter with bounded key storage and monotonic time."""

    def __init__(self, max_keys: int = 4096) -> None:
        if max_keys < 1:
            raise ValueError("max_keys must be positive")
        self.max_keys = max_keys
        self._events: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: float, now: float | None = None) -> bool:
        if limit < 1 or window_seconds <= 0:
            raise ValueError("limit and window_seconds must be positive")
        current = time.monotonic() if now is None else float(now)
        normalized_key = str(key or "unknown")
        with self._lock:
            events = self._events.get(normalized_key)
            if events is None:
                events = deque()
                self._events[normalized_key] = events
            else:
                self._events.move_to_end(normalized_key)

            while events and current - events[0] >= window_seconds:
                events.popleft()

            if len(events) >= limit:
                return False

            events.append(current)
            if len(self._events) > self.max_keys:
                for old_key, old_events in list(self._events.items()):
                    if not old_events or current - old_events[-1] >= window_seconds:
                        self._events.pop(old_key, None)
                while len(self._events) > self.max_keys:
                    self._events.popitem(last=False)
            return True
