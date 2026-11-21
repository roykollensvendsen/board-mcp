"""The real board: a GitHub project, read through GitHub's GraphQL API with the owner's key.

It only reads. It asks for each item's title, its type, whether it is archived, and the two
single-select fields the config names (status and class), a hundred items a page in the board's
own order. An item the key may not see comes back typed REDACTED, with no content, and is kept
with no title. No title or key is ever logged.
"""

from __future__ import annotations

import math
import time
from typing import TYPE_CHECKING, Any

import httpx2

from board_mcp.device import (
    DeviceError,
    Item,
    KeyRefusedError,
    NoRightError,
    NotFoundError,
    SlowDownError,
    UnreachableError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from board_mcp.settings import Settings

API = "https://api.github.com/graphql"
#: GitHub gives at most this many items a page.
PAGE = 100
#: A board bigger than this many pages is read only this far.
MOST_PAGES = 10
TIMEOUT = 10.0
AGENT = "board-mcp/0.1"
#: The owner field is filled in from the config's owner_kind, which is only ever user or organization.
QUERY = """
query Board($login: String!, $number: Int!, $first: Int!, $after: String, $status: String!, $class: String!) {
  owner: __OWNER__(login: $login) {
    projectV2(number: $number) {
      items(first: $first, after: $after, orderBy: {field: POSITION, direction: ASC}) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          type
          isArchived
          content { ... on Issue { title } ... on PullRequest { title } ... on DraftIssue { title } }
          status: fieldValueByName(name: $status) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          class: fieldValueByName(name: $class) { ... on ProjectV2ItemFieldSingleSelectValue { name } }
        }
      }
    }
  }
}
"""


def query(owner_kind: str) -> str:
    """The query for a board owned by a user or an organization."""
    return QUERY.replace("__OWNER__", owner_kind)


class GitHubBoard:
    """One GitHub project, read with the key `token` gives."""

    def __init__(
        self,
        rules: Settings,
        token: Callable[[], str],
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Read the board `rules` names; `transport` is the fake GitHub in tests."""
        self._rules = rules
        self._token = token
        self._transport = transport
        self._clock = clock

    async def items(self) -> list[Item]:
        """Every item on the board, archived ones left out, in the board's own order."""
        token = self._token()
        headers = {"Authorization": f"Bearer {token}", "User-Agent": AGENT}
        items: list[Item] = []
        after, seen = None, 0
        async with httpx2.AsyncClient(transport=self._transport, timeout=TIMEOUT, headers=headers) as client:
            for _ in range(MOST_PAGES):
                page = await self._page(client, after)
                items += [item for n, node in enumerate(page["nodes"], seen) if (item := _item(node, n))]
                seen += len(page["nodes"])
                # RULE: every page of the board is read
                if not page["pageInfo"]["hasNextPage"]:
                    break
                after = page["pageInfo"]["endCursor"]
        return items

    async def _page(self, client: httpx2.AsyncClient, after: str | None) -> dict[str, Any]:
        rules = self._rules
        variables = {
            "login": rules.owner,
            "number": rules.number,
            "first": PAGE,
            "after": after,
            "status": rules.status_field,
            "class": rules.class_field,
        }
        try:
            response = await client.post(API, json={"query": query(rules.owner_kind), "variables": variables})
        except httpx2.HTTPError as lost:
            msg = "GitHub did not answer"
            raise UnreachableError(msg) from lost
        _check(response, self._clock())
        items: dict[str, Any] = _project(response.json())["items"]
        return items


def _check(response: httpx2.Response, now: float) -> None:
    if response.status_code == 401:  # noqa: PLR2004 - HTTP's own number
        msg = "GitHub refused the key"
        raise KeyRefusedError(msg)
    headers = response.headers
    if "retry-after" in headers or headers.get("x-ratelimit-remaining") == "0":
        raise SlowDownError(_wait(headers, now))
    if response.is_error:
        msg = f"GitHub answered {response.status_code}"
        raise UnreachableError(msg)


def _wait(headers: httpx2.Headers, now: float) -> float:
    """Seconds until GitHub takes requests again: its retry-after, or its limit's reset time."""
    if "retry-after" in headers:
        return float(headers["retry-after"])
    return max(1.0, math.ceil(float(headers.get("x-ratelimit-reset", now + 60)) - now))


def _project(body: dict[str, Any]) -> dict[str, Any]:
    kinds = {error.get("type") for error in body.get("errors") or []}
    if "INSUFFICIENT_SCOPES" in kinds:
        msg = "the key lacks the read:project right"
        raise NoRightError(msg)
    project = ((body.get("data") or {}).get("owner") or {}).get("projectV2")
    if project is None and (not kinds or "NOT_FOUND" in kinds):
        msg = "GitHub has no such board, or the key cannot see it"
        raise NotFoundError(msg)
    if project is None:
        msg = f"GitHub answered with errors: {', '.join(sorted(str(kind) for kind in kinds))}"
        raise DeviceError(msg)
    return dict(project)


def _item(node: dict[str, Any], position: int) -> Item | None:
    # RULE: archived items are left out
    if node["isArchived"]:
        return None
    content = node.get("content") or {}
    title = None if node["type"] == "REDACTED" else content.get("title")
    return Item(title=title, status=_name(node.get("status")), klass=_name(node.get("class")), position=position)


def _name(value: dict[str, Any] | None) -> str | None:
    return None if value is None else value.get("name")
