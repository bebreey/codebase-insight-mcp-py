"""MCP server: five read-only tools over the analysis layer.

Error contract, verified against the SDK source rather than assumed:

* raising :class:`ToolError` produces an ``is_error`` tool result that **keeps
  the message**, which is what a caller needs for "path does not exist";
* raising any other exception is swallowed into ``Error executing tool <name>``,
  so it is never used for expected failures;
* :class:`MCPError` would surface as a JSON-RPC protocol error, which is wrong
  for a bad argument.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field

from . import SERVER_NAME, SERVER_VERSION, config
from .core import analysis, health, manifests, paths, symbols, todos, walk
from .core import languages as lang
from .core.text import human_bytes, percent, truncate
from .models import (
    AuditOut,
    CorpusOut,
    DependencyRow,
    FactorRow,
    FileRow,
    FindingRow,
    HealthOut,
    IssueRow,
    LanguageRow,
    LockfileRow,
    ManifestRow,
    RepoOverviewOut,
    SymbolCount,
    SymbolRow,
    SymbolsOut,
    TodoCount,
    TodoRow,
    TodosOut,
    TotalsOut,
)

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)

PathArg = Annotated[
    str,
    Field(
        description="Repository root to analyse. Empty falls back to CBI_DEFAULT_ROOT, then the working directory."
    ),
]
LimitArg = Annotated[int, Field(ge=0, description="Maximum items returned. 0 means the tool default.")]

ENTRY_CANDIDATES: tuple[str, ...] = (
    "src/index.ts",
    "src/index.js",
    "src/main.ts",
    "src/main.js",
    "src/server.ts",
    "src/server.js",
    "index.ts",
    "index.js",
    "main.ts",
    "main.js",
    "src/__main__.py",
    "__main__.py",
    "main.py",
    "app.py",
    "manage.py",
    "src/main.rs",
    "main.rs",
    "lib.rs",
    "main.go",
    "cmd/main.go",
    "Program.cs",
    "src/Program.cs",
    "src/codebase_insight/__main__.py",
)

ACTION_BY_AREA: dict[str, str] = {
    "tests": "Add a test runner plus at least one test that fails when the core path breaks, and run it in CI.",
    "security": "Rotate any real credential, purge it from history, and load secrets from the environment or a secret manager.",
    "dependencies": "Commit the lockfile for the package manager you actually use, and pin or bound the floating versions.",
    "ci": "Add a CI workflow that installs dependencies and runs the test suite on every push.",
    "docs": "Write a README stating what the project does, how to run it, and how to test it.",
    "type_safety": "Turn on a static checker (mypy or pyright) and burn down the first batch of errors.",
    "lint_format": "Add a linter and formatter, wire both into CI, and format the tree once.",
    "file_size": "Split the largest files along their responsibilities before adding more to them.",
    "debt": "Triage FIXME and BUG markers, and delete stale TODOs instead of carrying them forward.",
}


def _resolve(raw_path: str) -> tuple[Path, tuple[str, ...]]:
    try:
        root = paths.resolve_workspace_root(raw_path or None, config.default_root())
    except paths.WorkspaceError as exc:
        # ToolError keeps the message; a bare exception would be replaced by
        # "Error executing tool ..." before it reaches the caller.
        raise ToolError(str(exc)) from exc
    return root, walk.load_ignore_file(root)


def _clamp(value: int, fallback: int, maximum: int) -> int:
    if value is None or value <= 0:
        return fallback
    return min(int(value), maximum)


def _build_commands(root: Path) -> list[str]:
    commands: list[str] = []
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8", errors="replace"))
            for name in ("dev", "build", "test", "lint"):
                if name in (data.get("scripts") or {}):
                    commands.append(f"npm run {name}")
        except (OSError, json.JSONDecodeError):
            pass

    if (root / "pyproject.toml").is_file():
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace")
        if "[tool.pytest" in pyproject or (root / "tests").is_dir():
            commands.append("pytest")
        if "[tool.ruff" in pyproject:
            commands.append("ruff check .")
    if (root / "requirements.txt").is_file() or (root / "pyproject.toml").is_file():
        commands.append("pip install -e .")
    if (root / "Makefile").is_file():
        commands.append("make")
    if (root / "Cargo.toml").is_file():
        commands.append("cargo test")
    if (root / "go.mod").is_file():
        commands.append("go test ./...")
    return commands


def create_server() -> MCPServer:
    """Build the server with every tool registered."""
    server = MCPServer(
        name=SERVER_NAME,
        title="Codebase Insight (Python)",
        version=SERVER_VERSION,
        instructions=(
            "Offline, read-only analysis tools for a local codebase.\n\n"
            "Suggested order: repo_overview -> find_todos -> search_symbols -> "
            "audit_dependencies -> assess_health.\n\n"
            "Every tool takes an optional `path`; it defaults to CBI_DEFAULT_ROOT, then the "
            "working directory. Python symbols are extracted with the standard-library ast "
            "module; .gitignore files are honoured during the walk."
        ),
    )

    @server.tool(title="Repository overview", annotations=READ_ONLY)
    def repo_overview(
        path: PathArg = "",
        top_languages: Annotated[int, Field(description="How many languages to list.")] = 10,
        top_files: Annotated[int, Field(description="How many largest files to list.")] = 8,
    ) -> RepoOverviewOut:
        """Produce a one-shot orientation report for a local repository: project type,
        language breakdown, line counts, entry points and the build/test commands.

        Use this first when you have been pointed at an unfamiliar codebase and need to
        decide where to look. Runs entirely offline and never writes to disk.
        """
        root, ignore = _resolve(path)
        data = analysis.analyze(root, extra_ignore=ignore, collect_todos=False)
        ecosystem, primary, markers = analysis.detect_project_identity(data)

        rel_set = {item.rel for item in data.walk.files}
        entry_points = [candidate for candidate in ENTRY_CANDIDATES if candidate in rel_set]

        notes: list[str] = []
        if data.walk.truncated:
            notes.append(
                f"File listing was truncated at {len(data.walk.files)} entries; totals are a lower bound."
            )
        if data.skipped_too_large:
            notes.append(
                f"{len(data.skipped_too_large)} file(s) exceeded the {human_bytes(config.max_file_bytes())} read limit and were measured by size only."
            )
        if data.unreadable:
            notes.append(
                f"{len(data.unreadable)} file(s) could not be read (permissions or invalid encoding)."
            )
        if ignore:
            notes.append(f".codebase-insight-ignore excluded: {', '.join(ignore)}")
        if not markers:
            notes.append(
                "No recognised build manifest at the repository root; the ecosystem is a guess from file types."
            )

        languages = [
            LanguageRow(
                language=stats.language,
                kind=stats.kind,
                files=stats.files,
                code_lines=stats.loc.code,
                share_of_code=percent(stats.loc.code, data.code_lines) if stats.kind == "code" else "-",
                size=human_bytes(stats.bytes),
            )
            for stats in data.by_language[: _clamp(top_languages, 10, 40)]
        ]

        largest = sorted(data.files, key=lambda item: -item.loc.lines)[: _clamp(top_files, 8, 40)]
        largest_files = [
            FileRow(file=item.rel, lines=item.loc.lines, language=item.language)
            for item in largest
            if item.loc.lines
        ]

        project_type = (
            ecosystem if primary == "" or primary.lower() == ecosystem.lower() else f"{ecosystem} / {primary}"
        )

        return RepoOverviewOut(
            root=str(root),
            project_type=project_type,
            ecosystem=ecosystem,
            primary_language=primary,
            totals=TotalsOut(
                files_on_disk=data.files_on_disk,
                text_files=len(data.files),
                code_lines=data.code_lines,
                total_lines=data.total_lines,
                comment_lines=data.comment_lines,
                bytes=data.bytes,
                bytes_human=human_bytes(data.bytes),
                skipped_too_large=len(data.skipped_too_large),
                unreadable=len(data.unreadable),
                truncated=data.walk.truncated,
            ),
            languages=languages,
            entry_points=entry_points,
            build_commands=_build_commands(root),
            largest_files=largest_files,
            gitignore_files=data.walk.gitignore_files,
            notes=notes,
        )

    @server.tool(title="Find tech-debt markers", annotations=READ_ONLY)
    def find_todos(
        path: PathArg = "",
        tags: Annotated[
            list[str] | None,
            Field(
                description="Marker tags to look for. Defaults to TODO, FIXME, HACK, XXX, BUG, OPTIMIZE, DEPRECATED."
            ),
        ] = None,
        limit: LimitArg = 0,
    ) -> TodosOut:
        """Find TODO / FIXME / HACK / BUG and similar tech-debt markers, ordered so the
        highest-severity markers come first.

        A marker only counts when it sits in a comment or on a bare line, so a table of tag
        names in the source is not reported as debt. Use this to size up outstanding work or
        to find the places a codebase already admits are broken.
        """
        root, ignore = _resolve(path)
        requested = tuple(tag.upper() for tag in (tags or []) if tag)
        known = tuple(tag for tag in requested if tag in todos.ALL_TAGS)
        effective = known or todos.DEFAULT_TAGS

        # The tag scan runs inside the same read as the line counting.
        data = analysis.analyze(root, extra_ignore=ignore, todo_tags=effective)
        all_hits = data.todos

        cap = _clamp(limit, 50, 500)
        items = all_hits[:cap]

        counts: dict[str, int] = {}
        per_file: dict[str, int] = {}
        for hit in all_hits:
            counts[hit.tag] = counts.get(hit.tag, 0) + 1
            per_file[hit.file] = per_file.get(hit.file, 0) + 1

        notes: list[str] = []
        if len(all_hits) > len(items):
            notes.append(f"Showing {len(items)} of {len(all_hits)}; raise `limit` for more.")
        if data.walk.truncated:
            notes.append("The file listing was truncated, so this scan is incomplete.")

        return TodosOut(
            root=str(root),
            total=len(all_hits),
            returned=len(items),
            truncated=len(all_hits) > len(items),
            counts=[
                TodoCount(tag=tag, count=count)
                for tag, count in sorted(counts.items(), key=lambda pair: -pair[1])
            ],
            items=[
                TodoRow(
                    tag=hit.tag,
                    file=hit.file,
                    line=hit.line,
                    owner=hit.owner or "",
                    text=hit.text,
                    in_comment=hit.in_comment,
                )
                for hit in items
            ],
            files_with_most=[
                FileRow(file=file, lines=count, language="")
                for file, count in sorted(per_file.items(), key=lambda pair: -pair[1])[:8]
            ],
            notes=notes,
        )

    @server.tool(title="Search code symbols", annotations=READ_ONLY)
    def search_symbols(
        path: PathArg = "",
        query: Annotated[
            str, Field(description="Name to search for. Empty lists every declaration found.")
        ] = "",
        mode: Annotated[
            Literal["literal", "regex"],
            Field(description="Treat `query` as a substring or a regular expression."),
        ] = "literal",
        kinds: Annotated[
            list[str] | None, Field(description="Restrict to these kinds, e.g. ['class', 'function'].")
        ] = None,
        languages: Annotated[
            list[str] | None, Field(description="Restrict to these languages, e.g. ['Python'].")
        ] = None,
        limit: LimitArg = 0,
    ) -> SymbolsOut:
        """Locate function, class, method, interface, struct, enum and constant declarations
        across a repository.

        Python files are parsed with the standard-library ast module, so signatures and
        line numbers are exact and nested definitions are classified correctly. Other
        languages use per-language declaration patterns. Use this to jump straight to a
        definition instead of grepping and reading false positives.
        """
        root, ignore = _resolve(path)
        walk_result = walk.walk(root, extra_ignore=ignore)

        kind_filter = {kind.lower() for kind in (kinds or []) if kind}
        language_filter = {name.lower() for name in (languages or []) if name}

        pattern: re.Pattern[str] | None = None
        if query:
            try:
                source = query if mode == "regex" else re.escape(query)
                pattern = re.compile(source, re.IGNORECASE)
            except re.error as exc:
                raise ToolError(f"Invalid regular expression: {exc}") from exc

        supported = set(symbols.supported_languages())
        candidates = []
        for item in walk_result.files:
            if item.size > config.max_file_bytes():
                continue
            language = lang.language_of(item.rel)
            if language is None or language.kind != "code" or language.name not in supported:
                continue
            if language_filter and language.name.lower() not in language_filter:
                continue
            candidates.append((item, language))

        found: list[symbols.Symbol] = []
        for item, language in candidates:
            try:
                text = item.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for symbol in symbols.extract_symbols(item.rel, text, language.name):
                if kind_filter and symbol.kind.lower() not in kind_filter:
                    continue
                if pattern is not None and pattern.search(symbol.name) is None:
                    continue
                found.append(symbol)

        found.sort(key=lambda symbol: (symbol.file, symbol.line))
        cap = _clamp(limit, 50, 500)
        items = found[:cap]

        by_kind: dict[str, int] = {}
        by_language: dict[str, int] = {}
        for symbol in found:
            by_kind[symbol.kind] = by_kind.get(symbol.kind, 0) + 1
            by_language[symbol.language] = by_language.get(symbol.language, 0) + 1

        notes: list[str] = []
        if len(found) > len(items):
            notes.append(f"Showing {len(items)} of {len(found)}; raise `limit` for more.")
        if walk_result.truncated:
            notes.append("The file listing was truncated, so this search is incomplete.")
        if pattern is None:
            notes.append("No `query` supplied: returning declarations in file order.")

        python_scanned = any(language.name == "Python" for _, language in candidates)
        if python_scanned:
            notes.append(
                "Python files were parsed with the ast module, so their signatures and line numbers are exact."
            )

        return SymbolsOut(
            root=str(root),
            query=query,
            mode=mode,
            extracted_with_ast=python_scanned,
            scanned_files=len(candidates),
            matched=len(found),
            returned=len(items),
            truncated=len(found) > len(items),
            by_kind=[
                SymbolCount(key=key, count=count)
                for key, count in sorted(by_kind.items(), key=lambda pair: -pair[1])
            ],
            by_language=[
                SymbolCount(key=key, count=count)
                for key, count in sorted(by_language.items(), key=lambda pair: -pair[1])
            ],
            items=[
                SymbolRow(
                    name=s.name,
                    kind=s.kind,
                    language=s.language,
                    file=s.file,
                    line=s.line,
                    signature=s.signature,
                )
                for s in items
            ],
            supported_languages=list(symbols.supported_languages()),
            notes=notes,
        )

    @server.tool(title="Audit dependencies", annotations=READ_ONLY)
    def audit_dependencies(
        path: PathArg = "",
        preview_limit: LimitArg = 0,
    ) -> AuditOut:
        """Audit dependency manifests: what is depended on, how tightly versions are pinned,
        and whether a lockfile exists next to the manifest.

        pyproject.toml and Cargo.toml are read with the standard-library tomllib parser, so
        the result is exact rather than a heuristic scan. Use this before publishing or
        onboarding to catch floating versions and missing lockfiles.
        """
        root, ignore = _resolve(path)
        result = manifests.audit(root, extra_ignore=ignore)

        all_deps = [dep for manifest in result.manifests for dep in manifest.dependencies]
        rank = {"floating": 0, "unpinned": 1, "url": 2, "range": 3, "exact": 4, "unknown": 5}
        least_pinned = sorted(all_deps, key=lambda dep: (rank.get(dep.pin, 9), dep.name))[
            : _clamp(preview_limit, 25, 200)
        ]

        notes: list[str] = []
        if not result.manifests:
            notes.append("No supported dependency manifest was found in this repository.")

        return AuditOut(
            root=str(root),
            manifests=[
                ManifestRow(
                    file=manifest.file,
                    ecosystem=manifest.ecosystem,
                    package_name=manifest.package_name,
                    dependency_count=len(manifest.dependencies),
                    notes=manifest.notes,
                )
                for manifest in result.manifests
            ],
            lockfiles=[LockfileRow(file=lock.file, ecosystem=lock.ecosystem) for lock in result.lockfiles],
            issues=[
                IssueRow(severity=i.severity, code=i.code, message=i.message, file=i.file)
                for i in result.issues
            ],
            runtime=result.runtime,
            dev=result.dev,
            other=result.other,
            floating=result.floating,
            unpinned=result.unpinned,
            url=result.url,
            least_pinned=[
                DependencyRow(
                    name=dep.name, spec=dep.spec, ecosystem=dep.ecosystem, kind=dep.kind, pin=dep.pin
                )
                for dep in least_pinned
            ],
            notes=notes,
        )

    @server.tool(title="Assess repository health", annotations=READ_ONLY)
    def assess_health(path: PathArg = "", top_findings: LimitArg = 0) -> HealthOut:
        """Score a repository on nine weighted factors (tests, dependencies, secret hygiene,
        CI, docs, type safety, lint/format, file size, tech debt) and return a graded report
        with concrete findings.

        Use this for due diligence on a codebase you are about to join, publish or hand over.
        Credential-shaped strings are detected and reported as redacted fingerprints, so the
        result is safe to paste elsewhere. Runs entirely offline and never writes to disk.
        """
        root, ignore = _resolve(path)
        data = analysis.analyze(root, extra_ignore=ignore, scan_secrets=True)
        audit = manifests.audit(root, extra_ignore=ignore)
        report = health.assess(data, audit)

        actions: list[str] = []
        for finding in report.findings:
            if finding.severity != health.HIGH:
                continue
            action = ACTION_BY_AREA.get(finding.area)
            if action and action not in actions:
                actions.append(action)

        cap = _clamp(top_findings, 12, 60)
        notes: list[str] = []
        if data.walk.truncated:
            notes.append(
                "The file listing was truncated, so the score was computed on a subset of the repository."
            )
        if data.secret_findings:
            notes.append(
                "Credential findings are redacted fingerprints only; review those files directly to confirm."
            )
        if ignore:
            notes.append(f".codebase-insight-ignore excluded: {', '.join(ignore)}")

        return HealthOut(
            root=str(root),
            score=report.score,
            grade=report.grade,
            summary=report.summary,
            factors=[
                FactorRow(id=f.id, label=f.label, weight=f.weight, earned=f.earned, detail=f.detail)
                for f in report.factors
            ],
            findings=[
                FindingRow(severity=f.severity, area=f.area, message=truncate(f.message, 400), file=f.file)
                for f in report.findings[:cap]
            ],
            stats=CorpusOut(
                files_on_disk=data.files_on_disk,
                text_files=len(data.files),
                code_files=report.code_files,
                test_files=report.test_files,
                code_lines=data.code_lines,
                total_lines=data.total_lines,
                large_files=sum(1 for item in data.files if item.loc.lines > health.LARGE_FILE_LINES),
                todo_count=len(data.todos),
                secret_count=len(data.secret_findings),
                sensitive_file_count=len(data.sensitive_files),
                bytes=human_bytes(data.bytes),
            ),
            priority_actions=actions,
            notes=notes,
        )

    return server


__all__ = ["create_server"]
