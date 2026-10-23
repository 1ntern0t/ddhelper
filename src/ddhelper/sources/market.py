"""Official marketplace (market.doginaldogs.com).

UNOFFICIAL ACCESS: the site's frontend loads its data from tRPC procedures under
/api/trpc/*. These are undocumented internal endpoints, not a published API; they can
change or disappear at any time. Ask the Doginal Dogs team before relying on them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..http import Fetcher, SourceError
from ._util import parse_iso

_DOG_RE = re.compile(r"#\s*(\d{1,5})")


@dataclass(frozen=True)
class MarketStats:
  floor: float
  floor_change_pct: float | None  # period not labelled by the API
  listed: int
  supply: int
  volume_30d: float
  trades_30d: int
  avg_sale_30d: float
  total_volume: float
  fetched_at: datetime


@dataclass(frozen=True)
class Sale:
  id: int
  name: str
  dog_number: int | None
  price_doge: float
  txid: str | None
  is_manual: bool
  otc: bool
  created_at: datetime
  inscription_id: str
  source: str

  @property
  def has_tx(self) -> bool:
    return bool(self.txid)

  @property
  def market_url(self) -> str:
    return f"https://market.doginaldogs.com/inscription/{self.inscription_id}"


def _unwrap(payload: Any, proc: str) -> Any:
  """Unwrap a batched tRPC (superjson) response: [{"result": {"data": {"json": ...}}}]."""
  try:
    item = payload[0]
  except (IndexError, KeyError, TypeError) as e:
    raise SourceError(f"market {proc}: unexpected response shape") from e
  if "error" in item:
    msg = item["error"].get("json", {}).get("message", "error") if isinstance(item["error"], dict) else "error"
    raise SourceError(f"market {proc}: {msg}")
  try:
    return item["result"]["data"]["json"]
  except (KeyError, TypeError) as e:
    raise SourceError(f"market {proc}: unexpected response shape") from e


def parse_stats(payload: Any, fetched_at: datetime | None = None) -> MarketStats:
  d = _unwrap(payload, "listings.getStats")
  try:
    return MarketStats(
      floor=float(d["floorPrice"]),
      floor_change_pct=float(d["floorPriceChange"]) if d.get("floorPriceChange") is not None else None,
      listed=int(d["listed"]),
      supply=int(d.get("supply") or 10000),
      volume_30d=float(d.get("volume30d") or 0),
      trades_30d=int(d.get("trades30d") or 0),
      avg_sale_30d=float(d.get("avgSalePrice30d") or 0),
      total_volume=float(d.get("totalVolume") or 0),
      fetched_at=fetched_at or datetime.now(UTC),
    )
  except (KeyError, TypeError, ValueError) as e:
    raise SourceError("market listings.getStats: missing fields") from e


def parse_sale(a: dict[str, Any]) -> Sale | None:
  if a.get("activityType") != "sale":
    return None
  # createdAt = time of the sale; confirmedAt can lag (on-chain confirmation).
  created = parse_iso(a.get("createdAt")) or parse_iso(a.get("confirmedAt"))
  try:
    price = float(a["priceDoge"])
    sale_id = int(a["id"])
  except (KeyError, TypeError, ValueError):
    return None
  if created is None:
    return None
  name = str(a.get("dogName") or "Doginal Dog")
  m = _DOG_RE.search(name)
  txid = a.get("txid") or None
  if txid is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(txid)):
    txid = None
  return Sale(
    id=sale_id,
    name=name,
    dog_number=int(m.group(1)) if m else None,
    price_doge=price,
    txid=txid,
    is_manual=bool(a.get("isManual")),
    otc=bool(a.get("otc")),
    created_at=created,
    inscription_id=str(a.get("inscriptionId") or ""),
    source=str(a.get("source") or ""),
  )


def parse_activity(payload: Any) -> tuple[list[Sale], int | None]:
  d = _unwrap(payload, "activity.getGlobal")
  sales = [s for s in (parse_sale(a) for a in d.get("activities") or []) if s is not None]
  cursor = d.get("nextCursor")
  return sales, int(cursor) if isinstance(cursor, int) else None


def parse_floor_history(payload: Any) -> list[tuple[datetime, float]]:
  d = _unwrap(payload, "listings.getHistoricalFloorPrice")
  out = []
  for p in d.get("data") or []:
    try:
      out.append((datetime.fromtimestamp(p["timestamp"] / 1000, UTC), float(p["price"])))
    except (KeyError, TypeError, ValueError):
      continue
  return sorted(out)


class OfficialMarket:
  name = "market.doginaldogs.com"

  def __init__(self, fetcher: Fetcher, base_url: str = "https://market.doginaldogs.com"):
    self._f = fetcher
    self._base = base_url.rstrip("/") + "/api/trpc/"

  async def _call(self, proc: str, inp: Any, cache_ttl: float) -> tuple[Any, datetime]:
    params = {"batch": "1", "input": json.dumps({"0": {"json": inp}}, separators=(",", ":"))}
    r = await self._f.get_json(self._base + proc, params=params, cache_ttl=cache_ttl)
    return r.data, datetime.fromtimestamp(r.fetched_at, UTC)

  async def stats(self, cache_ttl: float = 60) -> MarketStats:
    data, ts = await self._call("listings.getStats", None, cache_ttl)
    return parse_stats(data, ts)

  async def recent_sales(self, limit: int = 50, cursor: int | None = None, cache_ttl: float = 60) -> tuple[list[Sale], int | None]:
    inp: dict[str, Any] = {"limit": max(1, min(limit, 50))}
    if cursor is not None:
      inp["cursor"] = cursor
    data, _ = await self._call("activity.getGlobal", inp, cache_ttl)
    return parse_activity(data)

  async def sales_since(self, since: datetime, max_pages: int = 4, cache_ttl: float = 60) -> list[Sale]:
    """All sales newer than `since`, paging until older data or `max_pages`."""
    out: list[Sale] = []
    cursor: int | None = None
    for _ in range(max_pages):
      page, cursor = await self.recent_sales(50, cursor, cache_ttl)
      out.extend(s for s in page if s.created_at >= since)
      if not page or cursor is None or min(s.created_at for s in page) < since:
        break
    return out

  async def floor_history(self, time_range: str = "7d", cache_ttl: float = 300) -> list[tuple[datetime, float]]:
    if time_range not in ("24h", "7d", "30d", "all"):
      raise ValueError("time_range must be one of 24h, 7d, 30d, all")
    data, _ = await self._call("listings.getHistoricalFloorPrice", {"timeRange": time_range}, cache_ttl)
    return parse_floor_history(data)


def volume_window(sales: list[Sale], now: datetime, window: timedelta) -> tuple[float, int, int]:
  """(total DOGE, count, count_without_txid) for sales within `window` before `now`."""
  sel = [s for s in sales if now - window <= s.created_at <= now]
  return sum(s.price_doge for s in sel), len(sel), sum(1 for s in sel if not s.has_tx)
