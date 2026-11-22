"""The plugin's own settings, read from its own config folder.

`claude-voice plugins install` writes `config.default.toml` there the first time, so the file
holds exactly the keys that file has. A key it does not know is refused by name, so a typo
never passes as a default silently. The GitHub key is a file of its own in the same folder,
written with secret-box, and is read only when a request needs it.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import tomllib
from dataclasses import dataclass
from typing import Any

from board_mcp import platform
from board_mcp.device import NotSetUpError

#: The folder under the config home, as the manifest's `config.dir` names it.
CONFIG_DIR = "board-mcp"
#: Points at another config file, for a test or a second board.
CONFIG_ENV = "BOARD_MCP_CONFIG"
OWNER_KINDS = ("user", "organization")
ENTER_KEY = (
    "no GitHub key is set up; make a classic token with only the read:project right and an expiry, "
    "and enter it with secret-box, as the file named by token_file in board-mcp's config folder"
)


class SettingsError(ValueError):
    """The config file cannot be used; the message names the fix."""


@dataclass(frozen=True)
class Settings:
    """What the plugin reads from its config file: whose board, and the board's own rules."""

    owner_kind: str = "user"
    owner: str = "example-owner"
    number: int = 1
    token_file: str = "github-token"  # noqa: S105 - a file name, not a key
    status_field: str = "Status"
    done: tuple[str, ...] = ("Done",)
    class_field: str = "Class"
    class_order: tuple[str, ...] = ("Owner request", "Bug", "Idea")
    waiting_column: str = ""
    # RULE: with no config list asks for the key and never reads the fake
    simulate: bool = False


KEYS = {field.name: field.default for field in dataclasses.fields(Settings)}


def config_file() -> pathlib.Path:
    """Where the config is: `$BOARD_MCP_CONFIG`, or the plugin's folder in the config home."""
    named = os.environ.get(CONFIG_ENV)
    return pathlib.Path(named) if named else platform.current().config_home() / CONFIG_DIR / "config.toml"


def load(path: pathlib.Path | None = None) -> Settings:
    """The settings in `path`, or the defaults when there is no file."""
    path = config_file() if path is None else path
    if not path.is_file():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as broken:
        msg = f"{path} is not valid TOML ({broken}); fix it, or delete it to use the defaults"
        raise SettingsError(msg) from broken
    board = data.pop("board", {})
    unknown = sorted(data) + sorted(f"board.{key}" for key in board if key not in KEYS)
    if unknown:
        msg = f"{path} has keys board-mcp does not know: {', '.join(unknown)}; remove them or fix their spelling"
        raise SettingsError(msg)
    values: dict[str, Any] = {
        key: tuple(value) if isinstance(KEYS[key], tuple) else value for key, value in board.items()
    }
    return _checked(path, Settings(**values))


def _checked(path: pathlib.Path, loaded: Settings) -> Settings:
    # RULE: only a user or organization owner kind reaches the query
    if loaded.owner_kind not in OWNER_KINDS:
        msg = f"{path}: owner_kind is {loaded.owner_kind!r}; it must be user or organization"
        raise SettingsError(msg)
    name = loaded.token_file
    # RULE: the token is read only from the plugin's config folder
    if not name or name.startswith(".") or "/" in name or "\\" in name:
        msg = f"{path}: token_file must be a file name in board-mcp's config folder, not a path"
        raise SettingsError(msg)
    return loaded


def token_path(loaded: Settings) -> pathlib.Path:
    """The key file, beside the config file in the plugin's own folder."""
    return config_file().parent / loaded.token_file


def read_token(path: pathlib.Path) -> str:
    """The key in `path`, without its line end; a missing or empty file says how to enter one."""
    # RULE: a missing token names the secret-box step
    if not path.is_file():
        raise NotSetUpError(ENTER_KEY)
    token = path.read_text(encoding="utf-8").strip()
    if not token:
        raise NotSetUpError(ENTER_KEY)
    return token
