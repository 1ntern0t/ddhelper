from datetime import timedelta

import pytest

from ddhelper.http import SourceError
from ddhelper.sources.doggy import parse_doggy, staleness_warnings

from .conftest import RECORDED_AT, load


def test_parse_doggy_recorded_koinu_conversion():
  d = parse_doggy(load("doggy_collection.json"))
  assert d.floor == 23669
  assert d.listed == 44
  assert d.owners == 4955
  assert d.trades_7d == 1 and d.volume_7d == 22000
  assert d.trades_24h == 0


def test_staleness_warnings_recorded():
  d = parse_doggy(load("doggy_collection.json"))
  w = staleness_warnings(d, 47000, RECORDED_AT)
  assert any("-50%" in x for x in w)
  assert any("Thin activity" in x for x in w)


def test_no_warning_when_close_to_official():
  d = parse_doggy(load("doggy_collection.json"))
  w = staleness_warnings(d, d.floor * 1.05, d.newest_listing_at + timedelta(days=1))
  assert not any("vs the official" in x for x in w)


def test_bad_shape():
  with pytest.raises(SourceError):
    parse_doggy([])
  with pytest.raises(SourceError):
    parse_doggy({"listed": 1})
