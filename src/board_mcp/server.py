"""The MCP server: the board's tools, over stdio, for a voice session.

It only puts the core together and names the tools; every answer comes from the service.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

if TYPE_CHECKING:
    from board_mcp.service import BoardService

#: The Claude app shows a tool by the start of its description, cut at this many characters.
FIRST_LINE_MAX = 78
INSTRUCTIONS = (
    "The owner's work board, read aloud. Read each answer's 'say' aloud as it is. "
    "The board only mirrors the work: reading it starts, stops or changes nothing."
)
SIMULATED = "SIMULATED board, not the real one: say so. "
LIST_DESCRIPTION = (
    "What's on the work board, highest priority first?\n"
    "The open items in priority order: by class, owner requests first, then by place on the board. "
    "Each has its number, title, class and status; an item the key may not see is said as a private item. "
    "limit is how many to read out, 1 to 50. The board only mirrors the work; reading it starts nothing. "
    "It only reads; it changes nothing."
)
#: Every tool, by name. The manifest lists the same, and each has a test file of its own.
TOOLS = ("board_list",)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True)


def build_server(service: BoardService, *, simulated: bool = False) -> MCPServer[Any]:
    """The MCP server with the board's tools, answering from `service`."""
    server: MCPServer[Any] = MCPServer(
        name="board-simulated" if simulated else "board",
        instructions=(SIMULATED + INSTRUCTIONS) if simulated else INSTRUCTIONS,
    )

    def marked(answer: dict[str, Any]) -> dict[str, Any]:
        answer["simulated"] = simulated
        if simulated:
            answer["say"] = "Simulated: " + answer["say"]
        return answer

    @server.tool(annotations=READ_ONLY, description=LIST_DESCRIPTION)
    async def board_list(limit: int = 10) -> dict[str, Any]:
        return marked(await service.open_items(limit))

    return server
