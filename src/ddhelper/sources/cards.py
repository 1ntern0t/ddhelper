"""DDL TCG ("Doginal Dogs Legends") card data. Pluggable source.

- OfficialCardSource: https://ddltcg.com/data/cards.json. That path is explicitly
  `Allow`ed in ddltcg.com/robots.txt and is what the official gallery page loads.
  Fetched at most every 6 hours (cached).
- LocalJsonCardSource: a local JSON file with the same schema (a list of card
  objects, or {"cards": [...]}) for offline use or if the official file moves.

Note: ddltcg.kushmetax.com (DDL Companion) has `Disallow: /` in robots.txt, so this
bot does NOT fetch from it. Ask @KushMetaX if you want to integrate with it.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..http import Fetcher, SourceError

_QUERY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 '\-.]{0,39}$")
_SERIAL_RE = re.compile(r"^V\d{1,3}$", re.I)


@dataclass(frozen=True)
class Card:
  serial: str
  name: str
  card_class: str
  type: str
  rarity: str
  mana: int | None
  attack: int | None
  hp: int | None
  keywords: tuple[str, ...]
  description: str
  image_url: str | None


def validate_query(q: str) -> str:
  """Normalise and validate user input for /card. Raises ValueError."""
  q = unicodedata.normalize("NFKC", q or "").strip()
  q = re.sub(r"\s+", " ", q)
  if not _QUERY_RE.match(q):
    raise ValueError("Card name must be 1-40 characters: letters, digits, spaces, ' - .")
  return q


def _int(v: Any) -> int | None:
  try:
    return int(v) if v is not None and v != "" else None
  except (TypeError, ValueError):
    return None


def parse_cards(data: Any, image_base: str = "https://ddltcg.com") -> list[Card]:
  rows = data.get("cards") if isinstance(data, dict) else data
  if not isinstance(rows, list):
    raise SourceError("card data: expected a list of cards")
  out = []
  for c in rows:
    if not isinstance(c, dict) or not c.get("id") or not c.get("name"):
      continue
    if c.get("sealed") in (True, 1, "1"):
      continue  # unrevealed cards are redacted upstream; never show them
    serial = str(c["id"]).strip().upper()
    img = c.get("image_url")
    if not img and _SERIAL_RE.match(serial):
      # Same path the official gallery uses (cardRenderPath in /js/config.js).
      img = f"{image_base.rstrip('/')}/card_renders/v2/{serial}.png"
    out.append(
      Card(
        serial=serial,
        name=str(c["name"]).strip(),
        card_class=str(c.get("class") or c.get("classRaw") or ""),
        type=str(c.get("type") or ""),
        rarity=str(c.get("rarity") or ""),
        mana=_int(c.get("mana")),
        attack=_int(c.get("attack")),
        hp=_int(c.get("hp")),
        keywords=tuple(
          str(k) for k in c.get("keywords") or ([c["keyword"]] if c.get("keyword") else [])
        ),
        description=str(c.get("description") or ""),
        image_url=img,
      )
    )
  return out


def search(cards: list[Card], query: str, limit: int = 5) -> list[Card]:
  """Rank: exact serial > exact name > name prefix > substring > fuzzy."""
  q = validate_query(query).lower()
  if _SERIAL_RE.match(q):
    num = int(q[1:])
    hit = [c for c in cards if c.serial.lower() == f"v{num:03d}"]
    if hit:
      return hit
  exact = [c for c in cards if c.name.lower() == q]
  if exact:
    return exact
  prefix = [c for c in cards if c.name.lower().startswith(q)]
  sub = [c for c in cards if q in c.name.lower() and c not in prefix]
  ranked = prefix + sub
  if ranked:
    return ranked[:limit]
  names = {c.name.lower(): c for c in cards}
  return [names[n] for n in difflib.get_close_matches(q, list(names), n=limit, cutoff=0.6)]


class CardSource(Protocol):
  name: str

  async def all_cards(self) -> list[Card]: ...


class OfficialCardSource:
  name = "ddltcg.com"

  def __init__(self, fetcher: Fetcher, url: str = "https://ddltcg.com/data/cards.json"):
    self._f = fetcher
    self._url = url

  async def all_cards(self) -> list[Card]:
    r = await self._f.get_json(self._url, cache_ttl=6 * 3600)
    base = self._url.split("/data/")[0]
    return parse_cards(r.data, base)


class LocalJsonCardSource:
  def __init__(self, path: str | Path):
    self._path = Path(path)
    self.name = f"local file {self._path.name}"
    self._cache: list[Card] | None = None

  async def all_cards(self) -> list[Card]:
    if self._cache is None:
      try:
        data = json.loads(self._path.read_text(encoding="utf-8"))
      except (OSError, ValueError) as e:
        raise SourceError(f"card file {self._path}: {e}") from e
      self._cache = parse_cards(data)
    return self._cache
