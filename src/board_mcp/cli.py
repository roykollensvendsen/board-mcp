"""Command line for board-mcp: serve the tools, or read the board once as the voice hears it."""

from __future__ import annotations

import argparse
import asyncio
import functools
import sys

import httpx2

from board_mcp import settings
from board_mcp.fake import SAMPLE_TOKEN, FakeGitHub
from board_mcp.github import GitHubBoard
from board_mcp.service import BoardService

#: Every verb this command has.
COMMANDS: tuple[str, ...] = ("serve", "list")
#: Help is laid out at one width on every terminal, so a page's copy of it stays true.
HELP = functools.partial(argparse.HelpFormatter, width=100)


def _board(rules: settings.Settings, *, simulate: bool) -> GitHubBoard:
    """The made-up board behind the fake GitHub, or the real one with the key from secret-box."""
    if simulate:
        fields = (rules.status_field, rules.class_field)
        fake = FakeGitHub(kind=rules.owner_kind, owner=rules.owner, number=rules.number, fields=fields)
        return GitHubBoard(rules, lambda: SAMPLE_TOKEN, transport=httpx2.MockTransport(fake))
    return GitHubBoard(rules, lambda: settings.read_token(settings.token_path(rules)))


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="board-mcp", description=__doc__, formatter_class=HELP)
    verbs = parser.add_subparsers(dest="command", required=True)
    serve = verbs.add_parser("serve", formatter_class=HELP, help="serve the tools over stdio, for a voice session")
    listed = verbs.add_parser("list", formatter_class=HELP, help="read the board's open items, as the voice hears them")
    for verb in (serve, listed):
        verb.add_argument("--simulate", action="store_true", help="answer from the made-up board")
    args = parser.parse_args(argv)
    try:
        configured = settings.load()
    except settings.SettingsError as broken:
        sys.stderr.write(f"{broken}\n")
        return 2
    simulate = args.simulate or configured.simulate
    service = BoardService(_board(configured, simulate=simulate), configured)

    # The MCP server is a slow import, and only a working command needs it.
    from mcp.types import CallToolResult  # noqa: PLC0415

    from board_mcp.server import build_server  # noqa: PLC0415

    server = build_server(service, simulated=simulate)
    if args.command == "list":
        # Through the tool itself, so this says exactly what the voice would hear.
        result = asyncio.run(server.call_tool("board_list", {}))
        answer = result.structured_content if isinstance(result, CallToolResult) else None
        sys.stdout.write(str((answer or {}).get("say", "")) + "\n")
        return 0
    server.run("stdio")  # pragma: no cover - runs until stdin closes
    return 0  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
