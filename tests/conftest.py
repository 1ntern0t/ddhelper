"""Shared fixtures. All upstream data comes from real responses recorded on
2026-10-23 (~11:56 AM ET) into tests/fixtures/; see tests/fixtures/README.md."""

from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest

from ddhelper.config import Settings
from ddhelper.http import JsonResponse, SourceError

FIXTURES = Path(__file__).parent / "fixtures"
# Shortly after the fixtures were recorded.
RECORDED_AT = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)

X_IDS = {
  "1659130914746806272": "doginaldogs",
  "336348053": "barkmeta",
  "1864480184067653632": "DDLTCG",
  "1884363006395420672": "DDSalesBot",
}


def load(name: str) -> Any:
  return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FixtureFetcher:
  """Implements the Fetcher protocol by routing URLs to recorded fixture files."""

  def __init__(self, overrides: Mapping[str, Any] | None = None, fail: set[str] | None = None):
    self.calls: list[tuple[str, dict[str, str], dict[str, str]]] = []
    self.overrides = dict(overrides or {})
    self.fail = set(fail or ())

  def route(self, url: str, params: Mapping[str, str]) -> str:
    parts = urlsplit(url)
    path = parts.path
    if parts.netloc == "market.doginaldogs.com":
      proc = path.rsplit("/", 1)[-1]
      if proc == "listings.getStats":
        return "market_stats.json"
      if proc == "activity.getGlobal":
        inp = json.loads(params["input"])["0"]["json"]
        return "market_activity_page2.json" if inp.get("cursor") else "market_activity_page1.json"
      if proc == "listings.getHistoricalFloorPrice":
        return "market_floor_7d.json"
    if parts.netloc == "api.doggy.market":
      return "doggy_collection.json"
    if parts.netloc == "ddltcg.com" and path == "/data/cards.json":
      return "ddl_cards_subset.json"
    if parts.netloc == "api.x.com":
      if path == "/2/users/by":
        return "x_users_by.json"
      if path.endswith("/tweets"):
        return f"x_tweets_{X_IDS[path.split('/')[3]]}.json"
    raise AssertionError(f"no fixture for {url}")

  async def get_json(self, url, *, params=None, headers=None, cache_ttl=0) -> JsonResponse:
    params = dict(params or {})
    self.calls.append((url, params, dict(headers or {})))
    name = self.route(url, params)
    if name in self.fail:
      raise SourceError(f"simulated outage for {name}")
    data = self.overrides[name] if name in self.overrides else load(name)
    if callable(data):
      data = data()
    return JsonResponse(copy.deepcopy(data), 200, {}, time.time())


@pytest.fixture
def fetcher() -> FixtureFetcher:
  return FixtureFetcher()


@pytest.fixture
def clock() -> Callable[[], datetime]:
  return lambda: RECORDED_AT


@pytest.fixture
def settings() -> Settings:
  return Settings.from_env({"DDHELPER_DB": ":memory:"})


@pytest.fixture
def settings_x() -> Settings:
  return Settings.from_env({"X_BEARER_TOKEN": "test-token-not-real", "DDHELPER_DB": ":memory:"})
