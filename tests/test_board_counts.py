"""board_counts, end to end: through the MCP server, the service, the GitHub adapter and the fake.

The column names come from the board itself, as each item's Status value; none is written here
in the code, so a renamed or new column is counted as it is.
"""

import asyncio

import httpx2

from board_mcp.fake import SAMPLE_TOKEN, FakeGitHub, FakeItem
from board_mcp.github import GitHubBoard
from board_mcp.server import build_server
from board_mcp.service import KEY_REFUSED, BoardService
from board_mcp.settings import Settings

RULES = Settings()
BOARD = [
    FakeItem("Hall lights", "Waiting for review", "Owner request"),
    FakeItem("Fix the gate", "In progress", "Bug"),
    FakeItem("Tidy the shed", "Waiting for review", "Idea"),
    FakeItem("Paint the fence", "Done", "Owner request"),
    FakeItem("Sign the form", "Waiting on the owner"),
    FakeItem("Loose end"),
    FakeItem("Mow the lawn", "Waiting for review", "Idea"),
    FakeItem("Old plan", "Done", "Idea"),
]


def _call(github, *, token=SAMPLE_TOKEN, simulated=False, **asked):
    board = GitHubBoard(RULES, lambda: token, transport=httpx2.MockTransport(github))
    server = build_server(BoardService(board, RULES), simulated=simulated)
    return asyncio.run(server.call_tool("board_counts", asked)).structured_content


def test_done_columns_are_counted_only_when_asked():
    assert "done" not in _call(FakeGitHub(BOARD))["say"]
    asked = _call(FakeGitHub(BOARD), include_done=True)
    assert asked["say"] == (
        "The board has 8 items: 3 waiting for review, 2 done, 1 in progress, 1 waiting on the owner, "
        "and 1 in no column."
    )
    assert {"status": "Done", "count": 2} in asked["counts"]


def test_an_item_with_no_status_is_left_out_of_the_counts():
    """It is in no column, so no column counts it; it is still open, as board_list says."""
    answer = _call(FakeGitHub(BOARD))
    assert answer["say"] == (
        "The board has 6 open items: 3 waiting for review, 1 in progress, 1 waiting on the owner, and 1 in no column."
    )
    assert (answer["total"], answer["in_no_column"]) == (6, 1)
    assert answer["counts"] == [
        {"status": "Waiting for review", "count": 3},
        {"status": "In progress", "count": 1},
        {"status": "Waiting on the owner", "count": 1},
    ]


def test_the_total_is_the_one_board_list_gives():
    github = FakeGitHub(BOARD)
    listed = asyncio.run(
        build_server(
            BoardService(GitHubBoard(RULES, lambda: SAMPLE_TOKEN, transport=httpx2.MockTransport(github)), RULES)
        ).call_tool("board_list", {})
    ).structured_content
    assert _call(github)["total"] == listed["count"]


def test_a_board_with_items_in_no_column_only_says_so():
    answer = _call(FakeGitHub([FakeItem("Loose end")]))
    assert answer["say"] == "The board has 1 open item: 1 in no column."


def test_the_column_the_config_names_is_said_as_waiting_on_you():
    """The owner's own column is named after the owner; the voice says "you", and the code names no one."""
    rules = Settings(waiting_column="Waiting on the owner")
    github = FakeGitHub([FakeItem("Sign the form", "Waiting on the owner", "Owner request"), FakeItem("A", "Blocked")])
    board = GitHubBoard(rules, lambda: SAMPLE_TOKEN, transport=httpx2.MockTransport(github))
    server = build_server(BoardService(board, rules))
    counted = asyncio.run(server.call_tool("board_counts", {})).structured_content
    listed = asyncio.run(server.call_tool("board_list", {})).structured_content
    assert counted["say"] == "The board has 2 open items: 1 waiting on you, 1 blocked."
    assert counted["counts"][0]["status"] == "Waiting on the owner"
    assert listed["say"].startswith("The board has 2 open items. 1: Sign the form, owner request, waiting on you.")


def test_the_waiting_column_matches_whatever_its_case():
    """A config value that differs only in capitals or edge spaces still finds the column."""
    rules = Settings(waiting_column=" waiting ON the owner ")
    github = FakeGitHub([FakeItem("Sign the form", "Waiting on the owner"), FakeItem("A", "Blocked")])
    board = GitHubBoard(rules, lambda: SAMPLE_TOKEN, transport=httpx2.MockTransport(github))
    counted = asyncio.run(build_server(BoardService(board, rules)).call_tool("board_counts", {})).structured_content
    assert counted["say"] == "The board has 2 open items: 1 waiting on you, 1 blocked."


def test_an_empty_waiting_column_names_no_column():
    """The default, empty, never turns a column with a blank name into "you"."""
    answer = _call(FakeGitHub([FakeItem("A", " ")]))
    assert "you" not in answer["say"]


def test_a_column_name_is_said_as_the_board_names_it():
    """Nothing in the code knows the columns: a new one is counted under its own name."""
    answer = _call(FakeGitHub([FakeItem("A", "Ready to merge"), FakeItem("B", "Ready to merge")]))
    assert answer["say"] == "The board has 2 open items: 2 ready to merge."


def test_equal_counts_keep_the_board_s_own_order():
    answer = _call(FakeGitHub([FakeItem("A", "Blocked"), FakeItem("B", "Backlog")]))
    assert answer["say"] == "The board has 2 open items: 1 blocked, 1 backlog."


def test_an_empty_board_says_so():
    answer = _call(FakeGitHub([FakeItem("Paint the fence", "Done")]))
    assert (answer["say"], answer["counts"], answer["total"]) == ("The board has no open items.", [], 0)


def test_a_failure_is_said_as_board_list_says_it():
    answer = _call(FakeGitHub(BOARD), token="an old key")  # noqa: S106 - made up
    assert (answer["success"], answer["outcome"], answer["say"]) == (False, "key_refused", KEY_REFUSED)


def test_a_simulated_count_says_so():
    answer = _call(FakeGitHub(BOARD), simulated=True)
    assert answer["say"].startswith("Simulated: The board has 6 open items")
