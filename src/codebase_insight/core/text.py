"""Small presentation helpers shared by the analysis modules."""

from __future__ import annotations


def human_bytes(size: int) -> str:
    """``1536`` -> ``1.5 KB``."""
    if size < 1024:
        return f"{size} B"
    value = size / 1024
    for unit in ("KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if value >= 100 else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def percent(part: int | float, total: int | float, digits: int = 1) -> str:
    if total <= 0:
        return "-"
    return f"{part / total * 100:.{digits}f}%"


def truncate(value: str, limit: int) -> str:
    """Collapse whitespace and cut on a word-ish boundary."""
    flat = " ".join(value.split())
    if len(flat) <= limit:
        return flat
    return f"{flat[: max(0, limit - 1)].rstrip()}…"


def plural(count: int, singular: str, plural_form: str | None = None) -> str:
    return singular if count == 1 else (plural_form or f"{singular}s")
