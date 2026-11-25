"""Deployment configuration validation helpers."""
from __future__ import annotations


def validate_cors_origins(environment: str, origins: list[str]) -> list[str]:
    """Reject permissive wildcard CORS when the service is explicitly production."""
    normalized = [str(origin).strip() for origin in origins if str(origin).strip()]
    if str(environment or "development").strip().lower() == "production":
        if not normalized or "*" in normalized:
            raise ValueError(
                "CORS_ORIGINS must contain explicit trusted origins in production; wildcard is forbidden."
            )
    return normalized
