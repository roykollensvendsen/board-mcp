"""The settings come from the plugin's own config folder, and a key it does not know is refused."""

import pathlib

import pytest

from board_mcp import settings
from board_mcp.device import NotSetUpError
from board_mcp.platform.linux import Linux
from board_mcp.service import NOT_SET_UP

ROOT = pathlib.Path(__file__).parent.parent


def test_no_config_file_gives_the_defaults(tmp_path):
    assert settings.load(tmp_path / "missing.toml") == settings.Settings()


def test_the_shipped_default_config_loads_as_the_defaults():
    """Install writes config.default.toml as the first config, so it must read back cleanly."""
    assert settings.load(ROOT / "config.default.toml") == settings.Settings()


def test_a_board_is_read_from_its_config(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '[board]\nowner_kind = "organization"\nowner = "example-org"\nnumber = 3\n'
        'done = ["Shipped"]\nclass_order = ["Must", "Could"]\nsimulate = false\n'
    )
    loaded = settings.load(path)
    assert (loaded.owner_kind, loaded.owner) == ("organization", "example-org")
    assert (loaded.number, loaded.simulate) == (3, False)
    assert (loaded.done, loaded.class_order) == (("Shipped",), ("Must", "Could"))


def test_a_key_the_plugin_does_not_know_is_refused_by_name(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[board]\nownr = "x"\n[other]\n')
    with pytest.raises(settings.SettingsError, match=r"board\.ownr, other|other, board\.ownr"):
        settings.load(path)


def test_an_owner_kind_github_does_not_have_is_refused(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[board]\nowner_kind = "team"\n')
    with pytest.raises(settings.SettingsError, match="user or organization"):
        settings.load(path)


def test_only_a_user_or_organization_owner_kind_reaches_the_query(tmp_path):
    """owner_kind is pasted into the query's text, so anything else could add to the query."""
    path = tmp_path / "config.toml"
    path.write_text('[board]\nowner_kind = "user(login: \\"x\\") { id } other: user"\n')
    with pytest.raises(settings.SettingsError, match="user or organization"):
        settings.load(path)


def test_the_key_advice_says_to_set_an_expiry():
    """A classic token never expires unless told to, and it reads every board the account sees."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for advice in (settings.ENTER_KEY, NOT_SET_UP, readme):
        assert "expiry" in advice


def test_a_config_that_is_not_toml_says_how_to_fix_it(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[board\n")
    with pytest.raises(settings.SettingsError, match="delete it to use the defaults"):
        settings.load(path)


def test_the_config_is_found_in_the_plugin_s_own_folder(monkeypatch, tmp_path):
    monkeypatch.delenv(settings.CONFIG_ENV)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert settings.config_file() == tmp_path / "board-mcp" / "config.toml"
    monkeypatch.setenv(settings.CONFIG_ENV, str(tmp_path / "other.toml"))
    assert settings.config_file() == tmp_path / "other.toml"


def test_the_config_home_falls_back_to_the_home_folder(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert Linux().config_home() == tmp_path / ".config"


@pytest.mark.parametrize("name", ["../token", "/etc/token", "keys/token", ".token", ""])
def test_the_token_is_read_only_from_the_plugin_s_config_folder(tmp_path, name):
    path = tmp_path / "config.toml"
    path.write_text(f'[board]\ntoken_file = "{name}"\n')
    with pytest.raises(settings.SettingsError, match="a file name in board-mcp's config folder"):
        settings.load(path)


def test_the_token_file_sits_beside_the_config(monkeypatch, tmp_path):
    monkeypatch.setenv(settings.CONFIG_ENV, str(tmp_path / "config.toml"))
    assert settings.token_path(settings.Settings()) == tmp_path / "github-token"


def test_a_missing_token_names_the_secret_box_step(tmp_path):
    with pytest.raises(NotSetUpError, match="secret-box"):
        settings.read_token(tmp_path / "github-token")


def test_an_empty_token_file_counts_as_missing(tmp_path):
    token = tmp_path / "github-token"
    token.write_text("\n")
    with pytest.raises(NotSetUpError, match="secret-box"):
        settings.read_token(token)


def test_a_token_is_read_without_its_line_end(tmp_path):
    token = tmp_path / "github-token"
    token.write_text("made-up-key\n")
    assert settings.read_token(token) == "made-up-key"
