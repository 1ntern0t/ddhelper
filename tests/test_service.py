import copy
from datetime import timedelta
from pathlib import Path

from ddhelper.events import load_events
from ddhelper.render import Renderer
from ddhelper.service import Helper
from ddhelper.state import State

from .conftest import RECORDED_AT, FixtureFetcher, load

EVENTS = load_events(Path(__file__).parents[1] / "config" / "events.toml")


async def test_floor_report_recorded(settings, fetcher, clock):
  rep = await Helper(settings, fetcher, clock=clock).floor_report()
  assert rep.stats.floor == 47000
  assert (rep.vol_24h.count, rep.vol_24h.doge) == (1, 56500)
  assert (rep.vol_7d.count, round(rep.vol_7d.doge), rep.vol_7d.without_tx) == (14, 1230914, 10)
  assert rep.doggy.floor == 23669
  assert rep.doggy_warnings


async def test_floor_report_degrades_when_doggy_down(settings, clock):
  f = FixtureFetcher(fail={"doggy_collection.json"})
  rep = await Helper(settings, f, clock=clock).floor_report()
  assert rep.stats is not None and rep.doggy is None
  assert "simulated outage" in rep.doggy_error
  text = Renderer(settings.tz).floor(rep)
  assert "Doggy Market (secondary): unavailable" in text


async def test_floor_report_official_down(settings, clock):
  f = FixtureFetcher(fail={"market_stats.json", "market_activity_page1.json"})
  rep = await Helper(settings, f, clock=clock).floor_report()
  assert rep.stats is None and rep.official_error and rep.sales_error
  assert rep.doggy is not None  # still have the secondary venue
  assert "Official stats unavailable" in Renderer(settings.tz).floor(rep)


async def test_digest_without_x_token_notes_gap(settings, fetcher, clock):
  d = await Helper(settings, fetcher, events=EVENTS, clock=clock).digest()
  assert d.posts == {}
  assert any("X_BEARER_TOKEN" in g for g in d.gaps)
  assert not any("api.x.com" in c[0] for c in fetcher.calls)
  assert d.events[0].name == "DDMIAMI 2026"
  assert d.floor_24h_ago == 47000
  text = Renderer(settings.tz).digest(d)
  assert "X posts not included" in text
  assert "DDMIAMI 2026: Dec 7–9, 2026 (in 45 days)" in text


async def test_digest_with_recorded_x(settings_x, fetcher, clock):
  d = await Helper(settings_x, fetcher, events=EVENTS, clock=clock).digest()
  assert d.gaps == []
  assert d.sales_bot_posts == 1  # only #7001 in the last 24h, matching the market feed
  assert [p.id for p in d.posts["doginaldogs"]] == ["2113419853457764693"]
  assert d.posts["DDLTCG"] == []
  bark = d.posts["barkmeta"]
  # barkmeta is keyword-filtered: AI/crypto commentary is dropped, Space link post kept
  assert "2113375044239831329" in [p.id for p in bark]
  assert "2113646306967077190" not in [p.id for p in bark]
  assert all(
    p.created_at >= RECORDED_AT - timedelta(hours=24) for ps in d.posts.values() for p in ps
  )
  text = Renderer(settings_x.tz).digest(d)
  assert "@DDLTCG: no new original posts" in text
  assert "@DDSalesBot posted 1 sale update." in text
  assert "<https://x.com/doginaldogs/status/2113419853457764693>" in text
  assert "Gaps" not in text


async def test_digest_x_partial_failure(settings_x, clock):
  f = FixtureFetcher(fail={"x_tweets_barkmeta.json"})
  d = await Helper(settings_x, f, clock=clock).digest()
  assert "barkmeta" not in d.posts and "doginaldogs" in d.posts
  assert any("@barkmeta" in g for g in d.gaps)


async def test_sales_poll_seeds_then_dedupes(settings, clock):
  page = load("market_activity_page1.json")
  without_newest = copy.deepcopy(page)
  without_newest[0]["result"]["data"]["json"]["activities"].pop(0)
  current = {"market_activity_page1.json": without_newest}
  f = FixtureFetcher(
    overrides={"market_activity_page1.json": lambda: current["market_activity_page1.json"]}
  )
  helper = Helper(settings, f, clock=clock)
  st = State(":memory:")
  assert await helper.poll_new_sales(st) == []  # first run seeds, never floods
  assert await helper.poll_new_sales(st) == []  # nothing new
  current["market_activity_page1.json"] = page  # sale #7001 (id 1443) appears
  new = await helper.poll_new_sales(st)
  assert [s.id for s in new] == [1443]
  assert await helper.poll_new_sales(st) == []  # deduped


async def test_sales_poll_ignores_old_backfill(settings, clock):
  page = load("market_activity_page1.json")
  acts = page[0]["result"]["data"]["json"]["activities"]
  without_old = copy.deepcopy(page)
  without_old[0]["result"]["data"]["json"]["activities"] = acts[:1] + acts[2:]
  current = {"p": without_old}
  f = FixtureFetcher(overrides={"market_activity_page1.json": lambda: current["p"]})
  helper = Helper(settings, f, clock=clock)
  st = State(":memory:")
  await helper.poll_new_sales(st)
  current["p"] = page  # id 1442 (#99, 26h old) shows up late: no alert, but marked seen
  assert await helper.poll_new_sales(st) == []
  assert st.filter_unseen([1442]) == []


def _stats_with_floor(floor):
  s = load("market_stats.json")
  s[0]["result"]["data"]["json"]["floorPrice"] = floor
  return s


async def test_floor_alert_threshold_and_cooldown(settings):
  now = {"t": RECORDED_AT}
  floor = {"v": 47000}
  f = FixtureFetcher(overrides={"market_stats.json": lambda: _stats_with_floor(floor["v"])})
  helper = Helper(settings, f, clock=lambda: now["t"])
  st = State(":memory:")
  assert await helper.poll_floor(st) is None  # baseline
  floor["v"] = 50000  # +6.4%: below 10% default
  assert await helper.poll_floor(st) is None
  floor["v"] = 52000  # +10.6% vs baseline
  a = await helper.poll_floor(st)
  assert a and a.old == 47000 and a.new == 52000 and round(a.pct, 1) == 10.6
  floor["v"] = 40000  # -23% but inside cooldown
  now["t"] += timedelta(minutes=30)
  assert await helper.poll_floor(st) is None
  now["t"] += timedelta(hours=1)
  a = await helper.poll_floor(st)
  assert a and a.old == 52000 and a.new == 40000


async def test_floor_alert_min_doge(settings):
  from ddhelper.config import Settings

  s = Settings.from_env({"FLOOR_ALERT_PCT": "1", "FLOOR_ALERT_MIN_DOGE": "5000"})
  floor = {"v": 47000}
  f = FixtureFetcher(overrides={"market_stats.json": lambda: _stats_with_floor(floor["v"])})
  helper = Helper(s, f, clock=lambda: RECORDED_AT)
  st = State(":memory:")
  await helper.poll_floor(st)
  floor["v"] = 50000  # +6.4% but only 3,000 DOGE
  assert await helper.poll_floor(st) is None


async def test_recent_sales_clamps(settings, fetcher, clock):
  h = Helper(settings, fetcher, clock=clock)
  assert len(await h.recent_sales(0)) == 1
  assert len(await h.recent_sales(999)) == 25
