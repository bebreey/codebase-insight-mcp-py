"""Live demo: start the server over stdio with the official MCP client and call
every tool once, printing a readable summary.

    python scripts/demo.py                 # analyse this repository
    python scripts/demo.py path/to/project # analyse something else

Unlike the test suite, this is meant to be watched: it shows the real
handshake, the advertised schemas, and what each tool actually returns.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO_ROOT = Path(__file__).resolve().parent.parent

TOOL_ORDER = (
    "repo_overview",
    "find_todos",
    "search_symbols",
    "audit_dependencies",
    "assess_health",
)

RULE = "-" * 78


def heading(title: str) -> None:
    print(f"\n{RULE}\n  {title}\n{RULE}")


def structured(result: object) -> dict[str, Any]:
    """Structured content.

    The SDK's client models expose snake_case attributes (the camelCase names
    only exist on the wire), so that spelling is checked first.
    """
    for attribute in ("structured_content", "structuredContent"):
        value = getattr(result, attribute, None)
        if value:
            return value
    return {}


def summarise(tool: str, payload: dict[str, Any]) -> None:
    """Print the interesting part of each tool's structured output."""
    if tool == "repo_overview":
        totals = payload["totals"]
        print(f"  type            : {payload['project_type']}")
        print(
            f"  files / code    : {totals['text_files']} text files, {totals['code_lines']} code lines, {totals['bytes_human']}"
        )
        for row in payload["languages"][:5]:
            print(
                f"    {row['language']:<14} {row['files']:>3} files  {row['code_lines']:>6} code  {row['share_of_code']}"
            )
        if payload["build_commands"]:
            print(f"  commands        : {', '.join(payload['build_commands'][:4])}")
        print(f"  .gitignore used : {', '.join(payload['gitignore_files']) or 'none'}")

    elif tool == "find_todos":
        print(f"  markers         : {payload['total']}")
        for row in payload["items"][:5]:
            owner = f"({row['owner']})" if row["owner"] else ""
            print(f"    {row['tag']}{owner:<8} {row['file']}:{row['line']}  {row['text'][:52]}")

    elif tool == "search_symbols":
        print(
            f"  scanned / found : {payload['scanned_files']} files, {payload['matched']} declarations matched"
        )
        print(f"  ast used        : {payload['extracted_with_ast']}")
        counts = ", ".join(f"{entry['key']}={entry['count']}" for entry in payload["by_kind"])
        print(f"  by kind         : {counts}")
        for row in payload["items"][:6]:
            print(f"    {row['kind']:<9} {row['name']:<24} {row['file']}:{row['line']}")

    elif tool == "audit_dependencies":
        print(f"  manifests       : {len(payload['manifests'])}, lockfiles: {len(payload['lockfiles'])}")
        print(f"  runtime / dev   : {payload['runtime']} / {payload['dev']}")
        print(f"  floating/unpinned/url: {payload['floating']} / {payload['unpinned']} / {payload['url']}")
        for issue in payload["issues"][:5]:
            print(f"    [{issue['severity']:<6}] {issue['code']}: {issue['message'][:70]}")

    elif tool == "assess_health":
        print(f"  score           : {payload['score']}/100 ({payload['grade']})")
        print(f"  summary         : {payload['summary'][:100]}")
        for factor in payload["factors"]:
            bar = "█" * round(factor["earned"] / factor["weight"] * 10) if factor["weight"] else ""
            print(f"    {factor['label']:<22} {factor['earned']:>3}/{factor['weight']:<3} {bar}")
        for finding in payload["findings"][:4]:
            print(f"    [{finding['severity']:<6}] {finding['area']}: {finding['message'][:66]}")
        for action in payload["priority_actions"][:3]:
            print(f"    → {action[:90]}")


async def run(target: Path) -> int:
    if not target.is_dir():
        print(f"error: not a directory: {target}", file=sys.stderr)
        return 2

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "codebase_insight"],
        # Passing the parent environment wholesale keeps PATH and friends intact
        # regardless of whether the client merges or replaces `env`.
        env={**os.environ, "CBI_DEFAULT_ROOT": str(target), "CBI_DEBUG": "1"},
    )

    print(f"starting the server with the official MCP client, target = {target}")

    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as session,
    ):
        info = await session.initialize()
        server_info = info.server_info
        print(f"connected       : {server_info.name} {server_info.version}")
        print(f"protocol        : {info.protocol_version}")

        tools = await session.list_tools()
        heading(f"tools/list - {len(tools.tools)} tools advertised")
        for tool in tools.tools:
            schema = tool.input_schema
            required = schema.get("required", [])
            optional = sorted(set(schema.get("properties", {})) - set(required))
            suffix = f"  (optional: {', '.join(optional)})" if optional else ""
            print(f"  {tool.name:<20} args: {', '.join(required) or 'none'}{suffix}")
            print(f"    {tool.description.splitlines()[0][:72]}")

        for name in TOOL_ORDER:
            heading(f"tools/call - {name}")
            result = await session.call_tool(name, {})
            if result.is_error:
                print(f"  ERROR: {result.content[0].text}")
                continue
            summarise(name, structured(result))

    print(f"\n{RULE}\n  done - every tool answered over stdio\n{RULE}")
    return 0


def main() -> int:
    target = Path(sys.argv[1]).expanduser().resolve() if len(sys.argv) > 1 else REPO_ROOT
    return asyncio.run(run(target))


if __name__ == "__main__":
    raise SystemExit(main())
