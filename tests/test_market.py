from datetime import UTC, datetime, timedelta

import pytest

from ddhelper.http import SourceError
from ddhelper.sources.market import (
  OfficialMarket,
  parse_activity,
  parse_floor_history,
  parse_sale,
  parse_stats,
  volume_window,
)

from .conftest import RECORDED_AT, load


def test_parse_stats_recorded():
  s = parse_stats(load("market_stats.json"))
  assert s.floor == 47000
  assert s.listed == 267
  assert s.supply == 10000
  assert s.trades_30d == 30
  assert s.volume_30d == 2094864


def test_parse_activity_recorded():
  sales, cursor = parse_activity(load("market_activity_page1.json"))
  # 50 rows recorded; id 1377 (Aug 30) has priceDoge null upstream and is skipped
  # rather than shown with an invented price.
  assert len(sales) == 49
  assert 1377 not in {s.id for s in sales}
  assert cursor == 1371
  first = sales[0]
  assert first.id == 1443
  assert first.dog_number == 7001
  assert first.price_doge == 56500
  assert first.txid is None and first.is_manual
  assert first.created_at == datetime(2026, 10, 22, 21, 17, 2, 408000, tzinfo=UTC)
  with_tx = [s for s in sales if s.has_tx]
  assert len(with_tx) == 5
  assert all(len(s.txid) == 64 for s in with_tx)


def test_sale_time_uses_created_not_confirmed():
  sales, _ = parse_activity(load("market_activity_page1.json"))
  s1968 = next(s for s in sales if s.dog_number == 1968)
  # createdAt 17:43Z; confirmedAt (on-chain) was an hour later
  assert s1968.created_at == datetime(2026, 10, 21, 17, 43, 15, 559000, tzinfo=UTC)


def test_volume_window_matches_report():
  # The Oct 23 report counted 14 sales / 1,230,914 DOGE for Oct 16-23 from the same feed.
  sales, _ = parse_activity(load("market_activity_page1.json"))
  total, count, no_tx = volume_window(sales, RECORDED_AT, timedelta(days=7))
  assert (count, round(total)) == (14, 1230914)
  assert no_tx == 10
  total24, count24, _ = volume_window(sales, RECORDED_AT, timedelta(hours=24))
  assert (count24, total24) == (1, 56500)


def test_parse_sale_rejects_bad_rows():
  assert parse_sale({"activityType": "listing"}) is None
  assert (
    parse_sale(
      {"activityType": "sale", "id": 1, "priceDoge": "x", "createdAt": "2026-10-22T00:00:00Z"}
    )
    is None
  )
  row = {
    "activityType": "sale",
    "id": 2,
    "priceDoge": "1",
    "createdAt": "2026-10-22T00:00:00Z",
    "txid": "not-hex",
  }
  assert parse_sale(row).txid is None


def test_trpc_error_raises():
  with pytest.raises(SourceError, match="boom"):
    parse_stats([{"error": {"json": {"message": "boom"}}}])
  with pytest.raises(SourceError):
    parse_stats({"unexpected": True})


def test_floor_history_sorted():
  h = parse_floor_history(load("market_floor_7d.json"))
  assert len(h) == 7
  assert h == sorted(h)
  assert min(v for _, v in h) == 45000


async def test_sales_since_pages_until_window(fetcher):
  m = OfficialMarket(fetcher)
  recent = await m.sales_since(RECORDED_AT - timedelta(days=7))
  assert len(recent) == 14
  assert (
    sum(1 for c in fetcher.calls if "activity.getGlobal" in c[0]) == 1
  )  # page 1 already covers 7d
  older = await m.sales_since(datetime(2026, 8, 15, tzinfo=UTC))
  assert sum(1 for c in fetcher.calls if "activity.getGlobal" in c[0]) == 3  # needed page 2
  assert all(s.created_at >= datetime(2026, 8, 15, tzinfo=UTC) for s in older)
  assert len(older) > 50


async def test_trpc_request_shape(fetcher):
  await OfficialMarket(fetcher).recent_sales(10, cursor=99)
  url, params, _ = fetcher.calls[-1]
  assert url == "https://market.doginaldogs.com/api/trpc/activity.getGlobal"
  assert params == {"batch": "1", "input": '{"0":{"json":{"limit":10,"cursor":99}}}'}


async def test_floor_history_validates_range(fetcher):
  with pytest.raises(ValueError):
    await OfficialMarket(fetcher).floor_history("1y")
