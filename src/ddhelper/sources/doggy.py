"""Doggy Market public API (third-party, secondary venue). Prices are in koinu (1e-8 DOGE)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ..http import Fetcher, SourceError
from ._util import parse_iso

KOINU = 100_000_000


@dataclass(frozen=True)
class DoggyStats:
  floor: float
  listed: int
  owners: int | None
  volume_24h: float
  volume_7d: float
  trades_24h: int
  trades_7d: int
  trades_30d: int
  newest_listing_at: datetime | None
  fetched_at: datetime


def parse_doggy(d: Any, fetched_at: datetime | None = None) -> DoggyStats:
  if not isinstance(d, dict):
    raise SourceError("doggy.market: unexpected response shape")
  try:
    listed_times = [parse_iso(x.get("listedAt")) for x in d.get("recentlyListed") or []]
    listed_times = [t for t in listed_times if t]
    return DoggyStats(
      floor=int(d["floorPrice"]) / KOINU,
      listed=int(d["listed"]),
      owners=int(d["owners"]) if d.get("owners") is not None else None,
      volume_24h=int(d.get("volume24h") or 0) / KOINU,
      volume_7d=int(d.get("volume7d") or 0) / KOINU,
      trades_24h=int(d.get("trades24h") or 0),
      trades_7d=int(d.get("trades7d") or 0),
      trades_30d=int(d.get("trades30d") or 0),
      newest_listing_at=max(listed_times) if listed_times else None,
      fetched_at=fetched_at or datetime.now(UTC),
    )
  except (KeyError, TypeError, ValueError) as e:
    raise SourceError("doggy.market: missing fields") from e


def staleness_warnings(doggy: DoggyStats, official_floor: float | None, now: datetime) -> list[str]:
  """Heuristics for when the Doggy Market numbers should not be trusted."""
  out = []
  if official_floor and official_floor > 0:
    diff = (doggy.floor - official_floor) / official_floor * 100
    if abs(diff) >= 25:
      out.append(
        f"Doggy Market floor is {diff:+.0f}% vs the official market; its listings may be stale or no longer valid."
      )
  if doggy.trades_7d == 0:
    out.append("No Doggy Market trades in the last 7 days.")
  elif doggy.trades_24h == 0 and doggy.trades_7d <= 2:
    out.append(
      f"Thin activity on Doggy Market ({doggy.trades_7d} trade{'s' if doggy.trades_7d != 1 else ''} in 7d)."
    )
  if doggy.newest_listing_at and (now - doggy.newest_listing_at).days >= 7:
    out.append(f"Newest Doggy Market listing is {(now - doggy.newest_listing_at).days} days old.")
  return out


class DoggyMarket:
  name = "doggy.market"

  def __init__(self, fetcher: Fetcher, url: str = "https://api.doggy.market/nfts/doginaldogs"):
    self._f = fetcher
    self._url = url

  async def stats(self, cache_ttl: float = 120) -> DoggyStats:
    r = await self._f.get_json(self._url, cache_ttl=cache_ttl)
    return parse_doggy(r.data, datetime.fromtimestamp(r.fetched_at, UTC))
