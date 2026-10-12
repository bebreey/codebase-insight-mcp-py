"""Dependency manifest parsing and hygiene auditing.

``pyproject.toml`` and ``Cargo.toml`` are read with the standard-library
``tomllib`` parser, so these tests assert exact values rather than the
heuristics the TypeScript implementation had to use.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from codebase_insight.core import manifests


def audit_tree(temp_tree: Callable[[dict[str, str]], Path], files: dict[str, str]) -> manifests.Audit:
    return manifests.audit(temp_tree(files))


def pins(audit: manifests.Audit) -> dict[str, str]:
    return {
        dependency.name: dependency.pin
        for manifest in audit.manifests
        for dependency in manifest.dependencies
    }


def test_pyproject_is_parsed_with_tomllib(
    temp_tree: Callable[[dict[str, str]], Path],
) -> None:
    audit = audit_tree(
        temp_tree,
        {
            "pyproject.toml": (
                "[project]\n"
                'name = "demo"\n'
                "dependencies = [\n"
                '    "requests>=2.31",\n'
                '    "click",\n'
                "]\n"
                "\n"
                "[project.optional-dependencies]\n"
                'dev = ["pytest>=7"]\n'
                "\n"
                "[tool.poetry.dependencies]\n"
                'python = "^3.11"\n'
                'wildcard = "*"\n'
            )
        },
    )

    manifest = audit.manifests[0]
    assert manifest.ecosystem == "poetry"
    assert manifest.package_name == "demo"

    names = {dependency.name for dependency in manifest.dependencies}
    assert {"requests", "click", "pytest", "wildcard"} <= names
    # The interpreter constraint is not a dependency.
    assert "python" not in names

    # Both syntaxes land in the same report, and opt-in groups are marked dev.
    kinds = {dependency.name: dependency.kind for dependency in manifest.dependencies}
    assert kinds["requests"] == "runtime"
    assert kinds["click"] == "runtime"
    assert kinds["pytest"] == "dev"
    assert kinds["wildcard"] == "runtime"

    classified = pins(audit)
    assert classified["requests"] == manifests.RANGE
    assert classified["click"] == manifests.UNPINNED
    assert classified["wildcard"] == manifests.FLOATING


def test_cargo_toml_uses_real_toml_parsing(
    temp_tree: Callable[[dict[str, str]], Path],
) -> None:
    audit = audit_tree(
        temp_tree,
        {
            "Cargo.toml": (
                "[package]\n"
                'name = "demo"\n'
                "\n"
                "[dependencies]\n"
                'serde = "1.0"\n'
                'tokio = { version = "1", features = ["full"] }\n'
                "\n"
                "[dev-dependencies]\n"
                'criterion = "0.5"\n'
            )
        },
    )
    kinds = {d.name: d.kind for d in audit.manifests[0].dependencies}
    assert kinds == {"serde": "runtime", "tokio": "runtime", "criterion": "dev"}
    assert pins(audit)["serde"] == manifests.RANGE


def test_broken_toml_is_reported_rather_than_fatal(
    temp_tree: Callable[[dict[str, str]], Path],
) -> None:
    audit = audit_tree(temp_tree, {"pyproject.toml": "[project]\nname = \n"})
    assert audit.manifests[0].notes
    assert "could not be parsed" in audit.manifests[0].notes[0]


def test_requirements_handles_comments_and_editable_vcs_installs(
    temp_tree: Callable[[dict[str, str]], Path],
) -> None:
    audit = audit_tree(
        temp_tree,
        {
            "requirements.txt": (
                "# pinned and ranged\n"
                "requests==2.31.0\n"
                "flask>=3.0,<4.0   # upper bounded upstream\n"
                "rich\n"
                "-e git+https://github.com/psf/requests.git#egg=localrequests\n"
                "-r requirements-dev.txt\n"
            )
        },
    )
    classified = pins(audit)
    assert classified["requests"] == manifests.EXACT
    assert classified["flask"] == manifests.RANGE
    assert classified["rich"] == manifests.UNPINNED
    # The editable install is a dependency, not a pip flag.
    assert classified["localrequests"] == manifests.URL
    assert audit.url == 1
    assert any("requirements-dev.txt" in note for note in audit.manifests[0].notes)
    assert any(issue.code == "unpinned-requirements" for issue in audit.issues)


def test_package_json_sections(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    audit = audit_tree(
        temp_tree,
        {
            "package.json": (
                "{"
                '"name":"demo",'
                '"dependencies":{"lodash":"*","zod":"^3.25.0"},'
                '"devDependencies":{"typescript":"5.9.3","zod":"^3.25.0"}'
                "}"
            ),
            "package-lock.json": "{}",
        },
    )
    classified = pins(audit)
    assert classified["lodash"] == manifests.FLOATING
    assert classified["zod"] == manifests.RANGE
    assert classified["typescript"] == manifests.EXACT
    assert audit.floating == 1
    assert any(issue.code == "duplicate-dependency-section" for issue in audit.issues)
    # A lockfile is present, so that issue must not appear.
    assert not any(issue.code == "missing-lockfile" for issue in audit.issues)


def test_go_mod_reads_require_blocks(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    audit = audit_tree(
        temp_tree,
        {
            "go.mod": (
                "module example.com/demo\n"
                "\n"
                "go 1.22\n"
                "\n"
                "require (\n"
                "\tgithub.com/spf13/cobra v1.8.0\n"
                ")\n"
                "\n"
                "require golang.org/x/text v0.14.0\n"
            )
        },
    )
    manifest = audit.manifests[0]
    assert manifest.package_name == "example.com/demo"
    assert len(manifest.dependencies) == 2
    assert pins(audit)["golang.org/x/text"] == manifests.EXACT


def test_multiple_npm_lockfiles_are_reported(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    audit = audit_tree(
        temp_tree,
        {
            "package.json": '{"name":"demo","dependencies":{"lodash":"4.17.21"}}',
            "package-lock.json": "{}",
            "yarn.lock": "# yarn lockfile v1\n",
        },
    )
    assert len(audit.lockfiles) == 2
    assert any(issue.code == "multiple-lockfiles" for issue in audit.issues)


def test_fixture_repository_reports_the_expected_gaps(fixture_repo: Path) -> None:
    audit = manifests.audit(fixture_repo)
    assert [manifest.file for manifest in audit.manifests] == ["pyproject.toml"]
    codes = {issue.code for issue in audit.issues}
    assert "missing-lockfile" in codes
    assert "floating-dependency" in codes
    assert audit.floating == 1
