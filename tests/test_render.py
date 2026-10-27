import time
from dataclasses import replace
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from ddhelper.render import (
  _TCO_RE,
  STALE_FLOOR_NOTE,
  Renderer,
  chunk,
  doge,
  link,
  sanitize,
  untrusted,
)
from ddhelper.service import DigestData, FloorReport
from ddhelper.sources.market import Sale, parse_activity, parse_stats
from ddhelper.sources.xapi import Post
from ddhelper.state import State

from .conftest import load

R = Renderer(ZoneInfo("America/New_York"))


def test_doge_format():
  assert doge(47000) == "47,000 DOGE"
  assert doge(69828.8) == "69,828.80 DOGE"


def test_sanitize_mentions():
  s = sanitize("hey @everyone and @here <@123> <@&9> <#5>")
  assert "@everyone" not in s and "@here" not in s
  assert "<@" not in s and "<#" not in s


def test_sales_flags_manual_and_links_tx():
  sales, _ = parse_activity(load("market_activity_page1.json"))
  text = R.sales(sales[:5])
  assert "**#7001** · 56,500 DOGE · Thu Oct 22, 5:17 PM ET" in text
  assert text.count("no tx id (manually recorded sale)") == 3
  assert (
    "https://blockchair.com/dogecoin/transaction/74b50620bd3b39b90b1d63f5503f116c3df026fd203a9d2c7ecfff4b681cf2fb"
    in text
  )
  assert "3 of 5 have no on-chain tx id" in text
  assert "D" + "NCgRn4Wi" not in text  # wallet addresses are never shown


def test_chunk_respects_limit():
  text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))
  parts = chunk(text, 2000)
  assert all(len(p) <= 2000 for p in parts)
  assert "\n".join(parts) == text
  assert chunk("y" * 4500, 2000) == ["y" * 2000, "y" * 2000, "y" * 500]


def test_state_roundtrip(tmp_path):
  st = State(tmp_path / "s.sqlite3")
  st.mark_seen([1, 2])
  assert st.filter_unseen([1, 2, 3]) == [3]
  st.set("k", {"a": 1})
  st.close()
  st2 = State(tmp_path / "s.sqlite3")
  assert st2.get("k") == {"a": 1}
  assert st2.filter_unseen([1]) == []


def test_untrusted_escapes_markdown_and_mentions():
  s = untrusted("[click](https://evil.example) **bold** @everyone <@1>\nline2 `x`")
  assert "[click]" not in s and r"\[click\]" in s
  assert r"\*\*bold\*\*" in s and r"\`x\`" in s
  assert "@everyone" not in s and "<@" not in s
  assert "\n" not in s
  assert len(untrusted("x" * 1000, 50)) == 50


def test_link_cannot_be_broken_out_of():
  assert (
    link("https://a.example/x> [y](https://evil)") == "<https://a.example/x%3E[y](https://evil)>"
  )
  assert link("https://a.example/\nx") == "<https://a.example/x>"


def test_floor_escapes_upstream_error_text():
  rep = FloorReport(
    generated_at=datetime(2026, 10, 23, 16, 0, tzinfo=UTC),
    official_error="market listings.getStats: [win](https://evil.example) @here",
    sales_error="x",
    doggy_error="y\n# heading",
  )
  text = R.floor(rep)
  assert "[win](" not in text and "@here" not in text
  assert "\n# heading" not in text


def test_sale_name_is_escaped_when_no_dog_number():
  s = Sale(
    id=1,
    name="[free](https://evil.example) @everyone",
    dog_number=None,
    price_doge=1.0,
    txid=None,
    is_manual=True,
    otc=False,
    created_at=datetime(2026, 10, 23, 16, 0, tzinfo=UTC),
    inscription_id="",
    source="",
  )
  line = R.sale_line(s)
  assert "[free](" not in line and "@everyone" not in line


def test_digest_escapes_post_text_and_gaps():
  now = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)
  post = Post(id="1", username="a", created_at=now, text="[x](https://evil.example) hi")
  d = DigestData(
    generated_at=now,
    since=now,
    floor=FloorReport(generated_at=now),
    posts={"a": [post]},
    gaps=["Doggy Market unavailable ([y](https://evil.example))."],
  )
  text = R.digest(d)
  assert "[x](" not in text and "[y](" not in text


def test_tco_strip_is_not_quadratic():
  start = time.perf_counter()
  _TCO_RE.sub("", " " * 50_000 + "x")
  assert time.perf_counter() - start < 0.5


def test_floor_with_zero_listings_is_flagged_as_stale():
  stats = parse_stats(load("market_stats.json"))
  rep = FloorReport(generated_at=datetime(2026, 10, 27, 13, 0, tzinfo=UTC), stats=stats)
  assert STALE_FLOOR_NOTE not in R.floor(rep)
  empty = replace(stats, listed=0)
  text = R.floor(FloorReport(generated_at=rep.generated_at, stats=empty))
  assert "Listed: **0** / 10,000" in text
  assert STALE_FLOOR_NOTE in text
