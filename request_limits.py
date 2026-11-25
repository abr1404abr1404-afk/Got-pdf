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


def validate_pixel_dimensions(width: int, height: int, max_pixels: int) -> int:
    """Return the decoded pixel count or reject unsafe image dimensions."""
    if width < 1 or height < 1 or max_pixels < 1:
        raise ValueError("image dimensions and pixel limit must be positive")
    pixels = int(width) * int(height)
    if pixels > max_pixels:
        raise ValueError("image exceeds the configured pixel limit")
    return pixels



class RequestBodyTooLarge(Exception):
    """Raised when an HTTP request body exceeds the configured byte limit."""


class RequestBodyLimitMiddleware:
    """Bound the complete ASGI request body, including chunked multipart uploads.

    UploadFile limits checked inside route handlers are too late to protect the
    multipart parser itself. This middleware rejects oversized Content-Length
    values early and also counts streamed chunks when the header is absent or
    inaccurate. It does not buffer request bodies.
    """

    def __init__(self, app, max_body_bytes: int) -> None:
        if max_body_bytes < 1:
            raise ValueError("max_body_bytes must be positive")
        self.app = app
        self.max_body_bytes = int(max_body_bytes)

    @staticmethod
    async def _reject(send) -> None:
        body = '{"detail":"حجم الطلب يتجاوز الحد المسموح."}'.encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        raw_length = headers.get(b"content-length")
        if raw_length:
            try:
                declared_length = int(raw_length)
            except (TypeError, ValueError):
                declared_length = -1
            if declared_length > self.max_body_bytes:
                await self._reject(send)
                return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise RequestBodyTooLarge()
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if not response_started:
                await self._reject(send)
