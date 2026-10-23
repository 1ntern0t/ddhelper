import json

import pytest

from ddhelper.http import SourceError
from ddhelper.sources.cards import (
  LocalJsonCardSource,
  OfficialCardSource,
  parse_cards,
  search,
  validate_query,
)

from .conftest import FIXTURES, load


@pytest.fixture
def cards():
  return parse_cards(load("ddl_cards_subset.json"))


def test_parse_recorded(cards):
  assert len(cards) == 8
  renza = next(c for c in cards if c.serial == "V052")
  assert renza.name == "Renza"
  assert renza.image_url == "https://ddltcg.com/card_renders/v2/V052.png"
  assert renza.mana == 7


@pytest.mark.parametrize(
  ("q", "expected"),
  [
    ("renza", "V052"),
    ("RENZA", "V052"),
    ("V52", "V052"),
    ("v052", "V052"),
    ("tidal", "V111"),
    ("Tidal  Wave", "V111"),
    ("gumy", "V057"),  # fuzzy
  ],
)
def test_search(cards, q, expected):
  assert search(cards, q)[0].serial == expected


def test_search_no_match(cards):
  assert search(cards, "zzzzzz") == []


@pytest.mark.parametrize("bad", ["", " ", "<@everyone>", "a" * 41, "x;rm -rf", "'quote"])
def test_validate_rejects(bad):
  with pytest.raises(ValueError):
    validate_query(bad)


def test_sealed_cards_hidden():
  data = load("ddl_cards_subset.json")
  data[0]["sealed"] = True
  assert data[0]["id"] not in {c.serial for c in parse_cards(data)}


async def test_local_source(tmp_path):
  p = tmp_path / "cards.json"
  p.write_text(json.dumps({"cards": load("ddl_cards_subset.json")}))
  src = LocalJsonCardSource(p)
  assert len(await src.all_cards()) == 8
  with pytest.raises(SourceError):
    await LocalJsonCardSource(tmp_path / "missing.json").all_cards()


async def test_official_source(fetcher):
  src = OfficialCardSource(fetcher)
  cards = await src.all_cards()
  assert {c.serial for c in cards} == {
    c["id"] for c in json.loads((FIXTURES / "ddl_cards_subset.json").read_text())
  }
  assert fetcher.calls[0][0] == "https://ddltcg.com/data/cards.json"
