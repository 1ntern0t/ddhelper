from datetime import UTC, datetime

import pytest

from ddhelper.sources.xapi import Post, XClient, XUnavailable, parse_posts, parse_users

from .conftest import load


def test_parse_users_recorded():
  ids = parse_users(load("x_users_by.json"))
  assert ids == {
    "doginaldogs": "1659130914746806272",
    "barkmeta": "336348053",
    "ddltcg": "1864480184067653632",
    "ddsalesbot": "1884363006395420672",
  }


def test_parse_posts_recorded():
  posts = parse_posts(load("x_tweets_barkmeta.json"), "barkmeta")
  assert len(posts) == 8
  assert posts == sorted(posts, key=lambda p: p.created_at, reverse=True)
  space_post = next(p for p in posts if p.id == "2113375044239831329")
  assert space_post.link_only  # the daily 5 PM Space link post is just a t.co link
  assert space_post.url == "https://x.com/barkmeta/status/2113375044239831329"
  assert parse_posts(load("x_tweets_DDLTCG.json"), "DDLTCG") == []


def test_unwound_urls_and_space_detection():
  sb = parse_posts(load("x_tweets_DDSalesBot.json"), "DDSalesBot")
  assert sb[0].urls[0].startswith("https://market.doginaldogs.com/inscription/")
  p = Post(
    "1",
    "barkmeta",
    datetime.now(UTC),
    "join https://t.co/x",
    urls=("https://x.com/i/spaces/1MJgNbBPelOGL",),
  )
  assert p.space_urls == ["https://x.com/i/spaces/1MJgNbBPelOGL"]


async def test_no_token_raises(fetcher):
  x = XClient(fetcher, None)
  assert not x.available
  with pytest.raises(XUnavailable, match="X_BEARER_TOKEN"):
    await x.user_ids(["doginaldogs"])
  assert fetcher.calls == []


async def test_requests_carry_bearer_and_params(fetcher):
  x = XClient(fetcher, "tkn")
  ids = await x.user_ids(["doginaldogs", "DDLTCG"])
  assert ids["DDLTCG"] == "1864480184067653632"
  await x.user_ids(["doginaldogs"])  # cached: no second lookup
  assert sum(1 for c in fetcher.calls if c[0].endswith("/users/by")) == 1
  await x.recent_posts("doginaldogs", ids["doginaldogs"], datetime(2026, 10, 22, 16, tzinfo=UTC), 1)
  url, params, headers = fetcher.calls[-1]
  assert url == "https://api.x.com/2/users/1659130914746806272/tweets"
  assert headers["Authorization"] == "Bearer tkn"
  assert params["start_time"] == "2026-10-22T16:00:00Z"
  assert params["max_results"] == "5"  # API minimum
  assert params["exclude"] == "retweets,replies"
