from datetime import time

import pytest

from ddhelper.config import ConfigError, Settings, load_dotenv


def test_defaults():
  s = Settings.from_env({})
  assert s.sales_poll_seconds == 300 and s.floor_poll_seconds == 300
  assert s.digest_time == time(9, 0)
  assert s.x_bearer_token is None
  assert "ddhelper/" in s.user_agent


def test_secrets_not_in_repr():
  s = Settings.from_env({"DISCORD_TOKEN": "discord-secret", "X_BEARER_TOKEN": "x-secret"})
  assert "discord-secret" not in repr(s) and "x-secret" not in repr(s)


@pytest.mark.parametrize(
  ("env", "msg"),
  [
    ({"SALES_POLL_SECONDS": "5"}, "SALES_POLL_SECONDS"),
    ({"FLOOR_ALERT_PCT": "abc"}, "FLOOR_ALERT_PCT"),
    ({"DISCORD_GUILD_ID": "12ab"}, "DISCORD_GUILD_ID"),
    ({"DIGEST_TIME": "25:00"}, "DIGEST_TIME"),
    ({"DDHELPER_TZ": "Mars/Olympus"}, "DDHELPER_TZ"),
    ({"X_ACCOUNTS": "good,bad name"}, "invalid X username"),
    ({"CARD_SOURCE": "local"}, "CARD_FILE"),
    ({"DDHELPER_USER_AGENT": "a\r\nInjected: 1"}, "single line"),
  ],
)
def test_validation(env, msg):
  with pytest.raises(ConfigError, match=msg):
    Settings.from_env(env)


def test_require_discord():
  with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
    Settings.from_env({}).require_discord()
  Settings.from_env(
    {"DISCORD_TOKEN": "t", "DISCORD_GUILD_ID": "1188215586057093120"}
  ).require_discord()


def test_dotenv(tmp_path):
  p = tmp_path / ".env"
  p.write_text("# c\nA=1\nexport B='two'\nC=\"3\"\nEXISTING=new\n")
  env = {"EXISTING": "old"}
  assert load_dotenv(p, env)
  assert env == {"EXISTING": "old", "A": "1", "B": "two", "C": "3"}
  assert not load_dotenv(tmp_path / "missing", env)
