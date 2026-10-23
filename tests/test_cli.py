import json

from ddhelper import cli

from .conftest import load


def test_dry_run_card_local_source(tmp_path, monkeypatch, capsys):
  p = tmp_path / "cards.json"
  p.write_text(json.dumps(load("ddl_cards_subset.json")))
  monkeypatch.setenv("CARD_SOURCE", "local")
  monkeypatch.setenv("CARD_FILE", str(p))
  rc = cli.main(["--env-file", str(tmp_path / "none"), "dry-run", "card", "renza"])
  out = capsys.readouterr().out
  assert rc == 0
  assert "**Renza** (V052)" in out
  assert "local file cards.json" in out


def test_dry_run_card_rejects_bad_input(tmp_path, monkeypatch, capsys):
  monkeypatch.setenv("CARD_SOURCE", "local")
  monkeypatch.setenv("CARD_FILE", str(tmp_path / "x.json"))
  assert cli.main(["--env-file", str(tmp_path / "none"), "dry-run", "card", "<@everyone>"]) == 64


def test_run_requires_token(tmp_path, monkeypatch, capsys):
  monkeypatch.delenv("DISCORD_TOKEN", raising=False)
  assert cli.main(["--env-file", str(tmp_path / "none"), "run"]) == 78
  assert "DISCORD_TOKEN" in capsys.readouterr().err


def test_bad_n(tmp_path):
  assert cli.main(["--env-file", str(tmp_path / "none"), "dry-run", "sales", "-n", "100"]) == 64


def test_bot_module_least_privilege():
  from ddhelper import bot

  assert bot.INTENTS.guilds
  assert not bot.INTENTS.message_content
  assert not bot.INTENTS.members and not bot.INTENTS.presences
  assert bot.INTENTS.value == 1  # GUILDS only
  assert bot.INVITE_PERMISSIONS == 1024 | 2048
  assert "scope=bot%20applications.commands" in bot.INVITE_URL_TEMPLATE
