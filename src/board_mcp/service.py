"""The core: read the board, and word every answer for the voice.

It knows no MCP. Every answer is a dict with `success`, an `outcome` and a `say`, the
sentence the voice reads aloud as it is, and it has one even when GitHub fails. The board only
mirrors the work: reading it starts, stops or changes nothing.
"""

from __future__ import annotations

import math
import time
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
    from collections.abc import Callable

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

    def __init__(self, board: Board, rules: Settings, clock: Callable[[], float] = time.time) -> None:
        """Answer from `board`, ordered and filtered by `rules`; `clock` is now, for a wait."""
        self._board = board
        self._rules = rules
        self._clock = clock

    async def open_items(self, limit: int = 10) -> dict[str, Any]:
        """The open items, highest priority first, as a sentence the voice reads."""
        if not 1 <= limit <= MOST:
            return _failed("bad_limit", f"Say how many items, from 1 to {MOST}.")
        items = await self._read()
        if isinstance(items, dict):
            return items
        return _listed(self._ordered(items), limit, self._clock(), self._spoken)

    async def counts(self, *, include_done: bool = False) -> dict[str, Any]:
        """How many items each column holds, the fullest first, as a sentence the voice reads."""
        items = await self._read()
        if isinstance(items, dict):
            return items
        columns, loose = self._columns(items, include_done=include_done)
        return _counted(columns, loose, self._spoken, include_done=include_done)

    def _spoken(self, status: str) -> str:
        """A column's name as the voice says it: the board's own, or "you" for the owner's."""
        mine = _folded(self._rules.waiting_column)
        # RULE: an empty waiting column names no column
        if not mine:
            return status.lower()
        # RULE: the waiting column matches whatever its case
        ours = _folded(status) == mine
        # RULE: the column the config names is said as waiting on you
        return "waiting on you" if ours else status.lower()

    async def _read(self) -> list[Item] | dict[str, Any]:
        """Every item on the board, or the failed answer that says why not."""
        try:
            return await self._board.items()
        except SlowDownError as slow:
            seconds = max(1, math.ceil(slow.seconds))
            return _failed("slow_down", f"GitHub asks for a pause; ask again in {seconds} seconds.")
        except DeviceError as failed:
            return _failed(*FAILURES.get(type(failed), ("broke", BROKE)))
        # RULE: every answer has a sentence to say even when github fails
        except Exception:  # noqa: BLE001 - whatever broke, the voice gets a sentence
            return _failed("broke", BROKE)

    def _ordered(self, items: list[Item]) -> list[Item]:
        rank = {name: n for n, name in enumerate(self._rules.class_order)}
        # RULE: done items are left out
        shown = [item for item in items if item.status not in self._rules.done]
        # RULE: the board is read in class order then position
        return sorted(shown, key=lambda item: (rank.get(item.klass or "", len(rank)), item.position))

    def _columns(self, items: list[Item], *, include_done: bool) -> tuple[list[tuple[str, int]], int]:
        """Each column the items are in, as the board names it, with how many: the fullest first.

        Also how many open items are in no column, which board_list counts as open too.
        """
        counts: dict[str, int] = {}
        loose = 0
        for item in sorted(items, key=lambda item: item.position):
            # RULE: an item with no status is left out of the counts
            if item.status is None:
                loose += 1
                continue
            # RULE: done columns are counted only when asked
            if item.status in self._rules.done and not include_done:
                continue
            counts[item.status] = counts.get(item.status, 0) + 1
        # A stable sort: equal counts keep the order their first items have on the board.
        return sorted(counts.items(), key=lambda column: -column[1]), loose


def _counted(
    columns: list[tuple[str, int]], loose: int, spoken: Callable[[str], str], *, include_done: bool
) -> dict[str, Any]:
    total = sum(count for _, count in columns) + loose
    kind = "" if include_done else "open "
    said = [f"{count} {spoken(status)}" for status, count in columns]
    head = f"The board has {_plural(total, kind + 'item')}: {_joined(said, loose)}."
    return {
        "success": True,
        "outcome": "counted",
        "total": total,
        "in_no_column": loose,
        "counts": [{"status": status, "count": count} for status, count in columns],
        "say": head if total else f"The board has no {kind}items.",
    }


def _folded(name: str) -> str:
    """A column name as compared: no capitals, no spaces at the ends."""
    return name.strip().casefold()


def _joined(said: list[str], loose: int) -> str:
    """The columns' counts, with the items in no column last."""
    if not loose:
        return ", ".join(said)
    tail = f"{loose} in no column"
    return ", ".join([*said, f"and {tail}"]) if said else tail


def _listed(items: list[Item], limit: int, now: float, spoken: Callable[[str], str]) -> dict[str, Any]:
    count = len(items)
    read = items[:limit]
    said = [_said(n, item, now, spoken) for n, item in enumerate(read, 1)]
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
            {
                "number": n,
                "title": item.title,
                "class": item.klass,
                "status": item.status,
                "waited_minutes": _minutes_in_column(item, now),
            }
            for n, item in enumerate(read, 1)
        ],
        "say": " ".join([head, *said, *more]),
    }


def _said(number: int, item: Item, now: float, spoken: Callable[[str], str]) -> str:
    # RULE: a private item is said without its title
    name = PRIVATE if item.title is None else item.title
    words = [name, *(word for word in (item.klass and item.klass.lower(), _in_column(item, now, spoken)) if word)]
    return f"{number}: {', '.join(words)}."


def _minutes_in_column(item: Item, now: float) -> int | None:
    return None if item.since is None else max(0, int((now - item.since) // 60))


def _in_column(item: Item, now: float, spoken: Callable[[str], str]) -> str | None:
    """The item's column, and how long it has been there when GitHub says."""
    if not item.status:
        return None
    if item.since is None:
        return spoken(item.status)
    return f"{spoken(item.status)} for {_waited(now - item.since)}"


def _waited(seconds: float) -> str:
    """A time in a column, as the voice says it."""
    minutes = int(seconds // 60)
    if minutes < 1:
        return "under a minute"
    # RULE: a wait under an hour is said in minutes
    if minutes < 60:  # noqa: PLR2004 - an hour
        return _plural(minutes, "minute")
    hours = minutes // 60
    # RULE: a wait under two days is said in hours
    if hours < 48:  # noqa: PLR2004 - two days
        return _plural(hours, "hour")
    return _plural(hours // 24, "day")


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _failed(outcome: str, say: str) -> dict[str, Any]:
    return {"success": False, "outcome": outcome, "say": say}
