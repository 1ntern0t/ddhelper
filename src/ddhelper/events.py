"""Upcoming events from a TOML config file (no scraping)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Event:
  name: str
  start: date
  end: date
  location: str = ""
  url: str = ""
  note: str = ""


@dataclass(frozen=True)
class Recurring:
  name: str
  at: time
  tz: str
  days: tuple[str, ...]
  url: str = ""
  note: str = ""

  def next_today(self, now: datetime) -> datetime | None:
    local = now.astimezone(ZoneInfo(self.tz))
    if _WEEKDAYS[local.weekday()] not in self.days:
      return None
    return datetime.combine(local.date(), self.at, ZoneInfo(self.tz))


@dataclass(frozen=True)
class EventsConfig:
  events: tuple[Event, ...] = ()
  recurring: tuple[Recurring, ...] = ()

  def upcoming(self, today: date, horizon_days: int = 120) -> list[Event]:
    return sorted(
      (e for e in self.events if e.end >= today and (e.start - today).days <= horizon_days),
      key=lambda e: e.start,
    )


def _to_date(v: object, field: str) -> date:
  if isinstance(v, date) and not isinstance(v, datetime):
    return v
  if isinstance(v, str):
    return date.fromisoformat(v)
  raise ValueError(f"{field}: expected a date (YYYY-MM-DD)")


def load_events(path: str | Path) -> EventsConfig:
  p = Path(path)
  if not p.is_file():
    log.warning("events file %s not found; digest will have no upcoming events", p)
    return EventsConfig()
  with p.open("rb") as f:
    raw = tomllib.load(f)
  events = []
  for e in raw.get("event", []):
    start = _to_date(e["start"], "start")
    end = _to_date(e.get("end", start), "end")
    if end < start:
      raise ValueError(f"event {e.get('name')!r}: end before start")
    events.append(
      Event(
        str(e["name"]),
        start,
        end,
        str(e.get("location", "")),
        str(e.get("url", "")),
        str(e.get("note", "")),
      )
    )
  rec = []
  for r in raw.get("recurring", []):
    at = r["time"] if isinstance(r["time"], time) else time.fromisoformat(str(r["time"]))
    days = tuple(d.lower()[:3] for d in r.get("days", list(_WEEKDAYS)))
    bad = [d for d in days if d not in _WEEKDAYS]
    if bad:
      raise ValueError(f"recurring {r.get('name')!r}: bad days {bad}")
    tz = str(r.get("tz", "America/New_York"))
    ZoneInfo(tz)
    rec.append(
      Recurring(str(r["name"]), at, tz, days, str(r.get("url", "")), str(r.get("note", "")))
    )
  return EventsConfig(tuple(events), tuple(rec))
