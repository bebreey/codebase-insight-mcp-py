"""Command line behaviour.

These run ``main`` in-process, so the flag handling is covered by the coverage
report. The transport itself is covered end-to-end by ``test_protocol.py``,
which spawns the real installed entry point.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest

from codebase_insight import SERVER_NAME, SERVER_VERSION
from codebase_insight.__main__ import main

TOOL_NAMES = ("repo_overview", "find_todos", "search_symbols", "audit_dependencies", "assess_health")


def test_version_flag(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [SERVER_NAME, "--version"])
    main()

    output = capsys.readouterr().out
    assert SERVER_NAME in output
    assert SERVER_VERSION in output


def test_short_version_flag(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [SERVER_NAME, "-v"])
    main()
    assert SERVER_VERSION in capsys.readouterr().out


def test_help_lists_the_environment_variables(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "argv", [SERVER_NAME, "--help"])
    main()

    output = capsys.readouterr().out
    for variable in ("CBI_DEFAULT_ROOT", "CBI_ROOTS", "CBI_MAX_FILES", "CBI_MAX_DEPTH", "CBI_DEBUG"):
        assert variable in output
    assert "mcpServers" in output


def test_list_tools(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [SERVER_NAME, "--list-tools"])
    main()

    output = capsys.readouterr().out
    assert "5 tools" in output
    for name in TOOL_NAMES:
        assert name in output


def test_default_invocation_starts_the_stdio_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, Any] = {}

    class StubServer:
        def run(self, **kwargs: Any) -> None:
            recorded.update(kwargs)

    monkeypatch.setattr("codebase_insight.__main__.create_server", StubServer)
    monkeypatch.setattr(sys, "argv", [SERVER_NAME])
    main()

    assert recorded == {"transport": "stdio"}
