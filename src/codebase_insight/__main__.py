"""Entry point.

``stdout`` carries JSON-RPC frames, so the CLI flags below are the only place
that writes to stdout, and they all return before the transport starts.
"""

from __future__ import annotations

import asyncio
import sys

from . import SERVER_NAME, SERVER_VERSION
from .server import create_server


def _stdout(text: str) -> None:
    sys.stdout.write(text if text.endswith("\n") else f"{text}\n")


def _print_help() -> None:
    _stdout(
        "\n".join(
            [
                f"{SERVER_NAME} {SERVER_VERSION}",
                "",
                "An MCP server that gives AI agents offline insight into a local codebase.",
                "",
                "USAGE",
                "  codebase-insight-mcp-py              run as a stdio MCP server",
                "  codebase-insight-mcp-py --list-tools print the tool catalogue and exit",
                "  codebase-insight-mcp-py --version    print the version and exit",
                "  codebase-insight-mcp-py --help       print this message and exit",
                "",
                "ENVIRONMENT",
                "  CBI_DEFAULT_ROOT     directory used when a tool call omits `path` (default: cwd)",
                "  CBI_ROOTS            allow-list of roots, separated by , or ;  (default: unrestricted)",
                "  CBI_MAX_FILES        walk file ceiling (default 20000)",
                "  CBI_MAX_DEPTH        directory recursion limit (default 12)",
                "  CBI_MAX_FILE_BYTES   text file size ceiling in bytes (default 2097152)",
                "  CBI_DEBUG=1          verbose diagnostics on stderr",
                "",
                "CLIENT CONFIGURATION",
                "  {",
                '    "mcpServers": {',
                '      "codebase-insight-py": {',
                '        "command": "codebase-insight-mcp-py"',
                "      }",
                "    }",
                "  }",
            ]
        )
    )


def _print_tools() -> None:
    server = create_server()
    # `list_tools` is a coroutine despite the sync-looking type stub.
    tools = asyncio.run(server.list_tools())
    lines = [f"{SERVER_NAME} exposes {len(tools)} tools:", ""]
    for tool in tools:
        lines.append(f"  {tool.name}")
        if tool.description:
            lines.append(f"    {tool.description.splitlines()[0]}")
        lines.append("")
    _stdout("\n".join(lines))


def main() -> None:
    """CLI entry point."""
    argv = sys.argv[1:]

    if "--help" in argv or "-h" in argv:
        _print_help()
        return
    if "--version" in argv or "-v" in argv:
        _stdout(f"{SERVER_NAME} {SERVER_VERSION}")
        return
    if "--list-tools" in argv:
        _print_tools()
        return

    create_server().run(transport="stdio")


if __name__ == "__main__":
    main()
