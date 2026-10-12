"""Fixture module holding one deliberately fake credential-shaped literal.

``notarealvalue12345678`` matches the generic "credential assigned to a
secret-looking name" rule and nothing else, so the scanner has a stable and
entirely synthetic input.
"""

from __future__ import annotations

API_KEY = "notarealvalue12345678"
SERVICE_TIMEOUT_SECONDS = 5


def load_config(endpoint: str) -> dict[str, object]:
    """Return a minimal configuration mapping."""
    return {"endpoint": endpoint, "timeout": SERVICE_TIMEOUT_SECONDS}
