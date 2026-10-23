"""Settings loaded from environment variables (optionally from a .env file)."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import __version__

DEFAULT_USER_AGENT = (
  f"ddhelper/{__version__} (Doginal Dogs community helper bot; read-only; "
  "+https://x.com/1nternot)"
)

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")


class ConfigError(ValueError):
  """Raised when an environment variable is missing or malformed."""


def load_dotenv(path: str | os.PathLike[str] = ".env", environ: dict[str, str] | None = None) -> bool:
  """Minimal .env loader. Existing variables win; returns True if the file was read.

  Supports KEY=VALUE lines, comments (#), blank lines and optional single/double quotes.
  """
  env = os.environ if environ is None else environ
  p = Path(path)
  if not p.is_file():
    return False
  for raw in p.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, _, value = line.partition("=")
    key = key.strip()
    if key.startswith("export "):
      key = key[len("export "):].strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
      value = value[1:-1]
    env.setdefault(key, value)
  return True


def _opt_str(env: Mapping[str, str], key: str) -> str | None:
  v = env.get(key, "").strip()
  return v or None


def _opt_int(env: Mapping[str, str], key: str) -> int | None:
  v = env.get(key, "").strip()
  if not v:
    return None
  if not v.isdigit():
    raise ConfigError(f"{key} must be a positive integer (Discord snowflake)")
  return int(v)


def _num(env: Mapping[str, str], key: str, default: float, lo: float, hi: float) -> float:
  v = env.get(key, "").strip()
  if not v:
    return default
  try:
    n = float(v)
  except ValueError as e:
    raise ConfigError(f"{key} must be a number") from e
  if not lo <= n <= hi:
    raise ConfigError(f"{key} must be between {lo} and {hi}")
  return n


def _csv(env: Mapping[str, str], key: str, default: str) -> tuple[str, ...]:
  raw = env.get(key, default)
  return tuple(x.strip() for x in raw.split(",") if x.strip())


@dataclass(frozen=True)
class Settings:
  # Discord (only needed for `run`)
  discord_token: str | None = field(default=None, repr=False)
  guild_id: int | None = None
  alert_channel_id: int | None = None
  digest_channel_id: int | None = None
  # X API v2 (optional; digest notes the gap without it)
  x_bearer_token: str | None = field(default=None, repr=False)
  x_accounts: tuple[str, ...] = ("doginaldogs", "barkmeta", "DDLTCG", "DDSalesBot")
  x_filtered_accounts: tuple[str, ...] = ("barkmeta",)
  x_filter_keywords: tuple[str, ...] = (
    "doginal", "ddl", "legends", "ddmiami", "pack", "space", "wizzy", "woof",
  )
  # Polling (seconds). Modest defaults: be a polite client.
  sales_poll_seconds: int = 300
  floor_poll_seconds: int = 300
  # Floor alerts
  floor_alert_pct: float = 10.0
  floor_alert_min_doge: float = 2000.0
  floor_alert_cooldown_seconds: int = 3600
  # Sales alerts
  sales_alert_max_per_cycle: int = 5
  # Digest
  digest_time: time = time(9, 0)
  timezone: str = "America/New_York"
  # Files
  db_path: str = "data/ddhelper.sqlite3"
  events_file: str = "config/events.toml"
  card_source: str = "official"
  card_file: str | None = None
  # Endpoints
  market_base_url: str = "https://market.doginaldogs.com"
  doggy_url: str = "https://api.doggy.market/nfts/doginaldogs"
  cards_url: str = "https://ddltcg.com/data/cards.json"
  x_api_base: str = "https://api.x.com/2"
  tx_explorer_url: str = "https://blockchair.com/dogecoin/transaction/{txid}"
  # HTTP
  http_timeout: float = 15.0
  user_agent: str = DEFAULT_USER_AGENT

  @property
  def tz(self) -> ZoneInfo:
    return ZoneInfo(self.timezone)

  @classmethod
  def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    accounts = _csv(env, "X_ACCOUNTS", ",".join(cls.x_accounts))
    filtered = _csv(env, "X_FILTERED_ACCOUNTS", ",".join(cls.x_filtered_accounts))
    for name in (*accounts, *filtered):
      if not _USERNAME_RE.match(name):
        raise ConfigError(f"invalid X username in config: {name!r}")
    tz_name = env.get("DDHELPER_TZ", cls.timezone).strip() or cls.timezone
    try:
      ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
      raise ConfigError(f"DDHELPER_TZ: unknown time zone {tz_name!r}") from e
    dt_raw = env.get("DIGEST_TIME", "09:00").strip() or "09:00"
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", dt_raw)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
      raise ConfigError("DIGEST_TIME must be HH:MM (24h)")
    card_source = env.get("CARD_SOURCE", "official").strip().lower() or "official"
    if card_source not in ("official", "local"):
      raise ConfigError("CARD_SOURCE must be 'official' or 'local'")
    card_file = _opt_str(env, "CARD_FILE")
    if card_source == "local" and not card_file:
      raise ConfigError("CARD_SOURCE=local requires CARD_FILE")
    ua = _opt_str(env, "DDHELPER_USER_AGENT") or DEFAULT_USER_AGENT
    if any(c in ua for c in "\r\n"):
      raise ConfigError("DDHELPER_USER_AGENT must be a single line")
    return cls(
      discord_token=_opt_str(env, "DISCORD_TOKEN"),
      guild_id=_opt_int(env, "DISCORD_GUILD_ID"),
      alert_channel_id=_opt_int(env, "ALERT_CHANNEL_ID"),
      digest_channel_id=_opt_int(env, "DIGEST_CHANNEL_ID"),
      x_bearer_token=_opt_str(env, "X_BEARER_TOKEN"),
      x_accounts=accounts,
      x_filtered_accounts=filtered,
      x_filter_keywords=tuple(k.lower() for k in _csv(env, "X_FILTER_KEYWORDS", ",".join(cls.x_filter_keywords))),
      # Lower bound of 60s keeps the bot polite even if misconfigured.
      sales_poll_seconds=int(_num(env, "SALES_POLL_SECONDS", 300, 60, 86400)),
      floor_poll_seconds=int(_num(env, "FLOOR_POLL_SECONDS", 300, 60, 86400)),
      floor_alert_pct=_num(env, "FLOOR_ALERT_PCT", 10.0, 0.5, 100),
      floor_alert_min_doge=_num(env, "FLOOR_ALERT_MIN_DOGE", 2000, 0, 1e9),
      floor_alert_cooldown_seconds=int(_num(env, "FLOOR_ALERT_COOLDOWN_SECONDS", 3600, 0, 7 * 86400)),
      sales_alert_max_per_cycle=int(_num(env, "SALES_ALERT_MAX_PER_CYCLE", 5, 1, 20)),
      digest_time=time(int(m.group(1)), int(m.group(2))),
      timezone=tz_name,
      db_path=env.get("DDHELPER_DB", cls.db_path).strip() or cls.db_path,
      events_file=env.get("EVENTS_FILE", cls.events_file).strip() or cls.events_file,
      card_source=card_source,
      card_file=card_file,
      http_timeout=_num(env, "HTTP_TIMEOUT_SECONDS", 15, 1, 120),
      user_agent=ua,
    )

  def require_discord(self) -> None:
    missing = [k for k, v in (
      ("DISCORD_TOKEN", self.discord_token),
      ("DISCORD_GUILD_ID", self.guild_id),
    ) if not v]
    if missing:
      raise ConfigError("missing required settings for the Discord bot: " + ", ".join(missing))
