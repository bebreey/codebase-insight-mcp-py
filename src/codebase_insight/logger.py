"""stderr-only diagnostics.

``stdout`` is the JSON-RPC channel for a stdio MCP server: a single stray
``print`` corrupts the frame stream and the client drops the connection. Every
diagnostic path in this project goes through here instead.
"""

from __future__ import annotations

import json
import sys

from .config import debug_enabled

PREFIX = "[codebase-insight-py]"


def _fmt(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, BaseException):
        return f"{type(value).__name__}: {value}"
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(value)


def _write(parts: tuple[object, ...]) -> None:
    try:
        sys.stderr.write(f"{PREFIX} {' '.join(_fmt(p) for p in parts)}\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        # stderr closed; nothing sensible left to do.
        pass


def debug(*parts: object) -> None:
    """Verbose diagnostics, enabled with ``CBI_DEBUG=1``."""
    if debug_enabled():
        _write(parts)


def warn(*parts: object) -> None:
    """Always-on diagnostics for degraded paths."""
    _write(parts)
