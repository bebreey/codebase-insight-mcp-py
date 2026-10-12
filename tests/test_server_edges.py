"""Edge cases and limits in the tool layer.

The happy paths live in ``test_server.py``; this file covers the branches that
only fire on an awkward repository or an explicit limit, which is exactly the
kind of code that rots unnoticed.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer

from codebase_insight.server import create_server

pytestmark = pytest.mark.asyncio


@pytest.fixture(scope="module")
def server() -> MCPServer:
    return create_server()


async def test_overview_of_an_empty_directory(
    server: MCPServer, temp_tree: Callable[[dict[str, str]], Path]
) -> None:
    root = temp_tree({})
    data = (await server.call_tool("repo_overview", {"path": str(root)})).structured_content

    assert data["ecosystem"] == "unclassified"
    assert data["primary_language"] == ""
    assert data["totals"]["text_files"] == 0
    assert data["entry_points"] == []
    assert any("manifest" in note for note in data["notes"])


async def test_overview_reports_build_commands_for_several_ecosystems(
    server: MCPServer, temp_tree: Callable[[dict[str, str]], Path]
) -> None:
    root = temp_tree(
        {
            "package.json": '{"name":"x","scripts":{"build":"tsc","test":"vitest"}}',
            "Makefile": "all:\n\techo hi\n",
            "Cargo.toml": '[package]\nname = "x"\n',
            "go.mod": "module example.com/x\n",
        }
    )
    data = (await server.call_tool("repo_overview", {"path": str(root)})).structured_content
    commands = " ".join(data["build_commands"])

    assert "npm run build" in commands
    assert "make" in commands
    assert "cargo test" in commands
    assert "go test ./..." in commands


async def test_overview_notes_truncation(server: MCPServer, fixture_repo: Path) -> None:
    data = (
        await server.call_tool(
            "repo_overview", {"path": str(fixture_repo), "top_languages": 1, "top_files": 1}
        )
    ).structured_content

    assert data["totals"]["truncated"] is False
    assert len(data["languages"]) == 1
    assert len(data["largest_files"]) <= 1


async def test_overview_reaches_deeply_nested_files(
    server: MCPServer, temp_tree: Callable[[dict[str, str]], Path]
) -> None:
    root = temp_tree({"a/b/c/d.py": "value = 1\n"})
    data = (await server.call_tool("repo_overview", {"path": str(root)})).structured_content

    # The tool uses the configured default depth, so a nested file is reached.
    assert data["totals"]["files_on_disk"] == 1
    assert data["totals"]["truncated"] is False
    assert data["totals"]["code_lines"] == 1


async def test_find_todos_respects_the_limit(server: MCPServer, fixture_repo: Path) -> None:
    data = (await server.call_tool("find_todos", {"path": str(fixture_repo), "limit": 2})).structured_content

    assert data["total"] == 5
    assert data["returned"] == 2
    assert data["truncated"] is True
    assert any("raise `limit`" in note for note in data["notes"])
    assert len(data["files_with_most"]) >= 1


async def test_search_symbols_lists_everything_without_a_query(server: MCPServer, fixture_repo: Path) -> None:
    data = (await server.call_tool("search_symbols", {"path": str(fixture_repo)})).structured_content

    assert data["query"] == ""
    assert data["matched"] > 0
    assert any("No `query`" in note for note in data["notes"])
    assert "Python" in data["supported_languages"]
    assert data["by_language"][0]["key"] == "Python"


async def test_search_symbols_truncates_and_notes_it(server: MCPServer, fixture_repo: Path) -> None:
    data = (
        await server.call_tool("search_symbols", {"path": str(fixture_repo), "limit": 1})
    ).structured_content

    assert data["returned"] == 1
    assert data["truncated"] is True
    assert any("raise `limit`" in note for note in data["notes"])


async def test_search_symbols_with_no_matches(server: MCPServer, fixture_repo: Path) -> None:
    data = (
        await server.call_tool("search_symbols", {"path": str(fixture_repo), "query": "NoSuchSymbolAnywhere"})
    ).structured_content

    assert data["matched"] == 0
    assert data["items"] == []


async def test_audit_of_a_repository_without_manifests(
    server: MCPServer, temp_tree: Callable[[dict[str, str]], Path]
) -> None:
    root = temp_tree({"src/a.py": "value = 1\n"})
    data = (await server.call_tool("audit_dependencies", {"path": str(root)})).structured_content

    assert data["manifests"] == []
    assert data["lockfiles"] == []
    assert any("No supported dependency manifest" in note for note in data["notes"])


async def test_audit_preview_limit(server: MCPServer, fixture_repo: Path) -> None:
    data = (
        await server.call_tool("audit_dependencies", {"path": str(fixture_repo), "preview_limit": 1})
    ).structured_content

    assert len(data["least_pinned"]) == 1
    assert data["least_pinned"][0]["pin"] in {"floating", "unpinned", "url"}


async def test_health_on_an_empty_directory(
    server: MCPServer, temp_tree: Callable[[dict[str, str]], Path]
) -> None:
    root = temp_tree({})
    data = (await server.call_tool("assess_health", {"path": str(root)})).structured_content

    assert 0 <= data["score"] <= 100
    assert data["stats"]["code_files"] == 0
    # An empty directory cannot satisfy any factor except the trivial ones.
    assert any(finding["area"] == "tests" for finding in data["findings"])
    assert data["priority_actions"]


async def test_health_findings_can_be_capped(server: MCPServer, fixture_repo: Path) -> None:
    capped = (
        await server.call_tool("assess_health", {"path": str(fixture_repo), "top_findings": 1})
    ).structured_content
    full = (await server.call_tool("assess_health", {"path": str(fixture_repo)})).structured_content

    assert len(capped["findings"]) <= len(full["findings"])
    assert capped["score"] == full["score"]


async def test_health_redacts_credential_findings(server: MCPServer, fixture_repo: Path) -> None:
    data = (await server.call_tool("assess_health", {"path": str(fixture_repo)})).structured_content

    security = [finding for finding in data["findings"] if finding["area"] == "security"]
    assert security
    assert all("notarealvalue12345678" not in finding["message"] for finding in security)
    assert any("cbi-ignore-secret" in finding["message"] for finding in security)
