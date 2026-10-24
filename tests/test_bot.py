"""Offline checks of the Discord layer (no gateway connection, no token)."""

import dataclasses

import discord
import pytest

from ddhelper import bot
from ddhelper.http import SourceError
from ddhelper.render import Renderer
from ddhelper.service import Helper
from ddhelper.sources.cards import parse_cards
from ddhelper.state import State

from .conftest import FixtureFetcher, load


async def test_commands_registered_to_guild(settings):
  b = bot.DDHelperBot(
    settings, None, Helper(settings, FixtureFetcher()), State(":memory:"), Renderer(settings.tz)
  )
  guild = discord.Object(id=1188215586057093120)
  bot.register_commands(b, guild)
  cmds = {c.name: c for c in b.tree.get_commands(guild=guild)}
  assert set(cmds) == {"floor", "sales", "card", "digest"}
  assert b.tree.get_commands() == []  # nothing global
  sales_n = next(p for p in cmds["sales"].parameters if p.name == "n")
  assert (sales_n.min_value, sales_n.max_value) == (1, 10)
  name = next(o for o in cmds["card"].to_dict(b.tree)["options"] if o["name"] == "name")
  assert (name["min_length"], name["max_length"], name["autocomplete"]) == (1, 40, True)
  assert b.intents.value == 1


def test_card_embed():
  cards = parse_cards(load("ddl_cards_subset.json"))
  renza = next(c for c in cards if c.serial == "V052")
  e = bot.card_embed(renza, "ddltcg.com", [])
  assert e.title == "Renza (V052)"
  assert e.image.url == "https://ddltcg.com/card_renders/v2/V052.png"
  assert {f.name for f in e.fields} >= {"Class", "Type", "Rarity", "Mana", "ATK / HP"}


class _Boom:
  """Stands in for Helper: every poll raises an unexpected (non-SourceError) error."""

  def __init__(self, exc):
    self.exc = exc
    self.calls = 0

  async def _raise(self, *a):
    self.calls += 1
    raise self.exc

  poll_new_sales = poll_floor = digest = _raise


def _bot(settings, helper):
  s = dataclasses.replace(settings, alert_channel_id=1, digest_channel_id=2)
  return bot.DDHelperBot(s, None, helper, State(":memory:"), Renderer(settings.tz))


@pytest.mark.parametrize("exc", [ValueError("bad"), OverflowError("inf"), KeyError("x")])
async def test_loops_survive_unexpected_errors(settings, exc, caplog):
  h = _Boom(exc)
  b = _bot(settings, h)
  for loop in (b.sales_loop, b.floor_loop, b.digest_loop):
    await loop()  # must not raise (a raise would stop the tasks.loop permanently)
  assert h.calls == 3
  assert b.state.get("digest_last_date") is None  # failed digest is not marked as posted
  assert sum(r.levelname == "ERROR" for r in caplog.records) == 3


async def test_loops_still_log_source_errors_as_warnings(settings, caplog):
  b = _bot(settings, _Boom(SourceError("down")))
  await b.sales_loop()
  await b.floor_loop()
  assert [r.levelname for r in caplog.records] == ["WARNING", "WARNING"]
