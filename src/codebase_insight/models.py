"""Output models for every tool.

With this SDK the **return type annotation is the output schema**: it is
published in ``tools/list`` as ``output_schema``, the returned value is
validated against it, and it becomes ``structured_content`` on the wire. Making
these Pydantic models the single source of truth means the schema and the
implementation cannot drift apart.

The TypeScript implementation of this server hand-wrote both a Markdown rendering
and a separate output schema, then relied on an end-to-end test to catch drift.
Both are defensible; this one removes the class of bug instead of testing for it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LanguageRow(BaseModel):
    language: str = Field(description="Language name.")
    kind: str = Field(description="code | markup | style | data | config | doc")
    files: int = Field(description="Number of files in this language.")
    code_lines: int = Field(description="Code lines (blank and comment lines excluded for code languages).")
    share_of_code: str = Field(description="Share of all code lines, e.g. '95.1%'.")
    size: str = Field(description="Total size on disk, human readable.")


class FileRow(BaseModel):
    file: str = Field(description="Path relative to the analysed root.")
    lines: int = Field(description="Total line count.")
    language: str = Field(description="Detected language.")


class TotalsOut(BaseModel):
    files_on_disk: int = Field(description="Files seen by the walker, after ignore rules.")
    text_files: int = Field(description="Files with a recognised text language that were read.")
    code_lines: int = Field(description="Code lines across programming languages.")
    total_lines: int = Field(description="Total lines across all text files.")
    comment_lines: int = Field(description="Lines that are only a comment (heuristic).")
    bytes: int = Field(description="Total bytes of text files.")
    bytes_human: str = Field(description="Total size, human readable.")
    skipped_too_large: int = Field(description="Files skipped because they exceed the read limit.")
    unreadable: int = Field(description="Files that matched a language but could not be read.")
    truncated: bool = Field(description="True when a walk limit was hit and the listing is incomplete.")


class RepoOverviewOut(BaseModel):
    """Orientation report for a repository."""

    root: str = Field(description="Absolute path that was analysed.")
    project_type: str = Field(description="Ecosystem plus primary language, e.g. 'Node.js / TypeScript'.")
    ecosystem: str = Field(description="Build system family detected from manifest markers.")
    primary_language: str = Field(description="Language with the most code lines.")
    totals: TotalsOut
    languages: list[LanguageRow] = Field(description="Languages ordered by code volume.")
    entry_points: list[str] = Field(description="Likely entry files that exist in this repository.")
    build_commands: list[str] = Field(description="Run/build/test commands discovered from manifests.")
    largest_files: list[FileRow] = Field(description="Files with the most lines.")
    gitignore_files: list[str] = Field(description=".gitignore files that were honoured.")
    notes: list[str] = Field(description="Caveats about this particular result.")


class TodoRow(BaseModel):
    tag: str = Field(description="TODO | FIXME | HACK | XXX | BUG | OPTIMIZE | DEPRECATED | REVIEW | NOTE")
    file: str
    line: int
    owner: str = Field(description="Name inside TAG(owner), or empty.")
    text: str = Field(description="Marker text, truncated.")
    in_comment: bool = Field(description="True when a comment marker precedes the tag on the same line.")


class TodoCount(BaseModel):
    tag: str
    count: int


class TodosOut(BaseModel):
    """Tech-debt markers found across a repository."""

    root: str
    total: int = Field(description="Markers found before the limit was applied.")
    returned: int = Field(description="Markers included in this response.")
    truncated: bool
    counts: list[TodoCount] = Field(description="Count per tag.")
    items: list[TodoRow] = Field(description="Markers, most severe first.")
    files_with_most: list[FileRow] = Field(
        description="Files carrying the most markers (lines = marker count)."
    )
    notes: list[str]


class SymbolRow(BaseModel):
    name: str
    kind: str = Field(
        description="function | method | class | interface | struct | trait | enum | type | constant | module | export"
    )
    language: str
    file: str
    line: int
    signature: str


class SymbolCount(BaseModel):
    key: str
    count: int


class SymbolsOut(BaseModel):
    """Declarations located across a repository."""

    root: str
    query: str = Field(description="The query that was applied, or empty when listing everything.")
    mode: str = Field(description="literal or regex.")
    extracted_with_ast: bool = Field(
        description="True when the query targeted Python, which is parsed with the ast module rather than regex."
    )
    scanned_files: int
    matched: int = Field(description="Declarations matched before the limit was applied.")
    returned: int
    truncated: bool
    by_kind: list[SymbolCount]
    by_language: list[SymbolCount]
    items: list[SymbolRow]
    supported_languages: list[str]
    notes: list[str]


class DependencyRow(BaseModel):
    name: str
    spec: str
    ecosystem: str
    kind: str = Field(description="runtime | dev | optional | build")
    pin: str = Field(description="exact | range | floating | url | unpinned | unknown")


class ManifestRow(BaseModel):
    file: str
    ecosystem: str
    package_name: str
    dependency_count: int
    notes: list[str]


class LockfileRow(BaseModel):
    file: str
    ecosystem: str


class IssueRow(BaseModel):
    severity: str = Field(description="high | medium | low")
    code: str = Field(description="Stable identifier, e.g. 'missing-lockfile'.")
    message: str
    file: str


class AuditOut(BaseModel):
    """Dependency hygiene audit."""

    root: str
    manifests: list[ManifestRow]
    lockfiles: list[LockfileRow]
    issues: list[IssueRow]
    runtime: int
    dev: int
    other: int
    floating: int
    unpinned: int
    url: int
    least_pinned: list[DependencyRow] = Field(
        description="Dependencies with the loosest version constraints."
    )
    notes: list[str]


class FactorRow(BaseModel):
    id: str
    label: str
    weight: int = Field(description="Maximum points this factor can contribute.")
    earned: int = Field(description="Points actually awarded.")
    detail: str = Field(description="Numerator, denominator and the evidence behind the score.")


class FindingRow(BaseModel):
    severity: str = Field(description="high | medium | low")
    area: str
    message: str
    file: str = Field(description="Location, or empty when the finding is repository-wide.")


class CorpusOut(BaseModel):
    files_on_disk: int
    text_files: int
    code_files: int
    test_files: int
    code_lines: int
    total_lines: int
    large_files: int
    todo_count: int
    secret_count: int
    sensitive_file_count: int
    bytes: str


class HealthOut(BaseModel):
    """Weighted repository health report."""

    root: str
    score: int = Field(description="0-100, the sum of the weighted factors.")
    grade: str = Field(description="A+ .. F")
    summary: str = Field(description="One-line verdict naming the highest-priority gap.")
    factors: list[FactorRow]
    findings: list[FindingRow]
    stats: CorpusOut
    priority_actions: list[str] = Field(description="Concrete next actions for the high-severity findings.")
    notes: list[str]
