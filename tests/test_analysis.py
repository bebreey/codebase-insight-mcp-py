"""The single analysis pass, exercised against the fixture repository."""

from __future__ import annotations

from pathlib import Path

from codebase_insight.core import analysis


def test_measures_the_fixture_repository(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo, scan_secrets=True)

    assert data.code_lines > 40
    assert data.total_lines >= data.code_lines
    assert data.files_on_disk >= len(data.files)
    languages = {stats.language for stats in data.by_language}
    # TOML is listed because pyproject.toml is a TOML file: before the
    # single-element-tuple fix, every .toml path resolved to no language at all.
    assert languages == {"Python", "Markdown", "YAML", "TOML", "Git Config"}


def test_gitignored_files_are_not_analysed(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo)
    rels = {item.rel for item in data.files}
    assert not any(rel.startswith("src/sample/generated/") for rel in rels)
    # The .gitignore itself is collected; it is not ignored by its own rules.
    assert ".gitignore" in {item.rel for item in data.walk.files}


def test_collects_debt_markers_in_the_same_pass(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo)

    tags = sorted(hit.tag for hit in data.todos)
    assert tags == ["FIXME", "HACK", "TODO", "TODO", "TODO"]
    owners = sorted(hit.owner for hit in data.todos if hit.owner)
    assert owners == ["alice"]
    # Markdown task items are prose and must be picked up.
    assert any(hit.file == "docs/notes.md" for hit in data.todos)


def test_custom_todo_tags_and_disabling_the_scan(fixture_repo: Path) -> None:
    only_note = analysis.analyze(fixture_repo, todo_tags=("NOTE",))
    assert only_note.todos == []

    disabled = analysis.analyze(fixture_repo, collect_todos=False)
    assert disabled.todos == []


def test_collects_exactly_one_credential_shaped_literal(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo, scan_secrets=True)
    assert len(data.secret_findings) == 1
    finding = data.secret_findings[0]
    assert finding.file == "src/sample/config.py"
    assert finding.rule == "generic-assigned-secret"
    assert "notarealvalue12345678" not in finding.fingerprint


def test_secrets_are_not_scanned_unless_requested(fixture_repo: Path) -> None:
    assert analysis.analyze(fixture_repo).secret_findings == []


def test_languages_are_ranked_by_code_volume(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo)
    assert data.by_language[0].language == "Python"
    assert data.by_language[0].kind == "code"
    assert data.top_language() == "Python"


def test_is_test_path_recognises_common_layouts() -> None:
    assert analysis.is_test_path("tests/test_a.py") is True
    assert analysis.is_test_path("src/pkg/tests/helper.py") is True
    assert analysis.is_test_path("src/pkg/__tests__/a.ts") is True
    assert analysis.is_test_path("src/pkg/a_test.go") is True
    assert analysis.is_test_path("src/pkg/module.py") is False


def test_detects_project_identity(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo)
    ecosystem, primary, markers = analysis.detect_project_identity(data)
    assert ecosystem == "Python"
    assert primary == "Python"
    assert "pyproject.toml" in markers


def test_extra_ignore_excludes_paths(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo, extra_ignore=("docs",))
    assert not any(item.rel.startswith("docs/") for item in data.walk.files)
    assert data.walk.ignore_patterns == ("docs",)


def test_truncation_is_reported_rather_than_silent(fixture_repo: Path) -> None:
    data = analysis.analyze(fixture_repo, max_files=2, max_depth=1)
    assert data.walk.truncated is True
    assert len(data.files) <= 2
