"""End-to-end protocol test.

Spawns the *installed* server as a real child process and speaks newline
delimited JSON-RPC 2.0 over its stdio pipes. This is the only layer that can
catch the two failure modes that matter most for a stdio MCP server:

* a broken handshake, and
* a stray line on stdout, which corrupts the frame stream and makes the client
  drop the connection without any useful error.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

PROTOCOL_VERSION = "2025-06-18"
TOOL_NAMES = {"repo_overview", "find_todos", "search_symbols", "audit_dependencies", "assess_health"}
RESPONSE_TIMEOUT_SECONDS = 90


class StdioClient:
    """Minimal JSON-RPC client over a child process' stdio."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        merged = {**os.environ, **(env or {})}
        merged.pop("CBI_DEBUG", None)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "codebase_insight"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=merged,
        )
        self.lines: queue.Queue[str] = queue.Queue()
        self.violations: list[str] = []
        self.stderr: list[str] = []
        self._next_id = 1

        threading.Thread(target=self._pump_stdout, daemon=True).start()
        threading.Thread(target=self._pump_stderr, daemon=True).start()

    def _pump_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            stripped = line.strip()
            if stripped == "":
                continue
            try:
                json.loads(stripped)
            except json.JSONDecodeError:
                self.violations.append(stripped)
                continue
            self.lines.put(stripped)

    def _pump_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip("\n"))

    def _write(self, payload: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})

        deadline = time.monotonic() + RESPONSE_TIMEOUT_SECONDS
        while True:
            try:
                raw = self.lines.get(timeout=max(0.1, deadline - time.monotonic()))
            except queue.Empty:
                self.close()
                raise AssertionError(
                    f"timed out after {RESPONSE_TIMEOUT_SECONDS}s waiting for {method}; "
                    f"stderr so far: {self.stderr[-5:]}"
                ) from None
            message = json.loads(raw)
            if message.get("id") == request_id:
                return message
            if self.proc.poll() is not None and self.lines.empty():
                # The child died without answering: report it instead of hanging.
                self.close()
                raise AssertionError(
                    f"the server exited (code {self.proc.returncode}) while answering {method}; "
                    f"stderr: {self.stderr[-8:]}"
                )

    def initialize(self) -> dict[str, Any]:
        response = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "codebase-insight-e2e", "version": "1.0.0"},
            },
        )
        self.notify("notifications/initialized")
        return response["result"]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})["result"]

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=10)


@pytest.fixture
def client() -> Iterator[StdioClient]:
    instance = StdioClient()
    try:
        yield instance
    finally:
        instance.close()


def test_initialize_handshake(client: StdioClient) -> None:
    result = client.initialize()

    assert result["serverInfo"]["name"] == "codebase-insight-mcp-py"
    assert result["serverInfo"]["version"] == "1.0.0"
    assert result["protocolVersion"] == PROTOCOL_VERSION
    assert "tools" in result["capabilities"]
    assert result["instructions"]


def test_tools_list_advertises_schemas(client: StdioClient) -> None:
    client.initialize()
    tools = client.request("tools/list")["result"]["tools"]

    assert {tool["name"] for tool in tools} == TOOL_NAMES
    for tool in tools:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        # The output schema comes from the return type annotation.
        assert tool["outputSchema"]["type"] == "object"
        assert tool["annotations"]["readOnlyHint"] is True
        assert tool["annotations"]["openWorldHint"] is False


def test_every_tool_answers_over_the_wire(client: StdioClient, fixture_repo: Path) -> None:
    client.initialize()

    for name in sorted(TOOL_NAMES):
        result = client.call_tool(name, {"path": str(fixture_repo)})
        assert result.get("isError") is not True, f"{name} returned an error: {result}"
        assert result["structuredContent"], f"{name} returned no structured content"
        assert result["content"], f"{name} returned no text content"


