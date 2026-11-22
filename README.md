# board-mcp

A GitHub project board, read by voice. This is an MCP server that a voice assistant reaches
through claude-voice, as one of its plugins. It has two tools:
- `board_list`: ask "what's on the board?" and it reads the open items, highest priority first.
  Each item says how long it has been in its column, such as "waiting for review for 6 hours".
- `board_counts`: ask "how many are waiting for review?" and it says the count in each column,
  such as "3 waiting for review, 1 in progress". Done is left out unless asked for. Open items
  in no column are said last, so its total is the one `board_list` gives.

The column names are the board's own, and the time in a column is GitHub's own record of when
the item's Status last changed. The plugin keeps nothing itself. Name the column for work that
waits on you as `waiting_column` in the config, and the voice says it as "waiting on you".

It only reads. The board mirrors the work, so reading it starts, stops or changes nothing.

## The key

It reads the board with a classic GitHub token that has only the `read:project` right, and no
`repo` right. Fine-grained tokens can't reach a project owned by a user account yet. A classic
token reads every project the account can see, and never expires unless told to, so give it an
expiry, such as 90 days. When GitHub refuses it, make a new one with the same single right. Enter the
key with secret-box, into the file `token_file` names in the plugin's config folder. It is read
from there and nowhere else, and never logged. Without the `repo` right, an item from a private
repository is read out as "a private item", with no title.

It started from claude-voice's plugin template. The guide for writing one is
`docs/write-a-plugin.md` in claude-voice, and `docs/plugin-standard.md` there holds the rules.

## Try it

<!-- not run: it needs the project installed, which `just setup` does -->
```
just setup
uv run board-mcp list --simulate
```

The second line prints what the voice would hear, from the made-up board behind the fake GitHub
in `fake.py`.

## Install it in claude-voice

<!-- not run: it changes the owner's own bridge config, and asks in a terminal -->
```
claude-voice plugins install board --from <this folder>
```

It reads `claude-voice-plugin.toml`, writes `config.default.toml` as your first config, and
ends with the usual typed-name approval. On the way it asks whose board it is and its number,
and writes your answers into that config. It never asks for the key: its summary names the
secret-box line to run for that.

## What is where

| Part | What it is for |
|---|---|
| `src/board_mcp/server.py` | The MCP tools. Each answer carries a `say`, the sentence the voice reads aloud. |
| `src/board_mcp/service.py` | The core: it orders the board and words every answer, failures included. |
| `src/board_mcp/device.py` | What the service needs from a board, and the ways reading one fails. |
| `src/board_mcp/github.py` | The real board, read through GitHub's GraphQL API. |
| `src/board_mcp/fake.py` | A made-up GitHub that refuses what the real one refuses. |
| `src/board_mcp/settings.py` | The plugin's own config and key, from its own folder. |
| `src/board_mcp/platform/` | The one place that knows the operating system. |
| `scripts/ratchet.py` | The quality levels, which may never get worse than main's. |
| `scripts/mutate.py` | Switches each rule off in turn, to prove its test can fail. |

## The checks

Every check is a recipe in the `justfile`, and CI runs the same lines.
`just check` runs the ones a pull request needs, with no network.

<!-- not run: these are the gates; running them from a gate would recurse -->
```
just check
just commits
just ratchet
```

A new test must fail on the code before it, and the `red-first` job proves that. It runs only
the test files a change touches. So it does not see a change to shared test setup, such as
`tests/conftest.py`; say that in the pull request.

A rule is a line marked `# RULE: what it says`. Each one needs a test with its words as the
name, and a row in `scripts/mutations/`.

A commit may carry `Co-Authored-By` and an outside contributor's `Signed-off-by`, and no other
trailers. Any other note
belongs in the pull request's text. `just setup` turns on the hook that says so early.

## Cleaning up your own worktree

A session that worked in a worktree of its own removes it when it is done. Do it in this order.

1. While `scripts/.mutate-recovery.json` exists, a mutation run of yours still has a line
   switched off. Stop that run with SIGTERM, and it puts the line back itself.
2. Run the repair, which puts back a line a killed run left and runs nothing else.
3. Check that `git status` shows nothing. A plain `git worktree remove` refuses a worktree with
   changes, and that refusal is the point: never add `--force`.
4. Remove the worktree. Each run's temporary folder went with the run itself.

<!-- not run: these clean up a worktree, so they would remove the one the docs check runs in -->
```
kill -TERM <the mutation run's process>
uv run python scripts/mutate.py --repair-only
git status --short
git worktree remove <the worktree's path>
```
