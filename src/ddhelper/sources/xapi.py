"""X API v2 (read-only, app-only bearer token).

Endpoints used:
  GET /2/users/by?usernames=...            (resolve handles -> ids, cached)
  GET /2/users/:id/tweets?start_time=...   (recent original posts)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..http import Fetcher, SourceError
from ._util import parse_iso

_SPACE_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/i/spaces/[A-Za-z0-9]+", re.I)
_TCO_ONLY_RE = re.compile(r"^\s*(?:https://t\.co/\w+\s*)+$")


class XUnavailable(SourceError):
  """X data is not available (no token, auth failure, rate limit, outage)."""


@dataclass(frozen=True)
class Post:
  id: str
  username: str
  created_at: datetime
  text: str
  likes: int = 0
  reposts: int = 0
  replies: int = 0
  views: int | None = None
  urls: tuple[str, ...] = field(default_factory=tuple)
  is_quote: bool = False

  @property
  def url(self) -> str:
    return f"https://x.com/{self.username}/status/{self.id}"

  @property
  def space_urls(self) -> list[str]:
    return [u for u in self.urls if _SPACE_RE.match(u)] + _SPACE_RE.findall(self.text)

  @property
  def link_only(self) -> bool:
    """Post body is just t.co link(s) (e.g. @barkmeta's daily Space link post)."""
    return bool(_TCO_ONLY_RE.match(self.text))


def parse_users(payload: Any) -> dict[str, str]:
  if not isinstance(payload, dict):
    raise XUnavailable("X users lookup: unexpected response")
  return {
    u["username"].lower(): u["id"]
    for u in payload.get("data") or []
    if "id" in u and "username" in u
  }


def parse_posts(payload: Any, username: str) -> list[Post]:
  if not isinstance(payload, dict):
    raise XUnavailable("X timeline: unexpected response")
  out = []
  for p in payload.get("data") or []:
    created = parse_iso(p.get("created_at"))
    if not created or "id" not in p:
      continue
    m = p.get("public_metrics") or {}
    urls = tuple(
      u.get("unwound_url") or u.get("expanded_url") or ""
      for u in (p.get("entities") or {}).get("urls") or []
    )
    refs = {r.get("type") for r in p.get("referenced_tweets") or []}
    out.append(
      Post(
        id=str(p["id"]),
        username=username,
        created_at=created,
        text=str(p.get("text") or ""),
        likes=int(m.get("like_count") or 0),
        reposts=int(m.get("retweet_count") or 0),
        replies=int(m.get("reply_count") or 0),
        views=int(m["impression_count"]) if m.get("impression_count") is not None else None,
        urls=tuple(u for u in urls if u),
        is_quote="quoted" in refs,
      )
    )
  return sorted(out, key=lambda x: x.created_at, reverse=True)


class XClient:
  name = "X API v2"

  def __init__(
    self, fetcher: Fetcher, bearer_token: str | None, base_url: str = "https://api.x.com/2"
  ):
    self._f = fetcher
    self._token = bearer_token
    self._base = base_url.rstrip("/")
    self._ids: dict[str, str] = {}

  @property
  def available(self) -> bool:
    return bool(self._token)

  def _headers(self) -> dict[str, str]:
    if not self._token:
      raise XUnavailable("X_BEARER_TOKEN is not set")
    return {"Authorization": f"Bearer {self._token}"}

  async def _get(self, path: str, params: dict[str, str], cache_ttl: float) -> Any:
    try:
      r = await self._f.get_json(
        self._base + path, params=params, headers=self._headers(), cache_ttl=cache_ttl
      )
    except XUnavailable:
      raise
    except SourceError as e:
      raise XUnavailable(str(e)) from e
    return r.data

  async def user_ids(self, usernames: list[str] | tuple[str, ...]) -> dict[str, str]:
    missing = [u for u in usernames if u.lower() not in self._ids]
    if missing:
      data = await self._get("/users/by", {"usernames": ",".join(missing)}, cache_ttl=86400)
      self._ids.update(parse_users(data))
    return {u: self._ids[u.lower()] for u in usernames if u.lower() in self._ids}

  async def recent_posts(
    self, username: str, user_id: str, since: datetime, max_results: int = 10
  ) -> list[Post]:
    params = {
      "max_results": str(max(5, min(max_results, 100))),
      "exclude": "retweets,replies",
      "start_time": since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
      "tweet.fields": "created_at,public_metrics,entities,referenced_tweets",
    }
    data = await self._get(f"/users/{user_id}/tweets", params, cache_ttl=600)
    return parse_posts(data, username)
