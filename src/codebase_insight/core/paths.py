"""Analysis-target validation.

Every tool takes an optional ``path``. Left unchecked that turns an MCP server
into an arbitrary-directory reader for whatever model is driving it.
"""

from __future__ import annotations

from pathlib import Path

from .. import config


class WorkspaceError(Exception):
    """The caller asked for something that cannot be analysed."""


def is_inside(parent: Path, child: Path) -> bool:
    """True when ``child`` is ``parent`` or lives underneath it."""
    try:
        return child == parent or child.is_relative_to(parent)
    except ValueError:  # pragma: no cover - only on exotic path types
        return False


def resolve_workspace_root(raw: str | None, fallback: Path) -> Path:
    """Resolve and validate the analysis target.

    ``Path.resolve(strict=True)`` follows symlinks before the containment check,
    so a symlink cannot be used to escape ``CBI_ROOTS``.
    """
    candidate = Path(raw).expanduser() if raw else fallback

    try:
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        raise WorkspaceError(f"Path does not exist or is not readable: {candidate}") from exc

    if not resolved.is_dir():
        raise WorkspaceError(f"Path is not a directory: {resolved}")

    roots = config.allowed_roots()
    if roots is not None and not any(is_inside(root, resolved) for root in roots):
        allowed = ", ".join(str(root) for root in roots)
        raise WorkspaceError(f"Path is outside the directories allowed by CBI_ROOTS ({allowed}): {resolved}")

    return resolved


def to_rel(root: Path, path: Path) -> str:
    """Forward-slashed path relative to ``root``."""
    return path.relative_to(root).as_posix()
