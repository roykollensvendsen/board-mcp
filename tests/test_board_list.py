"""board_list, end to end: through the MCP server, the service, the GitHub adapter and the fake.

The fake GitHub sits behind httpx2's mock transport, so every test runs the real adapter and
no test reaches the network. Each tool has a file like this one, named after it.
"""

import asyncio

import httpx2

from board_mcp.device import NotSetUpError
from board_mcp.fake import SAMPLE_TOKEN, FakeGitHub, FakeItem
from board_mcp.github import GitHubBoard
from board_mcp.server import build_server
from board_mcp.service import (
    BROKE,
    KEY_REFUSED,
    NO_RIGHT,
    NOT_FOUND,
    NOT_SET_UP,
    UNREACHABLE,
    BoardService,
)
from board_mcp.settings import Settings

RULES = Settings()


def _board(github, token=SAMPLE_TOKEN, rules=RULES):
    def key():
        return token

    return GitHubBoard(rules, key, transport=httpx2.MockTransport(github), clock=lambda: 1000.0)


def _call(github, *, simulated=False, rules=RULES, token=SAMPLE_TOKEN, **asked):
    server = build_server(BoardService(_board(github, token, rules), rules), simulated=simulated)
    return asyncio.run(server.call_tool("board_list", asked)).structured_content


def test_the_board_is_read_in_class_order_then_position():
    github = FakeGitHub(
        [
            FakeItem("Tidy the shed", "Todo", "Idea"),
            FakeItem("Hall lights", "In progress", "Owner request"),
            FakeItem("Fix the gate", "Todo", "Bug"),
            FakeItem("Paint the fence", "Todo", "Owner request"),
        ]
    )
    answer = _call(github)
    assert answer["say"] == (
        "The board has 4 open items. 1: Hall lights, owner request, in progress. "
        "2: Paint the fence, owner request, todo. 3: Fix the gate, bug, todo. 4: Tidy the shed, idea, todo."
    )
    assert [item["number"] for item in answer["items"]] == [1, 2, 3, 4]


def test_an_item_with_no_class_comes_after_every_class():
    github = FakeGitHub([FakeItem("Loose end", "Todo"), FakeItem("Tidy the shed", "Todo", "Idea")])
    assert _call(github)["say"] == "The board has 2 open items. 1: Tidy the shed, idea, todo. 2: Loose end, todo."


def test_done_items_are_left_out():
    github = FakeGitHub([FakeItem("Hall lights", "Done", "Owner request"), FakeItem("Tidy the shed", "Todo", "Idea")])
    assert _call(github)["say"] == "The board has 1 open item. 1: Tidy the shed, idea, todo."


def test_archived_items_are_left_out():
    github = FakeGitHub([FakeItem("Old plan", "Todo", "Idea", archived=True), FakeItem("Tidy the shed", "Todo")])
    assert _call(github)["say"] == "The board has 1 open item. 1: Tidy the shed, todo."


def test_a_private_item_is_said_without_its_title():
    """Without the repo scope, GitHub gives an issue in a private repo as REDACTED, with no content."""
    github = FakeGitHub([FakeItem("Secret plan", "Todo", "Idea", kind="REDACTED")])
    answer = _call(github)
    assert answer["say"] == "The board has 1 open item. 1: a private item, idea, todo."
    assert answer["items"][0]["title"] is None
    assert "Secret plan" not in str(answer)


def test_the_list_stops_at_the_limit_and_says_how_many_more():
    github = FakeGitHub([FakeItem(f"Job {n}", "Todo") for n in range(1, 5)])
    assert _call(github, limit=2)["say"] == "The board has 4 open items. 1: Job 1, todo. 2: Job 2, todo. And 2 more."


def test_an_empty_board_says_so():
    assert _call(FakeGitHub([]))["say"] == "The board has no open items."


def test_every_page_of_the_board_is_read():
    """GitHub gives at most 100 items a page; a bigger board goes on with the page's end cursor."""
    github = FakeGitHub([FakeItem(f"Job {n}", "Todo") for n in range(1, 151)])
    answer = _call(github, limit=1)
    assert answer["say"] == "The board has 150 open items. 1: Job 1, todo. And 149 more."
    assert github.asked == 2


def test_a_limit_out_of_range_is_refused_with_the_range():
    github = FakeGitHub()
    answer = _call(github, limit=0)
    assert (answer["success"], answer["say"]) == (False, "Say how many items, from 1 to 50.")
    assert github.asked == 0


def test_a_simulated_answer_says_so():
    answer = _call(FakeGitHub(), simulated=True)
    assert answer["simulated"] is True
    assert answer["say"].startswith("Simulated: ")


def test_no_token_set_up_says_to_enter_one():
    def missing():
        msg = "no key file"
        raise NotSetUpError(msg)

    board = GitHubBoard(RULES, missing, transport=httpx2.MockTransport(FakeGitHub()))
    answer = asyncio.run(build_server(BoardService(board, RULES)).call_tool("board_list", {})).structured_content
    assert (answer["outcome"], answer["say"]) == ("not_set_up", NOT_SET_UP)
    assert "secret-box" in NOT_SET_UP


def test_a_refused_key_says_to_make_a_new_one():
    assert _call(FakeGitHub(), token="an old key")["say"] == KEY_REFUSED  # noqa: S106 - made up


def test_a_key_without_the_project_right_says_which_right():
    assert _call(FakeGitHub(scopes=("repo",)))["say"] == NO_RIGHT


def test_a_board_github_cannot_find_says_what_to_check():
    assert _call(FakeGitHub(owner="someone-else"))["say"] == NOT_FOUND
    assert _call(FakeGitHub(number=2))["say"] == NOT_FOUND
    assert _call(FakeGitHub(kind="organization"))["say"] == NOT_FOUND


def test_github_off_the_network_is_said_plainly():
    github = FakeGitHub()
    github.unreachable = True
    assert _call(github) == {"success": False, "outcome": "unreachable", "say": UNREACHABLE, "simulated": False}


def test_asking_past_githubs_rate_limit_says_how_long_to_wait():
    github = FakeGitHub(clock=lambda: 1000.0)
    github.requests_left = 0
    answer = _call(github)
    assert (answer["outcome"], answer["say"]) == ("slow_down", "GitHub asks for a pause; ask again in 60 seconds.")


class _Broken:
    async def items(self):
        msg = "a fault nobody planned for"
        raise RuntimeError(msg)


def test_every_answer_has_a_sentence_to_say_even_when_github_fails():
    """Whatever broke, the voice gets a sentence to read, and never a stack trace."""
    server = build_server(BoardService(_Broken(), RULES))
    assert asyncio.run(server.call_tool("board_list", {})).structured_content["say"] == BROKE
