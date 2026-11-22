"""What the plugin needs from a board, and the ways asking for one can fail.

The service talks to this and nothing else. The GitHub adapter (`github.py`) answers it, and in
tests it talks to the fake GitHub (`fake.py`), so every test runs through the same door the real
board does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DeviceError(Exception):
    """Asking for the board failed; each kind below is said to the voice in its own words."""


class UnreachableError(DeviceError):
    """GitHub did not answer in time, or answered with a fault of its own."""


class SlowDownError(DeviceError):
    """GitHub asks for a pause before the next request."""

    def __init__(self, seconds: float) -> None:
        """Keep how long to wait, so the voice can say it."""
        super().__init__(f"ask again in {seconds:.0f} s")
        self.seconds = seconds


class NotSetUpError(DeviceError):
    """No key for GitHub is set up, so nothing was asked."""


class KeyRefusedError(DeviceError):
    """GitHub refused the key: it is wrong, revoked or out of date."""


class NoRightError(DeviceError):
    """The key lacks the right to read projects."""


class NotFoundError(DeviceError):
    """GitHub has no such board, or the key cannot see it."""


@dataclass(frozen=True)
class Item:
    """One item on the board, as read.

    `title` is None for an item the key may not see. `position` is its place on the board,
    counted from 0 in GitHub's own order. `since` is when its status last changed, in seconds
    since 1970, as GitHub keeps it; None when it has no status.
    """

    title: str | None
    status: str | None
    klass: str | None
    position: int
    since: float | None = None


class Board(Protocol):
    """A board the plugin can read."""

    async def items(self) -> list[Item]:
        """Every item on the board now, in its own order, archived ones left out."""
        ...
