"""Bounded response handling for optional Office-to-PDF conversions."""
from __future__ import annotations


class OutputTooLarge(ValueError):
    """Raised when a conversion response exceeds its configured byte budget."""


class InvalidPdfOutput(ValueError):
    """Raised when the upstream response is not a PDF."""


async def read_limited_pdf_response(response, max_bytes: int) -> bytes:
    """Read an HTTP response incrementally, enforcing its size before buffering it all."""
    if max_bytes < 5:
        raise ValueError("max_bytes must be at least five bytes")

    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise OutputTooLarge
        except ValueError as exc:
            if isinstance(exc, OutputTooLarge):
                raise
            # Ignore malformed Content-Length; the streaming limit remains authoritative.

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            raise OutputTooLarge
        chunks.append(chunk)

    body = b"".join(chunks)
    if not body.startswith(b"%PDF-"):
        raise InvalidPdfOutput
    return body
