"""The single pass over a repository that most tools are built on.

Walk the tree, classify every file, read the text ones concurrently and measure
them. Tech-debt markers and credential-shaped strings are collected during the
same read, so a caller asking for several of those does not pay for the I/O
twice.

There is no cross-invocation cache. Re-deriving what a tool needs costs a
second or two on a large repository and guarantees a tool can never report state
that no longer exists on disk.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from ..logger import debug
from . import languages, masking, secrets, todos, walk
from . import loc as loc_mod
from .loc import Loc

# Bounded concurrency: `Promise.all`-style fan-out over tens of thousands of
# files exhausts file descriptors and thrashes the disk.
READ_WORKERS = 32


@dataclass(frozen=True, slots=True)
class FileMetrics:
    rel: str
    size: int
    language: str
    kind: str
    loc: Loc


@dataclass(slots=True)
class LanguageStats:
    language: str
    kind: str
    files: int = 0
    bytes: int = 0
    loc: Loc = field(default_factory=Loc)


@dataclass(slots=True)
class Analysis:
    root: Path
    walk: walk.WalkResult
    files: list[FileMetrics] = field(default_factory=list)
    by_language: list[LanguageStats] = field(default_factory=list)
    files_on_disk: int = 0
    total_lines: int = 0
    code_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    bytes: int = 0
    todos: list[todos.Todo] = field(default_factory=list)
    secret_findings: list[secrets.Finding] = field(default_factory=list)
    sensitive_files: list[secrets.SensitiveFile] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    skipped_too_large: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def find(self, rel: str) -> FileMetrics | None:
        for item in self.files:
            if item.rel == rel:
                return item
        return None

    def top_language(self) -> str:
        return self.by_language[0].language if self.by_language else ""


def _read_one(root: Path, item: walk.WalkedFile) -> tuple[FileMetrics | None, str | None, str]:
    """Read and measure one file. Returns (metrics, error, text)."""
    language = languages.language_of(item.rel)
    if language is None:
        return None, None, ""
    try:
        text = item.path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, str(exc), ""
    metrics = FileMetrics(
        rel=item.rel,
        size=item.size,
        language=language.name,
        kind=language.kind,
        loc=loc_mod.count_lines(item.rel, text),
    )
    return metrics, None, text


def analyze(
    root: Path,
    *,
    max_depth: int | None = None,
    max_files: int | None = None,
    extra_ignore: tuple[str, ...] = (),
    collect_todos: bool = True,
    todo_tags: tuple[str, ...] | None = None,
    scan_secrets: bool = False,
) -> Analysis:
    """Walk ``root`` and measure it in one pass.

    ``todo_tags`` selects the marker tags collected during the same read;
    ``None`` uses the defaults and an empty tuple disables the scan entirely.
    """
    started = time.perf_counter()
    tags = todos.DEFAULT_TAGS if todo_tags is None else todo_tags

    result = walk.walk(root, max_depth=max_depth, max_files=max_files, extra_ignore=extra_ignore)
    analysis = Analysis(root=root, walk=result)
    analysis.files_on_disk = len(result.files)

    limit = config.max_file_bytes()
    candidates: list[walk.WalkedFile] = []
    for item in result.files:
        if languages.language_of(item.rel) is None:
            continue
        if item.size > limit:
            analysis.skipped_too_large.append(item.rel)
            continue
        candidates.append(item)

    if candidates:
        with ThreadPoolExecutor(max_workers=min(READ_WORKERS, len(candidates))) as pool:
            outcomes = list(pool.map(lambda entry: _read_one(root, entry), candidates))
    else:
        outcomes = []

    buckets: dict[str, LanguageStats] = {}

    for item, (metrics, error, text) in zip(candidates, outcomes, strict=True):
        if metrics is None:
            if error is not None:
                analysis.unreadable.append(item.rel)
            continue

        analysis.files.append(metrics)
        analysis.bytes += metrics.size
        analysis.total_lines += metrics.loc.lines
        analysis.comment_lines += metrics.loc.comment
        analysis.blank_lines += metrics.loc.lines - metrics.loc.non_blank
        if metrics.kind == languages.CODE:
            analysis.code_lines += metrics.loc.code

        bucket = buckets.get(metrics.language)
        if bucket is None:
            bucket = LanguageStats(language=metrics.language, kind=metrics.kind)
            buckets[metrics.language] = bucket
        bucket.files += 1
        bucket.bytes += metrics.size
        bucket.loc = loc_mod.add(bucket.loc, metrics.loc)

        if collect_todos and tags:
            language = languages.language_of(item.rel)
            # Blank string literals first: a marker inside test data or a
            # docstring is not actionable debt. Python is exact here because
            # `ast` supplies the byte span; other languages use the raw text.
            scannable = masking.mask_string_literals(text, language.name) if language else text
            analysis.todos.extend(
                todos.scan(
                    item.rel,
                    scannable,
                    language.line_comment if language else "",
                    tags=tags,
                    # Bare-line markers are a prose convention (Markdown task
                    # lists); in source they turn constant tables into debt.
                    allow_bare_line=language is not None and language.kind == languages.DOC,
                )
            )
        if scan_secrets:
            analysis.secret_findings.extend(secrets.scan(item.rel, text))

    analysis.files.sort(key=lambda entry: entry.rel)
    analysis.todos.sort(key=todos.sort_key)
    analysis.secret_findings.sort(key=lambda finding: (finding.severity, finding.file, finding.line))

    def weight(stats: LanguageStats) -> float:
        return float(stats.loc.code) if stats.kind == languages.CODE else stats.loc.code / 4

    analysis.by_language = sorted(buckets.values(), key=lambda stats: (-weight(stats), stats.language))

    for item in result.files:
        sensitive = secrets.match_sensitive_file(item.rel)
        if sensitive is not None:
            analysis.sensitive_files.append(sensitive)

    analysis.elapsed_ms = int((time.perf_counter() - started) * 1000)
    debug(f"analyze {root}: {len(analysis.files)} text files in {analysis.elapsed_ms}ms")
    return analysis


# --------------------------------------------------------------------------- #
# Path heuristics shared by the tools
# --------------------------------------------------------------------------- #

_TEST_DIR = re.compile(r"(?:^|/)(?:tests?|__tests__|specs?|fixtures?|e2e)/", re.IGNORECASE)
_TEST_FILE = re.compile(
    r"(?:^|/)test_[^/]*\.py$"
    r"|(?:^|/)[^/]*_test\.(?:py|go|rb|dart)$"
    r"|\.(?:test|spec)\.[cm]?[jt]sx?$"
    r"|\.(?:test|spec)\.(?:py|rb|php|cs|java|kt)$",
    re.IGNORECASE,
)


def is_test_path(rel: str) -> bool:
    """True when a relative path looks like test code or test data."""
    normalized = rel.replace("\\", "/")
    return _TEST_DIR.search(normalized) is not None or _TEST_FILE.search(normalized) is not None


def detect_project_identity(analysis: Analysis) -> tuple[str, str, list[str]]:
    """Return ``(ecosystem label, primary language, manifest paths)``."""
    by_lower = {item.rel.lower(): item.rel for item in analysis.walk.files}
    markers: list[tuple[str, str]] = [
        ("package.json", "Node.js"),
        ("pyproject.toml", "Python"),
        ("requirements.txt", "Python"),
        ("setup.py", "Python"),
        ("go.mod", "Go"),
        ("cargo.toml", "Rust"),
        ("pom.xml", "Java (Maven)"),
        ("build.gradle", "JVM (Gradle)"),
        ("composer.json", "PHP"),
        ("gemfile", "Ruby"),
        ("cmakelists.txt", "C / C++ (CMake)"),
        ("dockerfile", "containerised"),
    ]

    matched: list[tuple[str, str]] = []
    for name, label in markers:
        actual = by_lower.get(name)
        if actual is not None:
            matched.append((actual, label))

    ecosystem = matched[0][1] if matched else "unclassified"
    return ecosystem, analysis.top_language(), [actual for actual, _ in matched]
