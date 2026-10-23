"""Orchestration: gathers data from sources with graceful degradation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from .config import Settings
from .events import Event, EventsConfig, Recurring
from .http import Fetcher, SourceError
from .sources.cards import Card, CardSource, LocalJsonCardSource, OfficialCardSource, search
from .sources.doggy import DoggyMarket, DoggyStats, staleness_warnings
from .sources.market import MarketStats, OfficialMarket, Sale, volume_window
from .sources.xapi import Post, XClient, XUnavailable
from .state import State

log = logging.getLogger(__name__)


@dataclass
class Volume:
  doge: float
  count: int
  without_tx: int


@dataclass
class FloorReport:
  generated_at: datetime
  stats: MarketStats | None = None
  official_error: str | None = None
  vol_24h: Volume | None = None
  vol_7d: Volume | None = None
  sales_error: str | None = None
  doggy: DoggyStats | None = None
  doggy_error: str | None = None
  doggy_warnings: list[str] = field(default_factory=list)


@dataclass
class FloorAlert:
  old: float
  new: float
  pct: float
  listed: int | None


@dataclass
class DigestData:
  generated_at: datetime
  since: datetime
  floor: FloorReport
  floor_24h_ago: float | None = None
  floor_7d_ago: float | None = None
  sales: list[Sale] = field(default_factory=list)
  posts: dict[str, list[Post]] = field(default_factory=dict)
  sales_bot_posts: int | None = None
  events: list[Event] = field(default_factory=list)
  recurring_today: list[tuple[Recurring, datetime]] = field(default_factory=list)
  gaps: list[str] = field(default_factory=list)


def make_card_source(settings: Settings, fetcher: Fetcher) -> CardSource:
  if settings.card_source == "local":
    assert settings.card_file  # validated in Settings.from_env  # noqa: S101
    return LocalJsonCardSource(settings.card_file)
  return OfficialCardSource(fetcher, settings.cards_url)


def _err(e: Exception) -> str:
  return str(e) or type(e).__name__


class Helper:
  def __init__(
    self,
    settings: Settings,
    fetcher: Fetcher,
    *,
    events: EventsConfig | None = None,
    cards: CardSource | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
  ):
    self.settings = settings
    self.market = OfficialMarket(fetcher, settings.market_base_url)
    self.doggy = DoggyMarket(fetcher, settings.doggy_url)
    self.x = XClient(fetcher, settings.x_bearer_token, settings.x_api_base)
    self.cards = cards or make_card_source(settings, fetcher)
    self.events = events or EventsConfig()
    self.clock = clock

  # /floor
  async def floor_report(self) -> FloorReport:
    now = self.clock()
    rep = FloorReport(generated_at=now)
    stats_r, sales_r, doggy_r = await asyncio.gather(
      self.market.stats(),
      self.market.sales_since(now - timedelta(days=7)),
      self.doggy.stats(),
      return_exceptions=True,
    )
    if isinstance(stats_r, MarketStats):
      rep.stats = stats_r
    else:
      rep.official_error = _err(stats_r)
    if isinstance(sales_r, list):
      rep.vol_24h = Volume(*volume_window(sales_r, now, timedelta(hours=24)))
      rep.vol_7d = Volume(*volume_window(sales_r, now, timedelta(days=7)))
    else:
      rep.sales_error = _err(sales_r)
    if isinstance(doggy_r, DoggyStats):
      rep.doggy = doggy_r
      rep.doggy_warnings = staleness_warnings(doggy_r, rep.stats.floor if rep.stats else None, now)
    else:
      rep.doggy_error = _err(doggy_r)
    for r in (stats_r, sales_r, doggy_r):
      if isinstance(r, BaseException) and not isinstance(r, SourceError):
        log.error("unexpected error in floor report", exc_info=r)
    return rep

  # /sales
  async def recent_sales(self, n: int) -> list[Sale]:
    n = max(1, min(n, 25))
    sales, _ = await self.market.recent_sales(min(50, n))
    return sorted(sales, key=lambda s: s.created_at, reverse=True)[:n]

  # /card
  async def find_card(self, query: str) -> list[Card]:
    return search(await self.cards.all_cards(), query)

  # /digest
  async def digest(self) -> DigestData:
    now = self.clock()
    since = now - timedelta(hours=24)
    floor, hist, posts = await asyncio.gather(
      self.floor_report(),
      self.market.floor_history("7d"),
      self._x_posts(since),
      return_exceptions=True,
    )
    assert isinstance(floor, FloorReport)  # floor_report never raises SourceError  # noqa: S101
    d = DigestData(generated_at=now, since=since, floor=floor)
    if floor.official_error:
      d.gaps.append(f"Official market stats unavailable ({floor.official_error}).")
    if floor.sales_error:
      d.gaps.append(f"Official sales feed unavailable ({floor.sales_error}).")
    if floor.doggy_error:
      d.gaps.append(f"Doggy Market unavailable ({floor.doggy_error}).")
    if isinstance(hist, list) and hist:
      d.floor_24h_ago = _value_at(hist, now - timedelta(hours=24))
      d.floor_7d_ago = hist[0][1]  # first point of the 7d series
    elif isinstance(hist, BaseException):
      d.gaps.append(f"Floor history unavailable ({_err(hist)}).")
    if not floor.sales_error:
      try:
        d.sales = await self.market.sales_since(since)
      except SourceError as e:
        d.gaps.append(f"Sales list unavailable ({_err(e)}).")
    if isinstance(posts, tuple):
      d.posts, d.sales_bot_posts, x_gaps = posts
      d.gaps.extend(x_gaps)
    else:
      d.gaps.append(f"X posts unavailable ({_err(posts)}).")
    today_local = now.astimezone(self.settings.tz).date()
    d.events = self.events.upcoming(today_local)
    for r in self.events.recurring:
      at = r.next_today(now)
      if at is not None:
        d.recurring_today.append((r, at))
    return d

  async def _x_posts(self, since: datetime) -> tuple[dict[str, list[Post]], int | None, list[str]]:
    gaps: list[str] = []
    if not self.x.available:
      return {}, None, ["X posts not included: X_BEARER_TOKEN is not set."]
    try:
      ids = await self.x.user_ids(self.settings.x_accounts)
    except XUnavailable as e:
      return {}, None, [f"X posts unavailable ({_err(e)})."]
    out: dict[str, list[Post]] = {}
    sales_bot: int | None = None
    filtered = {a.lower() for a in self.settings.x_filtered_accounts}
    for username in self.settings.x_accounts:
      uid = ids.get(username)
      if uid is None:
        gaps.append(f"X account @{username} not found.")
        continue
      try:
        posts = [
          p for p in await self.x.recent_posts(username, uid, since) if p.created_at >= since
        ]
      except XUnavailable as e:
        gaps.append(f"X posts for @{username} unavailable ({_err(e)}).")
        continue
      if username.lower() == "ddsalesbot":
        sales_bot = len(posts)
        continue
      if username.lower() in filtered:
        posts = [p for p in posts if self._relevant(p)]
      out[username] = posts[:5]
    return out, sales_bot, gaps

  def _relevant(self, p: Post) -> bool:
    if p.space_urls or p.link_only:
      return True
    t = p.text.lower()
    return any(k in t for k in self.settings.x_filter_keywords)

  # background jobs
  async def poll_new_sales(self, state: State) -> list[Sale]:
    """New sales since last poll, oldest first. First run only seeds state (no flood)."""
    sales, _ = await self.market.recent_sales(25, cache_ttl=0)
    ids = [s.id for s in sales]
    if not state.get("sales_initialized", False):
      state.mark_seen(ids)
      state.set("sales_initialized", True)
      log.info("seeded sales state with %d existing sales", len(ids))
      return []
    unseen = set(state.filter_unseen(ids))
    state.mark_seen(ids)
    cutoff = self.clock() - timedelta(hours=24)
    new = sorted(
      (s for s in sales if s.id in unseen and s.created_at >= cutoff), key=lambda s: s.created_at
    )
    cap = self.settings.sales_alert_max_per_cycle
    if len(new) > cap:
      log.warning("%d new sales this cycle; posting the latest %d", len(new), cap)
      new = new[-cap:]
    return new

  async def poll_floor(self, state: State) -> FloorAlert | None:
    stats = await self.market.stats(cache_ttl=0)
    now = self.clock().timestamp()
    base = state.get("floor_baseline")
    if not base:
      state.set("floor_baseline", {"floor": stats.floor, "ts": now})
      return None
    old = float(base["floor"])
    if old <= 0:
      state.set("floor_baseline", {"floor": stats.floor, "ts": now})
      return None
    pct = (stats.floor - old) / old * 100
    s = self.settings
    if abs(pct) < s.floor_alert_pct or abs(stats.floor - old) < s.floor_alert_min_doge:
      return None
    last = float(state.get("floor_last_alert_ts", 0) or 0)
    if now - last < s.floor_alert_cooldown_seconds:
      return None
    state.set("floor_baseline", {"floor": stats.floor, "ts": now})
    state.set("floor_last_alert_ts", now)
    return FloorAlert(old=old, new=stats.floor, pct=pct, listed=stats.listed)


def _value_at(series: list[tuple[datetime, float]], when: datetime) -> float | None:
  """Last value at or before `when` (series sorted ascending)."""
  best = None
  for ts, v in series:
    if ts <= when:
      best = v
    else:
      break
  return best
