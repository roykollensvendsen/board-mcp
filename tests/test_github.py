"""The adapter asks GitHub only for what its schema has, as read live on 21.11 (github_schema.json)."""

import asyncio
import json
import pathlib

import httpx2
import pytest

from board_mcp.device import DeviceError, SlowDownError, UnreachableError
from board_mcp.fake import SAMPLE_TOKEN, FakeGitHub, FakeItem
from board_mcp.github import MOST_PAGES, PAGE, GitHubBoard, query
from board_mcp.settings import Settings

SCHEMA = json.loads((pathlib.Path(__file__).parent / "github_schema.json").read_text(encoding="utf-8"))
#: Every item field, items argument and enum value the query names, with where the schema lists it.
USED = {
    "ProjectV2Item": ["id", "type", "isArchived", "content", "fieldValueByName"],
    "ProjectV2.items": ["first", "after", "orderBy"],
    "ProjectV2ItemConnection": ["nodes", "pageInfo"],
    "ProjectV2ItemFieldSingleSelectValue": ["name", "updatedAt"],
    "ProjectV2ItemOrderField": ["POSITION"],
    "ProjectV2ItemOrder": ["field", "direction"],
    "OrderDirection": ["ASC"],
}


def test_the_query_names_only_what_githubs_schema_has():
    for where, names in USED.items():
        for name in names:
            assert name in SCHEMA[where], f"{where}.{name} is not in GitHub's schema"
            assert name in query("user"), f"{name} is listed as used but the query does not name it"


def test_a_private_item_is_one_github_types_as_redacted():
    assert "REDACTED" in SCHEMA["ProjectV2ItemType"]


def test_a_page_asks_for_no_more_than_github_gives():
    assert PAGE == 100


def _read(handler):
    board = GitHubBoard(Settings(), lambda: "made-up", transport=httpx2.MockTransport(handler), clock=lambda: 1000.0)
    return asyncio.run(board.items())


def test_a_fault_on_githubs_side_counts_as_not_answering():
    with pytest.raises(UnreachableError, match="502"):
        _read(lambda _request: httpx2.Response(502, text="Bad gateway"))


def test_a_secondary_rate_limit_waits_as_long_as_github_says():
    with pytest.raises(SlowDownError) as slow:
        _read(lambda _request: httpx2.Response(403, headers={"retry-after": "30"}, json={"message": "slow down"}))
    assert slow.value.seconds == 30.0


def test_an_error_github_gives_no_type_for_is_named_and_fails():
    def answer(_request):
        return httpx2.Response(200, json={"data": None, "errors": [{"type": "SOMETHING_NEW", "message": "x"}]})

    with pytest.raises(DeviceError, match="SOMETHING_NEW"):
        _read(answer)


def test_it_only_reads():
    """Every request GitHub gets is a query; a change to the board would need a mutation."""
    github = FakeGitHub([FakeItem(f"Job {n}", "Todo") for n in range(PAGE + 1)])
    sent = []

    def watched(request):
        sent.append(json.loads(request.content)["query"])
        return github(request)

    board = GitHubBoard(Settings(), lambda: SAMPLE_TOKEN, transport=httpx2.MockTransport(watched))
    asyncio.run(board.items())
    assert len(sent) == 2
    for text in sent:
        assert text.lstrip().startswith("query "), text[:40]
        assert "mutation" not in text


def test_the_status_time_is_read_as_github_writes_it():
    """GitHub's DateTime is ISO 8601 in UTC with a Z; the item keeps it as seconds since 1970."""
    node = {
        "id": "PVTI_x",
        "type": "ISSUE",
        "isArchived": False,
        "content": {"title": "Hall lights"},
        "status": {"name": "Waiting for review", "updatedAt": "2026-11-22T06:00:00Z"},
        "class": None,
    }
    page = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node]}
    body = {"data": {"owner": {"projectV2": {"items": page}}}}
    [item] = _read(lambda _request: httpx2.Response(200, json=body))
    assert item.since == 1795327200.0


def test_a_board_past_the_page_cap_is_read_only_that_far():
    """A runaway cursor never loops for ever: ten pages, then the items read so far."""
    github = FakeGitHub([FakeItem(f"Job {n}", "Todo") for n in range(PAGE * MOST_PAGES + 5)])
    items = asyncio.run(GitHubBoard(Settings(), lambda: SAMPLE_TOKEN, transport=httpx2.MockTransport(github)).items())
    assert (len(items), github.asked) == (PAGE * MOST_PAGES, MOST_PAGES)
