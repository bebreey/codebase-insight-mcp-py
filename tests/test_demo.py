"""The demo script, run the way CI runs it.

The first Windows CI run failed here and nowhere else: the tests passed, then
``scripts/demo.py`` died with ``UnicodeEncodeError`` because the default Windows
code page cannot encode the arrow in its output. Printing repository content on
a non-UTF-8 console is a real failure mode, not a cosmetic one, so it is pinned
by a test that reproduces the CI condition on every platform.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO = REPO_ROOT / "scripts" / "demo.py"


def run_demo(target: Path, **env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "CBI_DEBUG": "", "PYTHONIOENCODING": "utf-8", **env_overrides}
    env.pop("CBI_DEBUG", None)
    return subprocess.run(
        [sys.executable, str(DEMO), str(target)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=env,
        check=False,
    )


def test_demo_runs_against_the_fixture_repository(fixture_repo: Path) -> None:
    completed = run_demo(fixture_repo)

    assert completed.returncode == 0, completed.stderr
    assert "connected" in completed.stdout
    assert "5 tools advertised" in completed.stdout
    for tool in ("repo_overview", "find_todos", "search_symbols", "audit_dependencies", "assess_health"):
        assert tool in completed.stdout
    assert "every tool answered over stdio" in completed.stdout


def test_demo_survives_a_non_utf8_stdout(fixture_repo: Path) -> None:
    """Regression: the Windows CI failure.

    ``PYTHONIOENCODING=cp1252`` reproduces the default Windows console code page
    on any platform, so this test fails wherever the demo is not encoding-safe.
    """
    completed = run_demo(fixture_repo, PYTHONIOENCODING="cp1252")

    assert completed.returncode == 0, completed.stderr
    assert "UnicodeEncodeError" not in completed.stderr
    assert "every tool answered over stdio" in completed.stdout


def test_demo_handles_a_repository_full_of_non_ascii(tmp_path: Path) -> None:
    root = tmp_path / "unicode-repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "module.py").write_text(
        '"""中文模块文档。"""\n\n# TODO: 这里需要重构 —— 先把依赖拆开\n'
        "class 计算器:\n    def 相加(self, a, b):\n        return a + b\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# 中文仓库\n\n- [ ] TODO：补测试\n", encoding="utf-8")

    completed = run_demo(root, PYTHONIOENCODING="cp1252")

    assert completed.returncode == 0, completed.stderr
    assert "UnicodeEncodeError" not in completed.stderr
    assert "every tool answered over stdio" in completed.stdout


def test_demo_reports_a_missing_directory() -> None:
    completed = run_demo(Path("no/such/directory/at/all"))

    assert completed.returncode == 2
    assert "not a directory" in completed.stderr
