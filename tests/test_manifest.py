"""The install manifest meets claude-voice's published format, and says what the code does.

`tests/plugin-manifest-v1.json` is a copy of `docs/plugin-manifest/v1.json` in claude-voice,
kept here so this check runs offline, without its `$id`. When the bridge publishes a new
version, copy it again.
"""

import json
import pathlib
import sys
import tomllib

import jsonschema
import pytest

from board_mcp import settings
from board_mcp.server import TOOLS

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import private_data_scan

SCHEMA = json.loads((ROOT / "tests/plugin-manifest-v1.json").read_text(encoding="utf-8"))


def _manifest():
    return tomllib.loads((ROOT / "claude-voice-plugin.toml").read_text(encoding="utf-8"))


def test_the_manifest_meets_the_published_format():
    jsonschema.validate(_manifest(), SCHEMA)


@pytest.mark.parametrize(
    "change",
    [{"surprise": 1}, {"name": "Not A Name"}, {"tools": []}, {"uses": ["position"]}],
    ids=["an unknown key", "a bad name", "no tools", "an unknown shared value"],
)
def test_the_format_refuses_what_install_would_refuse(change):
    """Proof the check above can fail: each of these is refused by name in the bridge too."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**_manifest(), **change}, SCHEMA)


def test_the_manifest_lists_exactly_the_tools_the_server_offers():
    assert sorted(_manifest()["tools"]) == sorted(TOOLS)


def test_the_manifest_starts_the_command_this_package_installs():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    manifest = _manifest()
    assert manifest["args"][-1] == "serve"
    assert manifest["args"][-2] in pyproject["project"]["scripts"]


def test_the_manifest_names_the_config_folder_the_plugin_reads():
    config = _manifest()["config"]
    assert config["dir"] == settings.CONFIG_DIR
    assert (ROOT / config["default"]).is_file()


def _default_config():
    return tomllib.loads((ROOT / _manifest()["config"]["default"]).read_text(encoding="utf-8"))


def test_install_asks_whose_board_and_its_number():
    personal = {field["key"]: field for field in _manifest()["config"]["personal"]}
    assert sorted(personal) == ["board.number", "board.owner", "board.owner_kind"]
    board = _default_config()["board"]
    for key in personal:
        assert key.removeprefix("board.") in board, f"{key} is asked but the default config has no such key"
    assert personal["board.owner_kind"]["values"] == sorted(settings.OWNER_KINDS)


def test_the_answers_install_asks_for_are_accepted_by_the_plugin(tmp_path):
    """The longest login GitHub allows and the highest number asked both load as settings."""
    personal = {field["key"]: field for field in _manifest()["config"]["personal"]}
    login = "a" * personal["board.owner"]["max_len"]
    highest = personal["board.number"]["range"][1]
    config = tmp_path / "config.toml"
    config.write_text(f'[board]\nowner_kind = "organization"\nowner = "{login}"\nnumber = {highest}\n')
    loaded = settings.load(config)
    assert (loaded.owner_kind, loaded.owner, loaded.number) == ("organization", login, highest)


def test_an_installed_config_reads_the_real_board():
    """Install fills in the owner's board, so the copy it writes asks GitHub, not the fake."""
    assert _default_config()["board"]["simulate"] is False


def test_the_secrets_step_enters_the_key_where_the_plugin_reads_it():
    where = f"~/.config/{settings.CONFIG_DIR}/{settings.Settings().token_file}"
    assert _manifest()["secrets_step"] == f"secret-box {where}"


def test_the_default_config_holds_made_up_values_only():
    text = (ROOT / _manifest()["config"]["default"]).read_text(encoding="utf-8")
    assert private_data_scan.offences(text, set()) == []
    assert 'owner = "example-owner"' in text, "the shipped owner is made up, so it names no real account"
