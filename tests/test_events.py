from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from ddhelper.events import load_events

CONFIG = Path(__file__).parents[1] / "config" / "events.toml"


def test_shipped_config_has_ddmiami():
  cfg = load_events(CONFIG)
  up = cfg.upcoming(date(2026, 10, 23))
  assert up[0].name == "DDMIAMI 2026"
  assert (up[0].start, up[0].end) == (date(2026, 12, 7), date(2026, 12, 9))
  assert cfg.upcoming(date(2026, 12, 10)) == []
  assert cfg.upcoming(date(2026, 12, 8))[0].name == "DDMIAMI 2026"  # still running


def test_recurring_today_in_tz():
  cfg = load_events(CONFIG)
  at = cfg.recurring[0].next_today(datetime(2026, 10, 23, 16, tzinfo=UTC))
  assert at is not None and at.hour == 17 and at.utcoffset().total_seconds() == -4 * 3600


def test_missing_file_is_empty(tmp_path):
  assert load_events(tmp_path / "nope.toml").events == ()


def test_invalid_event(tmp_path):
  p = tmp_path / "e.toml"
  p.write_text('[[event]]\nname = "x"\nstart = 2026-12-09\nend = 2026-12-07\n')
  with pytest.raises(ValueError):
    load_events(p)
  p.write_text('[[recurring]]\nname = "x"\ntime = "17:00"\ndays = ["funday"]\n')
  with pytest.raises(ValueError):
    load_events(p)
