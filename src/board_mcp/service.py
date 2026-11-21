"""The core: read the board, and word every answer for the voice.

It knows no MCP. Every answer is a dict with `success`, an `outcome` and a `say`, the
sentence the voice reads aloud as it is, and it has one even when GitHub fails. The board only
mirrors the work: reading it starts, stops or changes nothing.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

from board_mcp.device import (
    DeviceError,
    KeyRefusedError,
    NoRightError,
    NotFoundError,
    NotSetUpError,
    SlowDownError,
    UnreachableError,
)

if TYPE_CHECKING:
    from board_mcp.device import Board, Item
    from board_mcp.settings import Settings

#: The most items one answer reads out.
MOST = 50
PRIVATE = "a private item"
UNREACHABLE = "GitHub isn't answering. Try again in a minute."
NOT_SET_UP = (
    "No GitHub key is set up for the board yet. Make a classic token with only the read:project right "
    "and an expiry, and enter it with secret-box into board-mcp's config folder."
)
KEY_REFUSED = "GitHub refused the board key. It may have run out; make a new one and enter it with secret-box."
NO_RIGHT = "The board key lacks the read:project right. Make a new one with that right, and enter it with secret-box."
NOT_FOUND = "GitHub has no such board, or the key can't see it. Check the owner and number in board-mcp's config."
BROKE = "That went wrong inside board-mcp. Try again, and if it fails again, check its log."
#: How each failure is said: its outcome, and its sentence.
FAILURES: dict[type[DeviceError], tuple[str, str]] = {
    UnreachableError: ("unreachable", UNREACHABLE),
    NotSetUpError: ("not_set_up", NOT_SET_UP),
    KeyRefusedError: ("key_refused", KEY_REFUSED),
    NoRightError: ("no_right", NO_RIGHT),
    NotFoundError: ("not_found", NOT_FOUND),
}


class BoardService:
    """What the tools ask, answered from one board and its rules."""

    def __init__(self, board: Board, rules: Settings) -> None:
        """Answer from `board`, ordered and filtered by `rules`."""
        self._board = board
        self._rules = rules

    async def open_items(self, limit: int = 10) -> dict[str, Any]:
        """The open items, highest priority first, as a sentence the voice reads."""
        if not 1 <= limit <= MOST:
            return _failed("bad_limit", f"Say how many items, from 1 to {MOST}.")
        try:
            items = await self._board.items()
        except SlowDownError as slow:
            seconds = max(1, math.ceil(slow.seconds))
            return _failed("slow_down", f"GitHub asks for a pause; ask again in {seconds} seconds.")
        except DeviceError as failed:
            return _failed(*FAILURES.get(type(failed), ("broke", BROKE)))
        # RULE: every answer has a sentence to say even when github fails
        except Exception:  # noqa: BLE001 - whatever broke, the voice gets a sentence
            return _failed("broke", BROKE)
        return _listed(self._ordered(items), limit)

    def _ordered(self, items: list[Item]) -> list[Item]:
        rank = {name: n for n, name in enumerate(self._rules.class_order)}
        # RULE: done items are left out
        shown = [item for item in items if item.status not in self._rules.done]
        # RULE: the board is read in class order then position
        return sorted(shown, key=lambda item: (rank.get(item.klass or "", len(rank)), item.position))


def _listed(items: list[Item], limit: int) -> dict[str, Any]:
    count = len(items)
    read = items[:limit]
    said = [_said(n, item) for n, item in enumerate(read, 1)]
    head = f"The board has {count} open {'item' if count == 1 else 'items'}."
    if not count:
        head = "The board has no open items."
    # RULE: the list stops at the limit and says how many more
    more = [f"And {count - limit} more."] if count > limit else []
    return {
        "success": True,
        "outcome": "listed",
        "count": count,
        "items": [
            {"number": n, "title": item.title, "class": item.klass, "status": item.status}
            for n, item in enumerate(read, 1)
        ],
        "say": " ".join([head, *said, *more]),
    }


def _said(number: int, item: Item) -> str:
    # RULE: a private item is said without its title
    name = PRIVATE if item.title is None else item.title
    words = [name, *(word.lower() for word in (item.klass, item.status) if word)]
    return f"{number}: {', '.join(words)}."


def _failed(outcome: str, say: str) -> dict[str, Any]:
    return {"success": False, "outcome": outcome, "say": say}
