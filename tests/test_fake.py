"""The fake GitHub refuses what the real one refuses, so a test cannot pass that GitHub would fail."""

import json

import httpx2

from board_mcp.fake import PAGE_MOST, SAMPLE_TOKEN, FakeGitHub

QUERY = "query { owner: user(login: $login) { projectV2(number: $number) { items(first: $first) { nodes { id } } } } }"


def _ask(github, *, token=SAMPLE_TOKEN, first=10, login="example-owner", number=1):
    body = {"query": QUERY, "variables": {"login": login, "number": number, "first": first, "status": "Status"}}
    request = httpx2.Request(
        "POST",
        "https://api.github.com/graphql",
        headers={"Authorization": f"Bearer {token}"},
        content=json.dumps(body).encode(),
    )
    return github(request)


def test_the_fake_refuses_a_request_without_the_right_token():
    answer = _ask(FakeGitHub(), token="not the key")  # noqa: S106 - made up
    assert answer.status_code == 401
    assert answer.json() == {"message": "Bad credentials"}


def test_the_fake_gives_at_most_a_hundred_items_a_page():
    answer = _ask(FakeGitHub(), first=PAGE_MOST + 1).json()
    assert answer["data"] is None
    assert "exceeds the `first` limit of 100 records" in answer["errors"][0]["message"]


def test_the_fake_says_not_found_for_another_owners_board():
    answer = _ask(FakeGitHub(), login="someone-else").json()
    assert answer["data"] == {"owner": None}
    assert answer["errors"][0]["type"] == "NOT_FOUND"


def test_the_fake_refuses_a_key_without_a_project_right():
    answer = _ask(FakeGitHub(scopes=("repo",))).json()
    assert answer["errors"][0]["type"] == "INSUFFICIENT_SCOPES"


def test_the_fake_stops_answering_past_the_rate_limit():
    github = FakeGitHub(clock=lambda: 1000.0)
    github.requests_left = 0
    answer = _ask(github)
    assert answer.status_code == 403
    assert (answer.headers["x-ratelimit-remaining"], answer.headers["x-ratelimit-reset"]) == ("0", "1060")
