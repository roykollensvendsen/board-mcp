"""The command line says what the voice would hear, and a broken config says how to fix it."""

import pytest

from board_mcp import cli
from board_mcp.service import NOT_SET_UP


def test_list_says_what_the_voice_would_hear(capsys):
    assert cli.main(["list", "--simulate"]) == 0
    assert capsys.readouterr().out.startswith("Simulated: The board has 4 open items. 1: ")


def test_counts_says_what_the_voice_would_hear(capsys):
    assert cli.main(["counts", "--simulate"]) == 0
    assert capsys.readouterr().out == "Simulated: The board has 4 open items: 3 todo, 1 in progress.\n"


def test_with_no_token_set_up_list_says_how_to_enter_one(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.toml"
    config.write_text("[board]\nsimulate = false\n")
    monkeypatch.setenv("BOARD_MCP_CONFIG", str(config))
    assert cli.main(["list"]) == 0
    assert capsys.readouterr().out == NOT_SET_UP + "\n"


def test_with_no_config_list_asks_for_the_key_and_never_reads_the_fake(tmp_path, monkeypatch, capsys):
    """Only --simulate or the config's own simulate = true answers from the made-up board."""
    monkeypatch.setenv("BOARD_MCP_CONFIG", str(tmp_path / "missing.toml"))
    assert cli.main(["list"]) == 0
    assert capsys.readouterr().out == NOT_SET_UP + "\n"


def test_a_broken_config_stops_the_command_with_the_fix(tmp_path, monkeypatch, capsys):
    config = tmp_path / "config.toml"
    config.write_text("[board\n")
    monkeypatch.setenv("BOARD_MCP_CONFIG", str(config))
    assert cli.main(["list"]) == 2
    assert "delete it to use the defaults" in capsys.readouterr().err


def test_every_verb_is_one_the_command_takes():
    for verb in cli.COMMANDS:
        with pytest.raises(SystemExit) as shown:
            cli.main([verb, "--help"])
        assert shown.value.code == 0
