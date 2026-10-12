"""Dependency manifest discovery and hygiene audit.

TOML is parsed with the standard library ``tomllib``, so ``pyproject.toml`` and
``Cargo.toml`` are read exactly rather than scanned with heuristics. The
TypeScript implementation documented that limitation explicitly; having a real
TOML parser in the standard library is the reason this version does not need
the caveat.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from ..logger import debug
from . import walk

EXACT = "exact"
RANGE = "range"
FLOATING = "floating"
URL = "url"
UNPINNED = "unpinned"
UNKNOWN = "unknown"

RUNTIME = "runtime"
DEV = "dev"
OPTIONAL = "optional"
BUILD = "build"


@dataclass(frozen=True, slots=True)
class Dependency:
    name: str
    spec: str
    ecosystem: str
    kind: str
    pin: str


@dataclass(slots=True)
class ManifestReport:
    file: str
    ecosystem: str
    package_name: str = ""
    dependencies: list[Dependency] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Lockfile:
    file: str
    ecosystem: str


@dataclass(frozen=True, slots=True)
class Issue:
    severity: str
    code: str
    message: str
    file: str


@dataclass(slots=True)
class Audit:
    manifests: list[ManifestReport] = field(default_factory=list)
    lockfiles: list[Lockfile] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    runtime: int = 0
    dev: int = 0
    other: int = 0
    floating: int = 0
    unpinned: int = 0
    url: int = 0


_MANIFESTS: dict[str, str] = {
    "pyproject.toml": "poetry",
    "requirements.txt": "pip",
    "requirements-dev.txt": "pip",
    "setup.py": "pip",
    "package.json": "npm",
    "cargo.toml": "cargo",
    "go.mod": "go",
    "composer.json": "composer",
    "gemfile": "bundler",
}

_LOCKFILES: tuple[tuple[str, str, str], ...] = (
    # (lockfile, ecosystem, manifest it belongs to)
    ("package-lock.json", "npm", "package.json"),
    ("pnpm-lock.yaml", "npm", "package.json"),
    ("yarn.lock", "npm", "package.json"),
    ("bun.lockb", "npm", "package.json"),
    ("poetry.lock", "poetry", "pyproject.toml"),
    ("uv.lock", "pip", "pyproject.toml"),
    ("Pipfile.lock", "pip", "Pipfile"),
    ("Cargo.lock", "cargo", "Cargo.toml"),
    ("go.sum", "go", "go.mod"),
)

_NPM_URL = re.compile(
    r"^(?:git\+|git:|github:|https?:|file:|link:|workspace:|npm:|portal:|patch:)", re.IGNORECASE
)
_NPM_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_SEMVER_EXACT = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
_REQ_NAME = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*(?P<spec>.*)$")


def classify_npm(spec: str) -> str:
    value = spec.strip()
    if value == "":
        return UNPINNED
    if value in {"*", "latest", "x", "X"}:
        return FLOATING
    if _NPM_URL.match(value):
        return URL
    cleaned = re.sub(r"^[=v]\s*", "", value)
    if _NPM_EXACT.match(cleaned):
        return EXACT
    if re.search(r"[<>^~|]|[*xX]", cleaned):
        return RANGE
    return RANGE


def classify_semver(spec: str) -> str:
    value = spec.strip()
    if value == "":
        return UNPINNED
    if value in {"*", "latest"}:
        return FLOATING
    if re.search(r"https?:|//|git\+|file:", value):
        return URL
    cleaned = re.sub(r"^[=v^~]\s*", "", value)
    if _SEMVER_EXACT.match(cleaned):
        return RANGE if value[:1] in {"^", "~"} else EXACT
    return RANGE


def classify_python(spec: str) -> str:
    value = spec.strip()
    if value == "":
        return UNPINNED
    if value == "*":
        return FLOATING
    if re.search(r"git\+|https?://|file:|svn\+|hg\+", value):
        return URL
    if value.startswith("==="):
        return EXACT
    if value.startswith("=="):
        return RANGE if re.search(r"[*xX]", value) else EXACT
    if re.match(r"^(?:>=|<=|~=|!=|>|<)", value):
        return RANGE
    # Poetry / PEP 621 constraints with no pip operator: `^0.27`, `~0.27`, `0.27`.
    if re.match(r"^[~^]?\s*v?\d", value):
        return RANGE
    return UNKNOWN


def _split_requirement(entry: str) -> tuple[str, str]:
    match = _REQ_NAME.match(entry.strip())
    if match is None:
        return entry.strip(), ""
    return match.group("name"), match.group("spec").strip()


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #


def _parse_pyproject(rel: str, text: str) -> ManifestReport:
    report = ManifestReport(file=rel, ecosystem="poetry")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        report.notes.append(f"pyproject.toml could not be parsed: {exc}")
        return report

    project = data.get("project", {})
    if isinstance(project, dict):
        report.package_name = str(project.get("name", ""))
        for entry in project.get("dependencies", []) or []:
            name, spec = _split_requirement(str(entry))
            report.dependencies.append(Dependency(name, spec, "poetry", RUNTIME, classify_python(spec)))
        optional = project.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for group, entries in optional.items():
                for entry in entries or []:
                    name, spec = _split_requirement(str(entry))
                    report.dependencies.append(Dependency(name, spec, "poetry", DEV, classify_python(spec)))
                report.notes.append(f"optional dependency group: {group}")

    poetry = data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
    if isinstance(poetry, dict):
        report.package_name = report.package_name or str(poetry.get("name", ""))
        for section, kind in (
            ("dependencies", RUNTIME),
            ("dev-dependencies", DEV),
        ):
            block = poetry.get(section, {})
            if isinstance(block, dict):
                for name, value in block.items():
                    if name.lower() == "python":
                        continue
                    spec = value.get("version", "") if isinstance(value, dict) else str(value)
                    report.dependencies.append(
                        Dependency(str(name), str(spec), "poetry", kind, classify_python(str(spec)))
                    )
        groups = poetry.get("group", {})
        if isinstance(groups, dict):
            for group_name, block in groups.items():
                deps = block.get("dependencies", {}) if isinstance(block, dict) else {}
                for name, value in (deps or {}).items():
                    spec = value.get("version", "") if isinstance(value, dict) else str(value)
                    report.dependencies.append(
                        Dependency(str(name), str(spec), "poetry", DEV, classify_python(str(spec)))
                    )
                report.notes.append(f"poetry group: {group_name}")

    return report


def _parse_cargo(rel: str, text: str) -> ManifestReport:
    report = ManifestReport(file=rel, ecosystem="cargo")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        report.notes.append(f"Cargo.toml could not be parsed: {exc}")
        return report

    package = data.get("package", {})
    if isinstance(package, dict):
        report.package_name = str(package.get("name", ""))

    for section, kind in (
        ("dependencies", RUNTIME),
        ("dev-dependencies", DEV),
        ("build-dependencies", BUILD),
    ):
        block = data.get(section, {})
        if not isinstance(block, dict):
            continue
        for name, value in block.items():
            spec = value.get("version", "") if isinstance(value, dict) else str(value)
            report.dependencies.append(
                Dependency(str(name), str(spec), "cargo", kind, classify_semver(str(spec)))
            )

    if "workspace" in data:
        report.notes.append("cargo workspace")
    return report


def _parse_package_json(rel: str, text: str) -> ManifestReport:
    report = ManifestReport(file=rel, ecosystem="npm")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.notes.append(f"package.json could not be parsed: {exc}")
        return report

    report.package_name = str(data.get("name", ""))
    for section, kind in (
        ("dependencies", RUNTIME),
        ("devDependencies", DEV),
        ("peerDependencies", OPTIONAL),
        ("optionalDependencies", OPTIONAL),
    ):
        block = data.get(section)
        if isinstance(block, dict):
            for name, spec in block.items():
                report.dependencies.append(
                    Dependency(str(name), str(spec), "npm", kind, classify_npm(str(spec)))
                )

    package_manager = data.get("packageManager")
    if isinstance(package_manager, str):
        report.notes.append(f"packageManager pinned to {package_manager}")
    if isinstance(data.get("workspaces"), (list, dict)):
        report.notes.append("monorepo workspaces declared")
    return report


def _parse_composer(rel: str, text: str) -> ManifestReport:
    report = ManifestReport(file=rel, ecosystem="composer")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        report.notes.append(f"composer.json could not be parsed: {exc}")
        return report

    report.package_name = str(data.get("name", ""))
    for section, kind in (("require", RUNTIME), ("require-dev", DEV)):
        block = data.get(section)
        if isinstance(block, dict):
            for name, spec in block.items():
                report.dependencies.append(
                    Dependency(str(name), str(spec), "composer", kind, classify_semver(str(spec)))
                )
    return report


def _parse_requirements(rel: str, text: str) -> ManifestReport:
    report = ManifestReport(file=rel, ecosystem="pip")
    for raw in text.splitlines():
        # Strip trailing comments, but keep `#egg=` URL fragments: `#` only
        # starts a comment when it follows whitespace.
        line = re.sub(r"\s+#.*$", "", raw).strip()
        if line == "" or line.startswith("#"):
            continue

        if re.match(r"^(?:-r|--requirement)\s", line):
            report.notes.append(f"includes another requirements file: {line}")
            continue

        if "://" in line or line.startswith("-e ") or line.startswith("git+"):
            fragment = line.split("#egg=")[-1] if "#egg=" in line else line.rstrip("/").rsplit("/", 1)[-1]
            report.dependencies.append(
                Dependency(re.sub(r"[?#].*$", "", fragment), line, "pip", RUNTIME, URL)
            )
            continue

        if line.startswith("-"):
            continue

        name, spec = _split_requirement(line)
        if name:
            report.dependencies.append(Dependency(name, spec, "pip", RUNTIME, classify_python(spec)))
    return report


def _parse_go_mod(rel: str, text: str) -> ManifestReport:
    report = ManifestReport(file=rel, ecosystem="go")
    in_require = False

    for raw in text.splitlines():
        line = raw.split("//")[0].strip()
        if line == "":
            continue
        if line.startswith("module "):
            report.package_name = line.removeprefix("module ").strip()
            continue
        if line.startswith("go "):
            report.notes.append(f"language version {line.removeprefix('go ').strip()}")
            continue
        if line.startswith("require (") or line == "require(":
            in_require = True
            continue
        if in_require and line == ")":
            in_require = False
            continue

        single = re.match(r"^require\s+(\S+)\s+(\S+)", line)
        if single:
            report.dependencies.append(Dependency(single.group(1), single.group(2), "go", RUNTIME, EXACT))
            continue

        if in_require:
            entry = re.match(r"^(\S+)\s+(\S+)", line)
            if entry:
                report.dependencies.append(Dependency(entry.group(1), entry.group(2), "go", RUNTIME, EXACT))
    return report


def _parse_manifest(path: Path, rel: str, ecosystem: str) -> ManifestReport | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    name = path.name.lower()
    try:
        if name == "pyproject.toml":
            return _parse_pyproject(rel, text)
        if name == "cargo.toml":
            return _parse_cargo(rel, text)
        if name == "package.json":
            return _parse_package_json(rel, text)
        if name == "composer.json":
            return _parse_composer(rel, text)
        if name == "go.mod":
            return _parse_go_mod(rel, text)
        if name.startswith("requirements") or name == "setup.py":
            return _parse_requirements(rel, text)
    except Exception as exc:
        debug(f"failed to parse {rel}: {exc}")
        return ManifestReport(file=rel, ecosystem=ecosystem, notes=[f"could not parse this manifest: {exc}"])
    return None


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


def audit(root: Path, *, extra_ignore: tuple[str, ...] = ()) -> Audit:
    """Discover manifests, probe lockfiles and collect hygiene issues."""
    result = Audit()
    discovery = walk.walk(root, max_depth=4, extra_ignore=extra_ignore)

    for item in discovery.files:
        ecosystem = _MANIFESTS.get(item.path.name.lower())
        if ecosystem is None:
            continue
        report = _parse_manifest(item.path, item.rel, ecosystem)
        if report is not None:
            result.manifests.append(report)

    result.manifests.sort(key=lambda report: report.file)

    directories: dict[str, None] = {"": None}
    for manifest in result.manifests:
        parent = manifest.file.rsplit("/", 1)[0] if "/" in manifest.file else ""
        directories.setdefault(parent, None)

    for directory in directories:
        for lock_name, ecosystem, _ in _LOCKFILES:
            rel = lock_name if directory == "" else f"{directory}/{lock_name}"
            if (root / rel).is_file():
                result.lockfiles.append(Lockfile(rel, ecosystem))

    unique: dict[str, Lockfile] = {}
    for lock in result.lockfiles:
        unique.setdefault(lock.file, lock)
    result.lockfiles = sorted(unique.values(), key=lambda lock: lock.file)

    for manifest in result.manifests:
        for dependency in manifest.dependencies:
            if dependency.kind == RUNTIME:
                result.runtime += 1
            elif dependency.kind == DEV:
                result.dev += 1
            else:
                result.other += 1
            if dependency.pin == FLOATING:
                result.floating += 1
            elif dependency.pin == UNPINNED:
                result.unpinned += 1
            elif dependency.pin == URL:
                result.url += 1

    _collect_issues(result)
    debug(f"dependency audit: {len(result.manifests)} manifest(s), {len(result.lockfiles)} lockfile(s)")
    return result


def _collect_issues(result: Audit) -> None:
    locks_by_dir: dict[str, list[Lockfile]] = {}
    for lock in result.lockfiles:
        parent = lock.file.rsplit("/", 1)[0] if "/" in lock.file else ""
        locks_by_dir.setdefault(parent, []).append(lock)

    for directory, locks in locks_by_dir.items():
        npm_locks = [lock for lock in locks if lock.ecosystem == "npm"]
        if len(npm_locks) > 1:
            names = ", ".join(lock.file.rsplit("/", 1)[-1] for lock in npm_locks)
            where = "the repository root" if directory == "" else directory
            result.issues.append(
                Issue(
                    "medium",
                    "multiple-lockfiles",
                    f"Multiple npm lockfiles in {where}: {names} — pick one package manager",
                    directory,
                )
            )

    for manifest in result.manifests:
        parent = manifest.file.rsplit("/", 1)[0] if "/" in manifest.file else ""
        matching = [lock for lock in locks_by_dir.get(parent, []) if lock.ecosystem == manifest.ecosystem]
        if not matching and manifest.ecosystem in {"npm", "cargo", "poetry"}:
            result.issues.append(
                Issue(
                    "medium",
                    "missing-lockfile",
                    f"No lockfile found next to {manifest.file} — dependency resolution is not recorded",
                    manifest.file,
                )
            )

        floating = [d for d in manifest.dependencies if d.pin in {FLOATING, URL}]
        if floating:
            sample = ", ".join(f"{d.name}@{d.spec}" for d in floating[:5])
            result.issues.append(
                Issue(
                    "medium",
                    "floating-dependency",
                    f"{len(floating)} dependency/ies in {manifest.file} resolve to a moving target: {sample}",
                    manifest.file,
                )
            )

        if manifest.ecosystem == "pip":
            unpinned = [d for d in manifest.dependencies if d.pin == UNPINNED]
            if unpinned:
                names = ", ".join(d.name for d in unpinned[:5])
                result.issues.append(
                    Issue(
                        "medium",
                        "unpinned-requirements",
                        f"{len(unpinned)} requirement(s) in {manifest.file} have no version specifier: {names}",
                        manifest.file,
                    )
                )

        runtime_names = {d.name for d in manifest.dependencies if d.kind == RUNTIME}
        duplicated = [d.name for d in manifest.dependencies if d.kind == DEV and d.name in runtime_names]
        if duplicated:
            result.issues.append(
                Issue(
                    "low",
                    "duplicate-dependency-section",
                    f"{', '.join(duplicated)} declared in both runtime and dev sections of {manifest.file}",
                    manifest.file,
                )
            )

    order = {"high": 0, "medium": 1, "low": 2}
    result.issues.sort(key=lambda issue: order.get(issue.severity, 3))
