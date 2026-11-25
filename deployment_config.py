"""Deployment configuration validation helpers."""
from __future__ import annotations

from urllib.parse import urlsplit


def validate_cors_origins(environment: str, origins: list[str]) -> list[str]:
    """Reject permissive wildcard CORS when the service is explicitly production."""
    normalized = [str(origin).strip() for origin in origins if str(origin).strip()]
    if str(environment or "development").strip().lower() == "production":
        if not normalized or any("*" in origin for origin in normalized):
            raise ValueError(
                "CORS_ORIGINS must contain explicit trusted origins in production; wildcard is forbidden."
            )
        validated = []
        for origin in normalized:
            parsed = urlsplit(origin)
            is_local_http = parsed.scheme == "http" and parsed.hostname in {
                "localhost", "127.0.0.1", "::1"
            }
            if (
                not parsed.netloc
                or (parsed.scheme != "https" and not is_local_http)
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "Production CORS origins must be HTTPS origins without paths, credentials, queries, or fragments."
                )
            validated.append(f"{parsed.scheme}://{parsed.netloc}")
        return validated
    return normalized
