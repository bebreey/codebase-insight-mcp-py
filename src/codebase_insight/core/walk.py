"""Directory traversal.

Unlike the TypeScript implementation — which shipped a built-in ignore list and
documented "does not parse .gitignore" as a limitation — this version honours
``.gitignore`` for real, including files nested in subdirectories, using
``pathspec`` (the same pattern engine ``pre-commit`` uses).

Precedence follows git: the deepest matching ``.gitignore`` wins, so the specs
are consulted newest-first and the first match decides.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pathspec import PathSpec

from .. import config
from ..logger import debug
from .languages import is_generated
from .paths import to_rel

GITIGNORE_NAME = ".gitignore"

# PathSpec factory registered by pathspec. The concrete
# ``GitWildMatchPattern`` class is deprecated in favour of this name.
GITIGNORE_FACTORY = "gitignore"

# Directories that are never worth descending into. All lowercase; the
# comparison lowercases the entry name so `Pods`/`Obj` behave the same
# everywhere.
DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        # version control
        ".git",
        ".hg",
        ".svn",
        ".jj",
        # python
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
        "site-packages",
        ".pytype",
        "build",
        "dist",
        # javascript / typescript
        "node_modules",
        "out",
        "coverage",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".turbo",
        ".parcel-cache",
        ".vite",
        ".angular",
        ".astro",
        ".output",
        ".vercel",
        ".netlify",
        # jvm / native / package managers
        "target",
        ".gradle",
        ".mvn",
        "obj",
        "vendor",
        ".terraform",
        ".dart_tool",
        ".stack-work",
        "pods",
        "deriveddata",
        ".bundle",
        "bower_components",
        ".cargo",
        # editors / caches
        ".idea",
        ".vscode",
        ".cache",
        ".sass-cache",
        ".eslintcache",
        # scratch
        "tmp",
        "temp",
        "logs",
        ".tmp",
    }
)


@dataclass(frozen=True, slots=True)
class WalkedFile:
    """A file collected during the walk."""

    path: Path
    rel: str
    size: int
    depth: int


@dataclass(slots=True)
class WalkResult:
    root: Path
    files: list[WalkedFile] = field(default_factory=list)
    directories_visited: int = 0
    entries_skipped: int = 0
    truncated: bool = False
    unreadable: list[str] = field(default_factory=list)
    gitignore_files: list[str] = field(default_factory=list)
    ignore_patterns: tuple[str, ...] = ()


def _load_gitignore(directory: Path, base_rel: str) -> tuple[str, PathSpec[Any]] | None:
    candidate = directory / GITIGNORE_NAME
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    spec = PathSpec.from_lines(GITIGNORE_FACTORY, text.splitlines())
    return (base_rel, spec)


def _matches_extra(rel: str, name: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if pattern in (rel, name):
            return True
        if rel.startswith(f"{pattern}/"):
            return True
    return False


def _matches_gitignore(rel: str, is_dir: bool, specs: list[tuple[str, PathSpec[Any]]]) -> bool:
    probe = f"{rel}/" if is_dir else rel
    for base, spec in reversed(specs):
        if base == "":
            if spec.match_file(probe):
                return True
            continue
        if not rel.startswith(f"{base}/"):
            continue
        sub = rel[len(base) + 1 :]
        if sub == "":
            continue
        if spec.match_file(f"{sub}/" if is_dir else sub):
            return True
    return False


def walk(
    root: Path,
    *,
    max_depth: int | None = None,
    max_files: int | None = None,
    extra_ignore: tuple[str, ...] = (),
    respect_gitignore: bool = True,
) -> WalkResult:
    """Breadth-first walk with ``.gitignore`` support. Symlinks are never followed."""
    depth_limit = config.max_depth() if max_depth is None else max_depth
    file_limit = config.max_files() if max_files is None else max_files
    extra = tuple(pattern for pattern in extra_ignore if pattern)

    result = WalkResult(root=root, ignore_patterns=extra)
    specs: list[tuple[str, PathSpec[Any]]] = []

    if respect_gitignore:
        root_spec = _load_gitignore(root, "")
        if root_spec is not None:
            specs.append(root_spec)
            result.gitignore_files.append(GITIGNORE_NAME)

    queue: deque[tuple[Path, int]] = deque([(root, 0)])

    while queue:
        if len(result.files) >= file_limit:
            result.truncated = True
            break

        directory, depth = queue.popleft()
        if depth > depth_limit:
            result.truncated = True
            continue

        result.directories_visited += 1

        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            result.unreadable.append(to_rel(root, directory) if directory != root else ".")
            result.entries_skipped += 1
            continue

        for entry in entries:
            rel = to_rel(root, entry)

            if entry.is_symlink():
                result.entries_skipped += 1
                continue

            try:
                is_dir = entry.is_dir()
            except OSError:
                result.entries_skipped += 1
                continue

            if _matches_extra(rel, entry.name, extra):
                result.entries_skipped += 1
                continue

            if is_dir:
                if entry.name.lower() in DEFAULT_IGNORED_DIRS:
                    result.entries_skipped += 1
                    continue
                if respect_gitignore and _matches_gitignore(rel, True, specs):
                    result.entries_skipped += 1
                    continue
                nested = _load_gitignore(entry, rel) if respect_gitignore else None
                if nested is not None:
                    specs.append(nested)
                    result.gitignore_files.append(f"{rel}/{GITIGNORE_NAME}")
                queue.append((entry, depth + 1))
                continue

            try:
                is_file = entry.is_file()
            except OSError:
                is_file = False
            if not is_file:
                result.entries_skipped += 1
                continue

            if _matches_gitignore(rel, False, specs):
                result.entries_skipped += 1
                continue

            if is_generated(entry.name):
                result.entries_skipped += 1
                continue

            try:
                size = entry.stat().st_size
            except OSError:
                result.entries_skipped += 1
                continue

            if len(result.files) >= file_limit:
                result.truncated = True
                break

            result.files.append(WalkedFile(path=entry, rel=rel, size=size, depth=depth + 1))

    result.files.sort(key=lambda item: item.rel)
    debug(
        f"walk {root}: {len(result.files)} files, "
        f"{len(result.gitignore_files)} .gitignore file(s), truncated={result.truncated}"
    )
    return result


def load_ignore_file(root: Path) -> tuple[str, ...]:
    """Patterns from an optional ``.codebase-insight-ignore`` at the root."""
    candidate = root / ".codebase-insight-ignore"
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ()

    patterns: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line == "" or line.startswith("#"):
            continue
        line = line.removeprefix("./").rstrip("/\\")
        if line and not Path(line).is_absolute():
            patterns.append(line)
    return tuple(patterns)
