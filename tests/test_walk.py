"""Directory traversal, including real .gitignore support."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from codebase_insight.core import walk


def test_skips_well_known_build_directories(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    root = temp_tree(
        {
            "src/a.py": "x = 1\n",
            "node_modules/dep/index.js": "module.exports = 1;\n",
            "dist/bundle.js": "x\n",
            "__pycache__/a.cpython-311.pyc": "x\n",
            "README.md": "# hi\n",
        }
    )
    rels = {item.rel for item in walk.walk(root).files}
    assert rels == {"README.md", "src/a.py"}


def test_honours_gitignore_in_the_fixture_repository(fixture_repo: Path) -> None:
    """The showcase: a path listed in .gitignore never reaches the analysis.

    The ignored file is asserted to exist first. Without that check the test
    passes just as happily on a clone where the file was never committed —
    it would be proving nothing at all. It has to be force-added, because the
    fixture's own .gitignore is what the test is about.
    """
    ignored = fixture_repo / "src" / "sample" / "generated" / "blob.py"
    assert ignored.is_file(), f"fixture file missing (was it force-added?): {ignored}"

    result = walk.walk(fixture_repo)
    rels = {item.rel for item in result.files}

    assert "src/sample/calculator.py" in rels
    assert "src/sample/generated/blob.py" not in rels
    assert ".gitignore" in result.gitignore_files

    # And the symbols tool therefore never sees the generated declarations.
    assert not any(rel.startswith("src/sample/generated/") for rel in rels)


def test_honours_a_nested_gitignore(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    root = temp_tree(
        {
            ".gitignore": "*.log\n",
            "keep.py": "x = 1\n",
            "noisy.log": "x\n",
            "sub/.gitignore": "private/\n",
            "sub/keep.py": "x = 1\n",
            "sub/private/secret.py": "x = 1\n",
        }
    )
    rels = {item.rel for item in walk.walk(root).files}
    assert rels == {".gitignore", "keep.py", "sub/.gitignore", "sub/keep.py"}


def test_gitignore_can_be_disabled(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    root = temp_tree({".gitignore": "*.log\n", "noisy.log": "x\n"})
    rels = {item.rel for item in walk.walk(root, respect_gitignore=False).files}
    assert rels == {".gitignore", "noisy.log"}


def test_extra_ignore_patterns_skip_a_subtree(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    root = temp_tree({"keep.py": "x\n", "drop/a.py": "x\n", "drop-b/b.py": "x\n"})
    rels = {item.rel for item in walk.walk(root, extra_ignore=("drop",)).files}
    assert rels == {"drop-b/b.py", "keep.py"}


def test_honours_depth_and_file_limits(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    deep = temp_tree({"a/b/c/d.py": "x\n"})
    assert walk.walk(deep, max_depth=1).files == []
    assert walk.walk(deep, max_depth=1).truncated is True
    assert [item.rel for item in walk.walk(deep, max_depth=4).files] == ["a/b/c/d.py"]

    many = temp_tree({"a.py": "x\n", "b.py": "x\n", "c.py": "x\n"})
    limited = walk.walk(many, max_files=2)
    assert len(limited.files) == 2
    assert limited.truncated is True


def test_symlinks_are_never_followed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "real.py").write_text("x = 1\n", encoding="utf-8")

    link = root / "link.py"
    try:
        link.symlink_to(root / "real.py")
    except (OSError, NotImplementedError):  # pragma: no cover - needs privileges on Windows
        return

    rels = {item.rel for item in walk.walk(root).files}
    assert "link.py" not in rels


def test_load_ignore_file_parses_patterns(tmp_path: Path) -> None:
    (tmp_path / ".codebase-insight-ignore").write_text(
        "# comment\n\n./src/legacy\nbuild/\n", encoding="utf-8"
    )
    assert walk.load_ignore_file(tmp_path) == ("src/legacy", "build")
    assert walk.load_ignore_file(tmp_path / "missing") == ()
