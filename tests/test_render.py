from zoneinfo import ZoneInfo

from ddhelper.render import Renderer, chunk, doge, sanitize
from ddhelper.sources.market import parse_activity
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