def test_stdout_carries_nothing_but_json(client: StdioClient, fixture_repo: Path) -> None:
    client.initialize()
    for name in sorted(TOOL_NAMES):
        client.call_tool(name, {"path": str(fixture_repo)})

    assert client.violations == [], f"non-JSON output on stdout: {client.violations[:3]}"
    # Nothing writes to stderr unless CBI_DEBUG is set.
    assert client.stderr == []


def test_tool_error_becomes_an_error_result_not_a_protocol_error(
    client: StdioClient, fixture_repo: Path
) -> None:
    client.initialize()

    result = client.call_tool("repo_overview", {"path": "D:/definitely/not/here"})
    assert result["isError"] is True
    assert "does not exist or is not readable" in result["content"][0]["text"]

    # The session must still be usable afterwards.
    recovered = client.call_tool("repo_overview", {"path": str(fixture_repo)})
    assert recovered.get("isError") is not True


def test_cbi_roots_is_enforced_over_the_wire(fixture_repo: Path) -> None:
    restricted = StdioClient(env={"CBI_ROOTS": str(fixture_repo)})
    try:
        restricted.initialize()

        allowed = restricted.call_tool("repo_overview", {"path": str(fixture_repo)})
        assert allowed.get("isError") is not True

        denied = restricted.call_tool("repo_overview", {"path": str(fixture_repo.parent)})
        assert denied["isError"] is True
        assert "CBI_ROOTS" in denied["content"][0]["text"]
    finally:
        restricted.close()


@pytest.mark.parametrize("flag", ["--version", "--help", "--list-tools"])
def test_cli_flags_work_without_starting_a_session(flag: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "codebase_insight", flag],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip()
    if flag == "--list-tools":
        for name in TOOL_NAMES:
            assert name in completed.stdout


NON_ASCII_REPO = {
    "src/module.py": (
        '"""中文模块文档。"""\n\n'
        "VALUE = 1\n\n\n"
        "# TODO: 这里需要重构 —— 先把依赖拆开\n"
        "class 计算器:\n"
        "    def 相加(self, a, b):\n"
        "        return a + b\n"
    ),
    "docs/笔记.md": "# 中文笔记\n\n- [ ] TODO：补测试\n",
}


def test_non_ascii_content_crosses_the_wire(
    client: StdioClient, temp_tree: Callable[[dict[str, str]], Path]
) -> None:
    """A codebase full of Chinese comments must survive the JSON-RPC channel."""
    root = temp_tree(NON_ASCII_REPO)
    client.initialize()

    result = client.call_tool("find_todos", {"path": str(root)})

    assert result.get("isError") is not True, result
    assert result["structuredContent"]["total"] == 2
    assert "重构" in result["content"][0]["text"]

    symbols = client.call_tool("search_symbols", {"path": str(root), "languages": ["Python"]})
    items = {row["name"]: row["kind"] for row in symbols["structuredContent"]["items"]}
    # Non-ASCII identifiers are extracted like any other: the ast module does
    # not care what the letters are.
    assert items["计算器"] == "class"
    assert items["相加"] == "method"
    assert items["VALUE"] == "constant"


def test_non_ascii_content_survives_a_non_utf8_stdout(temp_tree: Callable[[dict[str, str]], Path]) -> None:
    """Regression: the default Windows console code page cannot encode CJK at all.

    ``PYTHONIOENCODING=cp1252`` reproduces that condition on any platform, so the
    server has to write UTF-8 regardless of what the environment asks for.
    """
    root = temp_tree(NON_ASCII_REPO)

    client = StdioClient(env={"PYTHONIOENCODING": "cp1252"})
    try:
        client.initialize()

        result = client.call_tool("find_todos", {"path": str(root)})
        assert result.get("isError") is not True, result
        assert result["structuredContent"]["total"] == 2
        assert client.violations == []

        # The session must still work afterwards.
        assert client.call_tool("repo_overview", {"path": str(root)}).get("isError") is not True
    finally:
        client.close()
