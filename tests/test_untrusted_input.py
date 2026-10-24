"""Malformed or hostile upstream responses must degrade to SourceError / skipped rows,
never to an unexpected exception (which would kill a background loop)."""

import pytest

from ddhelper.http import SourceError
from ddhelper.sources import cards, doggy, market, xapi
from ddhelper.sources._util import finite_float, parse_iso

INSC = "9ba2f246beb9b42ffebde8cbaad266f297878587b2ee24eaaf1903b0fba989d9i0"
TS = "2026-10-22T21:17:02.408Z"


def wrap(j):
  return [{"result": {"data": {"json": j}}}]


def sale(**kw):
  return {"activityType": "sale", "id": 1, "priceDoge": "100", "createdAt": TS, **kw}


def test_parse_iso_rejects_non_strings():
  assert parse_iso(5) is None
  assert parse_iso(["x"]) is None
  assert parse_iso(TS) is not None


@pytest.mark.parametrize("v", ["nan", "inf", "-Infinity", float("nan"), True])
def test_finite_float_rejects(v):
  with pytest.raises((TypeError, ValueError)):
    finite_float(v)


@pytest.mark.parametrize("payload", [[None], [5], ["error"], {}, [], None, "x"])
def test_market_unwrap_bad_envelope(payload):
  with pytest.raises(SourceError):
    market.parse_activity(payload)


@pytest.mark.parametrize("inner", [[1], "x", 5, {"activities": 5}, {"activities": "abc"}])
def test_market_activity_bad_shapes(inner):
  with pytest.raises(SourceError):
    market.parse_activity(wrap(inner))


def test_market_activity_skips_bad_rows():
  rows = [
    1,
    None,
    "sale",
    sale(createdAt=5),
    sale(priceDoge="inf"),
    sale(priceDoge="NaN"),
    sale(id=float("inf")),
    sale(id=2**70),
    sale(id=7, inscriptionId=INSC),
  ]
  sales, _ = market.parse_activity(wrap({"activities": rows}))
  assert [s.id for s in sales] == [7]
  assert sales[0].market_url.endswith(INSC)


def test_market_inscription_id_cannot_break_out_of_link():
  s = market.parse_sale(sale(inscriptionId="x> [phish](https://evil.example)"))
  assert s is not None and s.inscription_id == ""
  assert s.market_url == "https://market.doginaldogs.com/"


def test_market_error_message_is_single_line_and_bounded():
  payload = [{"error": {"json": {"message": "a\nb\r\n" + "x" * 1000}}}]
  with pytest.raises(SourceError) as ei:
    market.parse_stats(payload)
  msg = str(ei.value)
  assert "\n" not in msg and "\r" not in msg
  assert len(msg) < 260


def test_market_error_odd_shapes():
  for err in ({"json": "boom"}, "boom", None, {"json": {"message": 5}}):
    with pytest.raises(SourceError):
      market.parse_stats([{"error": err}])


@pytest.mark.parametrize(
  "d", [[1], {"floorPrice": "NaN", "listed": 1}, {"floorPrice": 1, "listed": float("inf")}]
)
def test_market_stats_bad_values(d):
  with pytest.raises(SourceError):
    market.parse_stats(wrap(d))


def test_market_floor_history_bad_rows():
  with pytest.raises(SourceError):
    market.parse_floor_history(wrap({"data": 5}))
  rows = [
    1,
    {"timestamp": 1e30, "price": 1},
    {"timestamp": "x", "price": 1},
    {"timestamp": 1761000000000, "price": "inf"},
    {"timestamp": 1761000000000, "price": 5},
  ]
  assert [p for _, p in market.parse_floor_history(wrap({"data": rows}))] == [5.0]


@pytest.mark.parametrize(
  "d",
  [
    {"floorPrice": "inf", "listed": 1},
    {"floorPrice": 1, "listed": float("inf")},
    {"floorPrice": 1, "listed": 1, "recentlyListed": 5},
  ],
)
def test_doggy_bad_values(d):
  with pytest.raises(SourceError):
    doggy.parse_doggy(d)


def test_doggy_skips_non_dict_listings():
  st = doggy.parse_doggy({"floorPrice": 100, "listed": 1, "recentlyListed": [1, {"listedAt": TS}]})
  assert st.newest_listing_at is not None


def test_x_users_rejects_bad_rows_and_path_ids():
  data = [
    1,
    {"id": "../../oauth2/token", "username": "evil"},
    {"id": 5, "username": "num"},
    {"id": "123", "username": 5},
    {"id": "336348053", "username": "barkmeta"},
  ]
  assert xapi.parse_users({"data": data}) == {"barkmeta": "336348053"}
  with pytest.raises(xapi.XUnavailable):
    xapi.parse_users({"data": "x"})


def test_x_posts_tolerates_bad_fields():
  data = [
    1,
    {"id": "1> [x](https://e.example)", "created_at": TS},
    {
      "id": "42",
      "created_at": TS,
      "public_metrics": {"like_count": "x", "impression_count": float("inf")},
      "entities": {"urls": [1, {"expanded_url": "https://a.example"}]},
      "referenced_tweets": [1, {"type": "quoted"}],
    },
    {"id": "43", "created_at": TS, "public_metrics": 5, "entities": 5, "referenced_tweets": 5},
  ]
  posts = xapi.parse_posts({"data": data}, "a")
  assert sorted(p.id for p in posts) == ["42", "43"]
  p42 = next(p for p in posts if p.id == "42")
  assert (p42.likes, p42.views, p42.urls, p42.is_quote) == (0, 0, ("https://a.example",), True)
  with pytest.raises(xapi.XUnavailable):
    xapi.parse_posts({"data": 5}, "a")


def test_cards_unsafe_image_url_and_bad_keywords():
  rows = [
    {"id": "V001", "name": "A", "image_url": "javascript:x> [a](b)", "keywords": 5},
    {"id": "X9", "name": "B", "image_url": "http://plain.example/b.png"},
    {"id": "X10", "name": "C", "image_url": "https://ddltcg.com/c.png", "keywords": ["Taunt"]},
  ]
  a, b, c = cards.parse_cards(rows)
  assert a.image_url == "https://ddltcg.com/card_renders/v2/V001.png"
  assert a.keywords == ()
  assert b.image_url is None
  assert c.image_url == "https://ddltcg.com/c.png" and c.keywords == ("Taunt",)
