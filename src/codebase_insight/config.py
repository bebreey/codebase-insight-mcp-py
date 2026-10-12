"""Runtime configuration, read from the environment on every access.

Mirrors the variable names of the TypeScript implementation so the two servers
can be pointed at the same host configuration.
"""

from __future__ import annotations

import os
from pathlib import Path


def _positive_int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        return fallback
    return value if value > 0 else fallback


def max_files() -> int:
    """Hard ceiling on files collected by a single walk."""
    return _positive_int("CBI_MAX_FILES", 20_000)


def max_depth() -> int:
    """Directory recursion limit, measured from the analysis root."""
    return _positive_int("CBI_MAX_DEPTH", 12)


def max_file_bytes() -> int:
    """Files larger than this are measured but never read."""
    return _positive_int("CBI_MAX_FILE_BYTES", 2 * 1024 * 1024)


def debug_enabled() -> bool:
    raw = os.environ.get("CBI_DEBUG", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def default_root() -> Path:
    """Directory analysed when a tool call omits ``path``."""
    configured = os.environ.get("CBI_DEFAULT_ROOT")
    if configured is not None and configured.strip() != "":
        return Path(configured.strip())
    return Path.cwd()


def allowed_roots() -> list[Path] | None:
    """Optional allow-list from ``CBI_ROOTS`` (``,`` or ``;`` separated)."""
    raw = os.environ.get("CBI_ROOTS")
    if raw is None or raw.strip() == "":
        return None
    parts = [part.strip() for part in raw.replace(";", ",").split(",")]
    resolved = [Path(part).resolve() for part in parts if part]
    return resolved or None
