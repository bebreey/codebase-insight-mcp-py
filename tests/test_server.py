"""Tool layer, driven in-process.

The value here over the protocol test is speed and debuggability: every tool's
parameters and error paths can be exercised without a subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from codebase_insight.server import create_server

pytestmark = pytest.mark.asyncio

TOOL_NAMES = {"repo_overview", "find_todos", "search_symbols", "audit_dependencies", "assess_health"}


@pytest.fixture(scope="module")
def server() -> MCPServer:
    return create_server()


async def test_catalogue_exposes_every_tool(server: MCPServer) -> None:
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == TOOL_NAMES
    for tool in tools:
        assert tool.description, f"{tool.name} has no description"
        assert tool.input_schema is not None
        assert tool.output_schema is not None
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False


async def test_repo_overview(server: MCPServer, fixture_repo: Path) -> None:
    result = await server.call_tool("repo_overview", {"path": str(fixture_repo)})
    data = result.structured_content

    assert result.is_error is False
    assert data["ecosystem"] == "Python"
    assert data["primary_language"] == "Python"
    assert data["totals"]["code_lines"] > 40
    assert {row["language"] for row in data["languages"]} >= {"Python", "Markdown"}
    assert data["entry_points"] == []
    assert "pytest" in " ".join(data["build_commands"])
    assert data["gitignore_files"] == [".gitignore"]


async def test_find_todos(server: MCPServer, fixture_repo: Path) -> None:
    result = await server.call_tool("find_todos", {"path": str(fixture_repo)})
    data = result.structured_content

    assert data["total"] == 5
    assert {row["tag"] for row in data["items"]} == {"TODO", "FIXME", "HACK"}
    assert any(row["owner"] == "alice" for row in data["items"])

    custom = await server.call_tool("find_todos", {"path": str(fixture_repo), "tags": ["NOTE"]})
    assert custom.structured_content["total"] == 0


async def test_search_symbols_uses_the_ast_for_python(server: MCPServer, fixture_repo: Path) -> None:
    result = await server.call_tool(
        "search_symbols", {"path": str(fixture_repo), "query": "Calculator", "languages": ["Python"]}
    )
    data = result.structured_content

    assert data["extracted_with_ast"] is True
    assert data["matched"] == 1
    assert data["items"][0]["kind"] == "class"
    assert data["items"][0]["file"] == "src/sample/calculator.py"


async def test_search_symbols_kind_filter_and_regex(server: MCPServer, fixture_repo: Path) -> None:
    by_kind = await server.call_tool("search_symbols", {"path": str(fixture_repo), "kinds": ["method"]})
    kinds = {row["kind"] for row in by_kind.structured_content["items"]}
    assert kinds == {"method"}

    regex = await server.call_tool(
        "search_symbols", {"path": str(fixture_repo), "query": "^(add|describe)$", "mode": "regex"}
    )
    assert {row["name"] for row in regex.structured_content["items"]} == {"add", "describe"}


async def test_search_symbols_rejects_an_invalid_regex(server: MCPServer, fixture_repo: Path) -> None:
    with pytest.raises(ToolError, match="Invalid regular expression"):
        await server.call_tool(
            "search_symbols", {"path": str(fixture_repo), "query": "([unclosed", "mode": "regex"}
        )


async def test_audit_dependencies(server: MCPServer, fixture_repo: Path) -> None:
    result = await server.call_tool("audit_dependencies", {"path": str(fixture_repo)})
    data = result.structured_content

    assert [manifest["file"] for manifest in data["manifests"]] == ["pyproject.toml"]
    assert data["floating"] == 1
    assert {issue["code"] for issue in data["issues"]} >= {"missing-lockfile", "floating-dependency"}


async def test_assess_health(server: MCPServer, fixture_repo: Path) -> None:
    result = await server.call_tool("assess_health", {"path": str(fixture_repo)})
    data = result.structured_content

    assert 0 < data["score"] <= 100
    assert data["grade"] in {"A+", "A", "B", "C", "D", "F"}
    assert len(data["factors"]) == 9
    assert data["stats"]["test_files"] == 1
    assert data["stats"]["secret_count"] == 1
    assert data["stats"]["todo_count"] == 5
    assert any(finding["area"] == "dependencies" for finding in data["findings"])


async def test_text_content_accompanies_structured_content(server: MCPServer, fixture_repo: Path) -> None:
    """Every result carries both channels; the SDK derives the text from the model."""
    result = await server.call_tool("repo_overview", {"path": str(fixture_repo)})
    assert result.content, "no content blocks were returned"
    assert result.structured_content
    assert '"code_lines"' in result.content[0].text


async def test_missing_directory_raises_a_message_preserving_error(server: MCPServer) -> None:
    with pytest.raises(ToolError, match="does not exist or is not readable"):
        await server.call_tool("repo_overview", {"path": "D:/definitely/not/here"})


async def test_a_file_is_not_a_valid_target(server: MCPServer, fixture_repo: Path) -> None:
    with pytest.raises(ToolError, match="not a directory"):
        await server.call_tool("repo_overview", {"path": str(fixture_repo / "pyproject.toml")})


async def test_cbi_roots_is_enforced(
    server: MCPServer, fixture_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CBI_ROOTS", str(fixture_repo))

    allowed = await server.call_tool("repo_overview", {"path": str(fixture_repo)})
    assert allowed.is_error is False

    with pytest.raises(ToolError, match=r"CBI_ROOTS"):
        await server.call_tool("repo_overview", {"path": str(fixture_repo.parent)})
