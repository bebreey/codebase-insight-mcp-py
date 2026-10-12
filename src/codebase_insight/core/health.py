"""Weighted repository health score.

The score is a communication device, not a truth claim: it exists so a one-line
answer ("78/100, the gap is tests and CI") is available before the caller digs
into individual findings. Every factor reports its own numerator and
denominator, so the number can be argued with.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import manifests
from .analysis import Analysis, is_test_path

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

WEIGHTS: dict[str, int] = {
    "tests": 20,
    "dependencies": 15,
    "security": 15,
    "ci": 10,
    "docs": 10,
    "type_safety": 10,
    "lint_format": 8,
    "file_size": 7,
    "debt": 5,
}

LARGE_FILE_LINES = 800
VERY_LARGE_FILE_LINES = 2000
TARGET_TEST_RATIO = 0.35


@dataclass(frozen=True, slots=True)
class Factor:
    id: str
    label: str
    weight: int
    earned: int
    detail: str


@dataclass(frozen=True, slots=True)
class Finding:
    severity: str
    area: str
    message: str
    file: str = ""


@dataclass(slots=True)
class HealthReport:
    score: int = 0
    grade: str = "F"
    summary: str = ""
    factors: list[Factor] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    code_files: int = 0
    test_files: int = 0


def grade_of(score: int) -> str:
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def _finding_severity(severity: str) -> str:
    """Secret severities carry a `critical` tier that findings do not.

    To a reader both mean "act now"; collapsing them keeps the findings list on
    one comparable scale. The score still weights `critical` separately.
    """
    return HIGH if severity == "critical" else severity


def _any(analysis: Analysis, predicate: Callable[[str], bool]) -> str:
    for item in analysis.walk.files:
        if predicate(item.rel):
            return item.rel
    return ""


def _has_basename(analysis: Analysis, *names: str) -> bool:
    wanted = {name.lower() for name in names}
    return any(item.path.name.lower() in wanted for item in analysis.walk.files)


def assess(analysis: Analysis, audit: manifests.Audit) -> HealthReport:
    report = HealthReport()
    findings: list[Finding] = []
    pyproject = _read(analysis)
    tooling = pyproject.get("tool", {}) if isinstance(pyproject.get("tool"), dict) else {}

    code_files = [item for item in analysis.files if item.kind == "code" and not is_test_path(item.rel)]
    test_files = [item for item in analysis.walk.files if is_test_path(item.rel)]
    report.code_files = len(code_files)
    report.test_files = len(test_files)

    # ------------------------------------------------------------- tests
    ratio = len(test_files) / len(code_files) if code_files else 0.0
    runner = _detect_runner(analysis)
    test_score = 0.0 if not test_files else min(1.0, ratio / TARGET_TEST_RATIO)
    if test_files and runner is None:
        test_score *= 0.8
    report.factors.append(
        Factor(
            "tests",
            "Automated tests",
            WEIGHTS["tests"],
            round(test_score * WEIGHTS["tests"]),
            "no test files detected"
            if not test_files
            else f"{len(test_files)} test files vs {len(code_files)} source files "
            f"({ratio:.2f} ratio{', no runner config found' if runner is None else f', runner: {runner}'})",
        )
    )
    if not test_files:
        findings.append(
            Finding(
                HIGH,
                "tests",
                "No test files found. Add a runner and at least one test that fails when the core path breaks.",
            )
        )
    elif ratio < TARGET_TEST_RATIO:
        findings.append(
            Finding(
                MEDIUM,
                "tests",
                f"Test-to-source ratio is {ratio:.2f} (target >= {TARGET_TEST_RATIO}). The untested files are where regressions land.",
            )
        )

    # ------------------------------------------------------ dependencies
    high = sum(1 for issue in audit.issues if issue.severity == HIGH)
    medium = sum(1 for issue in audit.issues if issue.severity == MEDIUM)
    low = sum(1 for issue in audit.issues if issue.severity == LOW)
    dependency_score = max(0, WEIGHTS["dependencies"] - (high * 6 + medium * 3 + low))
    report.factors.append(
        Factor(
            "dependencies",
            "Dependency hygiene",
            WEIGHTS["dependencies"],
            dependency_score,
            "no dependency manifest detected"
            if not audit.manifests
            else f"{len(audit.manifests)} manifests, {len(audit.lockfiles)} lockfiles, "
            f"{len(audit.issues)} issues ({high} high / {medium} medium / {low} low)",
        )
    )
    for issue in audit.issues[:6]:
        findings.append(Finding(issue.severity, "dependencies", issue.message, issue.file))

    # ---------------------------------------------------------- security
    critical_secrets = sum(1 for item in analysis.secret_findings if item.severity == "critical")
    high_secrets = sum(1 for item in analysis.secret_findings if item.severity == "high")
    medium_secrets = sum(1 for item in analysis.secret_findings if item.severity == "medium")
    critical_files = sum(1 for item in analysis.sensitive_files if item.severity == "critical")
    security_score = max(
        0,
        WEIGHTS["security"]
        - (critical_secrets * 8 + high_secrets * 5 + medium_secrets * 2 + critical_files * 4),
    )
    secrets_count = len(analysis.secret_findings)
    report.factors.append(
        Factor(
            "security",
            "Secret hygiene",
            WEIGHTS["security"],
            security_score,
            "no credential-shaped strings or sensitive filenames detected"
            if secrets_count == 0 and not analysis.sensitive_files
            else f"{secrets_count} possible secret(s), {len(analysis.sensitive_files)} sensitive file(s)",
        )
    )
    for secret in analysis.secret_findings[:6]:
        findings.append(
            Finding(
                _finding_severity(secret.severity),
                "security",
                f"{secret.description} [{secret.rule}] fingerprint {secret.fingerprint} "
                f"(append a `cbi-ignore-secret` comment to accept it)",
                f"{secret.file}:{secret.line}",
            )
        )
    for sensitive in analysis.sensitive_files[:4]:
        findings.append(
            Finding(_finding_severity(sensitive.severity), "security", sensitive.description, sensitive.file)
        )

    # ---------------------------------------------------------------- ci
    ci_path = _any(
        analysis,
        lambda rel: bool(
            (rel.startswith(".github/workflows/") and rel.endswith((".yml", ".yaml")))
            or rel.lower()
            in {
                ".gitlab-ci.yml",
                "jenkinsfile",
                "azure-pipelines.yml",
                "bitbucket-pipelines.yml",
                ".travis.yml",
                ".drone.yml",
                "buildkite.yml",
            }
            or rel.lower() == ".circleci/config.yml"
        ),
    )
    report.factors.append(
        Factor(
            "ci",
            "Continuous integration",
            WEIGHTS["ci"],
            WEIGHTS["ci"] if ci_path else 0,
            ci_path or "no CI configuration found",
        )
    )
    if not ci_path:
        findings.append(
            Finding(
                MEDIUM,
                "ci",
                'No CI configuration. Nothing runs the tests on a fresh machine, so "works locally" is the only guarantee.',
            )
        )

    # -------------------------------------------------------------- docs
    readme = _any(analysis, lambda rel: rel.lower().startswith("readme"))
    license_file = _any(analysis, lambda rel: rel.lower().startswith(("license", "licence")))
    contributing = _any(analysis, lambda rel: rel.lower().startswith("contributing"))
    changelog = _any(analysis, lambda rel: rel.lower().startswith("changelog"))
    docs_dir = _any(analysis, lambda rel: rel.startswith("docs/"))
    security_doc = _any(analysis, lambda rel: rel.lower().startswith(("security.md", "code_of_conduct")))

    docs_score = 0
    docs_score += 4 if readme else 0
    docs_score += 2 if license_file else 0
    docs_score += 1 if contributing else 0
    docs_score += 1 if changelog else 0
    docs_score += 1 if docs_dir else 0
    docs_score += 1 if security_doc else 0
    missing = [
        name
        for name, present in (
            ("README", readme),
            ("LICENSE", license_file),
            ("CONTRIBUTING", contributing),
            ("CHANGELOG", changelog),
        )
        if not present
    ]
    report.factors.append(
        Factor(
            "docs",
            "Documentation",
            WEIGHTS["docs"],
            docs_score,
            "README, LICENSE and contributor docs all present"
            if not missing
            else f"missing: {', '.join(missing)}",
        )
    )
    if not readme:
        findings.append(
            Finding(HIGH, "docs", "No README. Nobody can evaluate the project without reading the source.")
        )
    elif missing:
        findings.append(Finding(LOW, "docs", f"Documentation gaps: {', '.join(missing)}"))

    # -------------------------------------------------------- type safety
    has_type_config = _has_basename(analysis, "mypy.ini", ".mypy.ini", "pyrightconfig.json", "py.typed")
    has_type_section = "mypy" in tooling or "pyright" in tooling
    annotated, total = _annotation_ratio(analysis)
    if has_type_config or has_type_section:
        type_score = WEIGHTS["type_safety"]
        type_detail = (
            "mypy / pyright configured" if has_type_config else "mypy / pyright configured in pyproject.toml"
        )
    elif total and annotated / total >= 0.8:
        type_score, type_detail = 6, f"{annotated}/{total} functions annotated, no checker configured"
    else:
        type_score, type_detail = 0, "no static type checking configured"
    report.factors.append(
        Factor("type_safety", "Type safety", WEIGHTS["type_safety"], type_score, type_detail)
    )

    # -------------------------------------------------------- lint/format
    lint_found: list[str] = []
    for key, label in (("ruff", "ruff"), ("black", "black"), ("isort", "isort"), ("pylint", "pylint")):
        if key in tooling:
            lint_found.append(f"{label} (pyproject.toml)")
    for name, label in (
        ("ruff.toml", "ruff"),
        (".ruff.toml", "ruff"),
        (".flake8", "flake8"),
        ("setup.cfg", "setup.cfg"),
        ("biome.json", "biome"),
        (".eslintrc.json", "eslint"),
        (".prettierrc", "prettier"),
    ):
        if _has_basename(analysis, name):
            lint_found.append(label)
    unique_lint = sorted(set(lint_found))
    lint_score = WEIGHTS["lint_format"] if unique_lint else 0
    report.factors.append(
        Factor(
            "lint_format",
            "Lint & formatting",
            WEIGHTS["lint_format"],
            lint_score,
            ", ".join(unique_lint) if unique_lint else "no linter or formatter configured",
        )
    )
    if not unique_lint:
        findings.append(
            Finding(
                LOW,
                "lint_format",
                "No linter or formatter configured — style debates get settled in code review instead of CI.",
            )
        )

    # ---------------------------------------------------------- file size
    large = [item for item in analysis.files if item.loc.lines > LARGE_FILE_LINES]
    very_large = [item for item in analysis.files if item.loc.lines > VERY_LARGE_FILE_LINES]
    size_score = max(0, round(WEIGHTS["file_size"] - len(large) * 0.7 - len(very_large) * 1.3))
    report.factors.append(
        Factor(
            "file_size",
            "File size discipline",
            WEIGHTS["file_size"],
            size_score,
            f"no file over {LARGE_FILE_LINES} lines"
            if not large
            else f"{len(large)} file(s) over {LARGE_FILE_LINES} lines, {len(very_large)} over {VERY_LARGE_FILE_LINES}",
        )
    )
    for item in very_large[:5]:
        findings.append(
            Finding(
                LOW,
                "file_size",
                f"{item.rel} is {item.loc.lines} lines. Long files hide coupled responsibilities.",
                item.rel,
            )
        )

    # --------------------------------------------------------------- debt
    density = len(analysis.todos) / (analysis.code_lines / 1000) if analysis.code_lines else 0.0
    debt_score = WEIGHTS["debt"] if density == 0 else 4 if density < 2 else 2 if density < 5 else 0
    report.factors.append(
        Factor(
            "debt",
            "Tech-debt markers",
            WEIGHTS["debt"],
            debt_score,
            f"{len(analysis.todos)} marker(s), {density:.2f} per 1k code lines",
        )
    )

    total_weight = sum(WEIGHTS.values())
    earned = sum(factor.earned for factor in report.factors)
    score = max(0, min(100, round(earned / total_weight * 100)))
    report.score = score
    report.grade = grade_of(score)

    order = {HIGH: 0, MEDIUM: 1, LOW: 2}
    findings.sort(key=lambda finding: order.get(finding.severity, 3))
    report.findings = findings

    worst = [finding.area for finding in findings if finding.severity == HIGH][:2]
    headline = (
        f"{score}/100 ({report.grade}) across {len(analysis.files)} text files, "
        f"{analysis.code_lines} code lines, {analysis.bytes} bytes"
    )
    report.summary = headline if not worst else f"{headline} — priority: {', '.join(dict.fromkeys(worst))}"
    return report


def _detect_runner(analysis: Analysis) -> str | None:
    if _has_basename(analysis, "pytest.ini", "conftest.py", "tox.ini"):
        return "pytest"
    if _has_basename(analysis, "vitest.config.ts", "vitest.config.js"):
        return "vitest"
    if _has_basename(analysis, "jest.config.js", "jest.config.ts"):
        return "jest"
    if _has_basename(analysis, "phpunit.xml"):
        return "phpunit"
    return None


def _read(analysis: Analysis) -> dict[str, Any]:
    """Parsed ``pyproject.toml`` when present, else an empty mapping."""
    import tomllib

    for item in analysis.walk.files:
        if item.path.name == "pyproject.toml":
            try:
                return tomllib.loads(item.path.read_text(encoding="utf-8", errors="replace"))
            except (OSError, tomllib.TOMLDecodeError):
                return {}
    return {}


def _annotation_ratio(analysis: Analysis) -> tuple[int, int]:
    """(annotated, total) top-level functions in Python files.

    A cheap proxy for type-safety discipline that does not need a checker to be
    installed.
    """
    import ast

    annotated = 0
    total = 0
    for item in analysis.files:
        if item.language != "Python" or not item.rel.endswith(".py"):
            continue
        try:
            tree = ast.parse((analysis.root / item.rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                if node.returns is not None:
                    annotated += 1
    return annotated, total
