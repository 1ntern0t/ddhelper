"""Command line: `python -m ddhelper run` (bot) or `python -m ddhelper dry-run ...`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

from .config import ConfigError, Settings, load_dotenv
from .events import load_events
from .http import HttpClient, SourceError
from .render import Renderer, chunk
from .service import Helper
from .sources.cards import validate_query
from .state import State

log = logging.getLogger("ddhelper")


def _setup_logging(verbose: bool) -> None:
  logging.basicConfig(
    level=logging.DEBUG if verbose else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
  )
  # aiohttp/discord debug logs can include request headers; keep them quiet.
  logging.getLogger("aiohttp").setLevel(logging.WARNING)
  logging.getLogger("discord.http").setLevel(logging.INFO)


def _print_message(text: str) -> None:
  parts = chunk(text)
  for i, part in enumerate(parts, 1):
    if len(parts) > 1:
      print(f"----- message {i}/{len(parts)} ({len(part)} chars) -----")
    print(part)


async def dry_run(settings: Settings, what: str, arg: str | None, n: int) -> int:
  events = load_events(settings.events_file)
  renderer = Renderer(settings.tz, tx_explorer_url=settings.tx_explorer_url)
  async with HttpClient(settings.user_agent, timeout=settings.http_timeout) as http:
    helper = Helper(settings, http, events=events)
    try:
      if what == "floor":
        _print_message(renderer.floor(await helper.floor_report()))
      elif what == "sales":
        _print_message(renderer.sales(await helper.recent_sales(n)))
      elif what == "digest":
        _print_message(renderer.digest(await helper.digest()))
      elif what == "card":
        q = validate_query(arg or "")
        _print_message(renderer.card(await helper.find_card(q), q, helper.cards.name))
      elif what == "alerts":
        # Uses a throwaway in-memory state: shows what the first two poll cycles would do.
        st = State(":memory:")
        seeded = await helper.poll_new_sales(st)
        print(
          f"[sales poll #1] seeded state, would post {len(seeded)} alert(s) (first run never floods)"
        )
        new = await helper.poll_new_sales(st)
        print(f"[sales poll #2] would post {len(new)} alert(s)")
        for s in new:
          _print_message(renderer.sale_alert(s))
        await helper.poll_floor(st)
        alert = await helper.poll_floor(st)
        print(
          f"[floor poll] baseline set; alert now: {renderer.floor_alert(alert) if alert else 'none'}"
        )
    except SourceError as e:
      print(f"Source unavailable: {e}", file=sys.stderr)
      return 2
    except ValueError as e:
      print(f"Invalid input: {e}", file=sys.stderr)
      return 64
  return 0


def build_parser() -> argparse.ArgumentParser:
  p = argparse.ArgumentParser(
    prog="ddhelper", description="Doginal Dogs community helper bot (read-only)."
  )
  p.add_argument("--env-file", default=".env", help="optional .env file to load (default: .env)")
  p.add_argument("-v", "--verbose", action="store_true")
  sub = p.add_subparsers(dest="cmd", required=True)
  sub.add_parser("run", help="run the Discord bot")
  dr = sub.add_parser("dry-run", help="fetch live data and print what the bot would post")
  dr.add_argument("what", choices=["floor", "sales", "digest", "card", "alerts"])
  dr.add_argument("arg", nargs="?", help="card name or serial (for `card`)")
  dr.add_argument("-n", type=int, default=5, help="number of sales (1-25, for `sales`)")
  sub.add_parser("check-config", help="validate configuration without connecting")
  return p


def main(argv: Sequence[str] | None = None) -> int:
  args = build_parser().parse_args(argv)
  _setup_logging(args.verbose)
  load_dotenv(args.env_file)
  try:
    settings = Settings.from_env()
  except ConfigError as e:
    print(f"Config error: {e}", file=sys.stderr)
    return 78
  if args.cmd == "check-config":
    try:
      load_events(settings.events_file)
      settings.require_discord()
    except (ConfigError, ValueError, OSError) as e:
      print(f"Config error: {e}", file=sys.stderr)
      return 78
    print("Config OK:", settings)  # secrets are excluded from repr
    return 0
  if args.cmd == "dry-run":
    if args.what == "card" and not args.arg:
      print("usage: ddhelper dry-run card <name>", file=sys.stderr)
      return 64
    if not 1 <= args.n <= 25:
      print("-n must be between 1 and 25", file=sys.stderr)
      return 64
    return asyncio.run(dry_run(settings, args.what, args.arg, args.n))
  try:
    settings.require_discord()
  except ConfigError as e:
    print(f"Config error: {e}", file=sys.stderr)
    return 78
  from .bot import run_bot  # imported lazily so dry-run works without discord.py configured

  run_bot(settings)
  return 0
