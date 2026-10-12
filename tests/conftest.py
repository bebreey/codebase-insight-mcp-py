"""Shared pytest fixtures.

``tests/fixtures/sample-repo`` is *analysis input*, not a test of this project:
it contains its own ``tests/`` directory and a deliberately broken-looking
``.gitignore``. Collection has to skip it or pytest tries to import a package
that only exists inside the fixture.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

# Directories pytest must not collect (paths are relative to this file).
collect_ignore = ["fixtures"]

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample-repo"


@pytest.fixture(scope="session")
def fixture_repo() -> Path:
    """The checked-in fixture repository, used as analyser input."""
    assert FIXTURE_REPO.is_dir(), f"missing fixture repository: {FIXTURE_REPO}"
    return FIXTURE_REPO


@pytest.fixture
def temp_tree(tmp_path: Path) -> Iterator[Callable[[dict[str, str]], Path]]:
    """Factory that writes a throwaway tree and returns its root."""

    created: list[Path] = []

    def build(files: dict[str, str]) -> Path:
        root = tmp_path / f"tree{len(created)}"
        root.mkdir(parents=True, exist_ok=True)
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        created.append(root)
        return root

    yield build

    for root in created:
        shutil.rmtree(root, ignore_errors=True)
