"""A made-up GitHub that refuses what the real one refuses.

A fake that says yes to everything lets a test pass that GitHub would fail. So this one keeps
GitHub's limits, as its docs give them and its schema showed them on 21.11: a wrong key gets 401
"Bad credentials"; a key with no project right gets INSUFFICIENT_SCOPES; at most 100 items a
page; another owner's board, or a user's board asked for as an organization's, is NOT_FOUND;
past the rate limit, 403 with the time the limit resets; and an item the key may not see is
typed REDACTED, with no content. It answers httpx2's mock transport, so the real adapter runs
in every test. Write each new limit of GitHub in here first, with a test, before the code that
copes with it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx2

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: GitHub's own limit on items a page.
PAGE_MOST = 100
#: The made-up key the fake takes. It is not a real token's shape, so no scanner mistakes it.
SAMPLE_TOKEN = "made-up-key-for-the-fake"  # noqa: S105 - made up, and only the fake takes it
#: The project rights a classic token may carry that let it read a board.
READS = ("read:project", "project")
#: How long the fake's rate limit lasts once it is spent.
RESET_SECONDS = 60


@dataclass(frozen=True)
class FakeItem:
    """One item on the fake board, in the fake's own order."""

    title: str
    status: str | None = None
    klass: str | None = None
    kind: str = "ISSUE"
    archived: bool = False
    #: Seconds since its status last changed, by the fake's clock; None leaves GitHub's time out.
    waited: float | None = None


#: The made-up board practice mode reads.
SAMPLE = (
    FakeItem("Read the board aloud", "In progress", "Owner request", waited=40 * 60),
    FakeItem("Tidy the shed", "Todo", "Idea", waited=3 * 86400),
    FakeItem("Fix the gate", "Todo", "Bug", waited=6 * 3600),
    FakeItem("Paint the fence", "Done", "Owner request", waited=86400),
    FakeItem("A plan in a private repo", "Todo", "Idea", kind="REDACTED", waited=2 * 3600),
)


class FakeGitHub:
    """GitHub's GraphQL endpoint in memory, holding one board."""

    def __init__(  # noqa: PLR0913 - each is a way the real GitHub can differ
        self,
        items: Sequence[FakeItem] = SAMPLE,
        *,
        token: str = SAMPLE_TOKEN,
        kind: str = "user",
        owner: str = "example-owner",
        number: int = 1,
        scopes: Sequence[str] = ("read:project",),
        fields: tuple[str, str] = ("Status", "Class"),
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Hold `items` on board `number` of `owner`, readable with `token`; `fields` names status and class."""
        self.items = list(items)
        self.fields = fields
        self.token = token
        self.kind = kind
        self.owner = owner
        self.number = number
        self.scopes = tuple(scopes)
        self.unreachable = False
        self.requests_left = 5000
        self.asked = 0
        self._clock = clock

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Answer one request as GitHub would."""
        self.asked += 1
        if self.unreachable:
            msg = "the fake GitHub is off the network"
            raise httpx2.ConnectError(msg, request=request)
        # RULE: the fake refuses a request without the right token
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx2.Response(401, json={"message": "Bad credentials"})
        if self.requests_left <= 0:
            reset = str(int(self._clock()) + RESET_SECONDS)
            limited = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset}
            return httpx2.Response(403, headers=limited, json={"message": "API rate limit exceeded"})
        self.requests_left -= 1
        asked = json.loads(request.content)
        return httpx2.Response(200, json=self._answer(asked["query"], asked["variables"]))

    def _answer(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not set(READS) & set(self.scopes):
            return _error("INSUFFICIENT_SCOPES", "Your token has not been granted the required scopes.")
        first = variables["first"]
        # RULE: the fake gives at most a hundred items a page
        if first > PAGE_MOST:
            said = f"Requesting {first} records on the `items` connection exceeds the `first` limit of 100 records."
            return {"data": None, "errors": [{"message": said}]}
        asked_kind = re.search(r"owner:\s*(\w+)\(", query)
        mine = asked_kind is not None and asked_kind.group(1) == self.kind
        if not (mine and variables["login"] == self.owner and variables["number"] == self.number):
            return {**_error("NOT_FOUND", "Could not resolve to a ProjectV2."), "data": {"owner": None}}
        start = int(variables.get("after") or 0)
        page = self.items[start : start + first]
        end = start + len(page)
        nodes = [self._node(start + n, item, variables) for n, item in enumerate(page)]
        info = {"hasNextPage": end < len(self.items), "endCursor": str(end)}
        return {"data": {"owner": {"projectV2": {"items": {"pageInfo": info, "nodes": nodes}}}}}

    def _node(self, n: int, item: FakeItem, variables: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"PVTI_fake{n}",
            "type": item.kind,
            "isArchived": item.archived,
            "content": None if item.kind == "REDACTED" else {"title": item.title},
            "status": _value(item.status, variables["status"] == self.fields[0], self._updated(item)),
            "class": _value(item.klass, variables["class"] == self.fields[1], None),
        }

    def _updated(self, item: FakeItem) -> str | None:
        """When the status last changed, as GitHub writes a DateTime: ISO 8601 in UTC with a Z."""
        if item.waited is None:
            return None
        when = dt.datetime.fromtimestamp(self._clock() - item.waited, tz=dt.UTC)
        return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _value(name: str | None, field_exists: bool, updated: str | None) -> dict[str, str] | None:  # noqa: FBT001
    """A single-select value, or None when the item has none or the field is not on the board."""
    if not (name and field_exists):
        return None
    return {"name": name} | ({"updatedAt": updated} if updated else {})


def _error(kind: str, message: str) -> dict[str, Any]:
    return {"data": None, "errors": [{"type": kind, "message": message}]}
