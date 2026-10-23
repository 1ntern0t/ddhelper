"""Polite async HTTP client: timeouts, retries with backoff, rate-limit respect, TTL cache."""

from __future__ import annotations

import asyncio
import email.utils
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

import aiohttp

log = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class SourceError(Exception):
  """A data source could not be reached or returned unusable data."""


class RateLimited(SourceError):
  """The remote asked us to wait longer than we are willing to block."""

  def __init__(self, url: str, retry_after: float):
    super().__init__(f"rate limited by {urlsplit(url).netloc}; retry after {retry_after:.0f}s")
    self.retry_after = retry_after


@dataclass(frozen=True)
class JsonResponse:
  data: Any
  status: int
  headers: Mapping[str, str]
  fetched_at: float
  from_cache: bool = False


class Fetcher(Protocol):
  async def get_json(
    self,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    cache_ttl: float = 0,
  ) -> JsonResponse: ...


def parse_retry_after(headers: Mapping[str, str], now: float | None = None) -> float | None:
  """Seconds to wait, from Retry-After (seconds or HTTP date) or X's x-rate-limit-reset (epoch)."""
  now = time.time() if now is None else now
  ra = headers.get("Retry-After") or headers.get("retry-after")
  if ra:
    ra = ra.strip()
    if ra.isdigit():
      return float(ra)
    try:
      dt = email.utils.parsedate_to_datetime(ra)
      return max(0.0, dt.timestamp() - now)
    except (TypeError, ValueError):
      pass
  reset = headers.get("x-rate-limit-reset") or headers.get("X-Rate-Limit-Reset")
  if reset and reset.strip().isdigit():
    return max(0.0, float(reset) - now)
  return None


class HttpClient:
  """aiohttp wrapper. One instance per process; call `close()` on shutdown."""

  def __init__(
    self,
    user_agent: str,
    *,
    timeout: float = 15.0,
    retries: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    max_rate_limit_wait: float = 60.0,
    min_host_interval: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    session: aiohttp.ClientSession | None = None,
  ):
    self._ua = user_agent
    self._timeout = aiohttp.ClientTimeout(total=timeout)
    self._retries = retries
    self._backoff_base = backoff_base
    self._backoff_max = backoff_max
    self._max_rl_wait = max_rate_limit_wait
    self._min_host_interval = min_host_interval
    self._sleep = sleep
    self._session = session
    self._own_session = session is None
    self._cache: dict[str, tuple[float, JsonResponse]] = {}
    self._host_last: dict[str, float] = {}
    self._host_locks: dict[str, asyncio.Lock] = {}
    self._blocked_until: dict[str, float] = {}

  async def _get_session(self) -> aiohttp.ClientSession:
    if self._session is None or self._session.closed:
      self._session = aiohttp.ClientSession(timeout=self._timeout, raise_for_status=False)
      self._own_session = True
    return self._session

  async def close(self) -> None:
    if self._session is not None and self._own_session and not self._session.closed:
      await self._session.close()

  async def __aenter__(self) -> HttpClient:
    return self

  async def __aexit__(self, *exc: object) -> None:
    await self.close()

  def _backoff(self, attempt: int) -> float:
    cap = min(self._backoff_max, self._backoff_base * (2**attempt))
    return random.uniform(cap / 2, cap)  # noqa: S311 - jitter, not crypto

  @staticmethod
  def _cache_key(url: str, params: Mapping[str, str] | None) -> str:
    return url + "?" + json.dumps(sorted((params or {}).items()))

  async def _polite_wait(self, host: str) -> None:
    lock = self._host_locks.setdefault(host, asyncio.Lock())
    async with lock:
      wait = self._host_last.get(host, 0.0) + self._min_host_interval - time.monotonic()
      if wait > 0:
        await self._sleep(wait)
      self._host_last[host] = time.monotonic()

  async def get_json(
    self,
    url: str,
    *,
    params: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    cache_ttl: float = 0,
  ) -> JsonResponse:
    key = self._cache_key(url, params)
    now = time.monotonic()
    if cache_ttl > 0 and key in self._cache:
      expires, resp = self._cache[key]
      if now < expires:
        return JsonResponse(resp.data, resp.status, resp.headers, resp.fetched_at, from_cache=True)

    host = urlsplit(url).netloc
    blocked = self._blocked_until.get(host, 0.0) - time.time()
    if blocked > 0:
      raise RateLimited(url, blocked)

    req_headers = {"User-Agent": self._ua, "Accept": "application/json"}
    if headers:
      req_headers.update(headers)
    session = await self._get_session()
    last_err: str = "unknown error"
    for attempt in range(self._retries + 1):
      await self._polite_wait(host)
      try:
        async with session.get(url, params=params, headers=req_headers, timeout=self._timeout) as r:
          status = r.status
          rheaders = {k: v for k, v in r.headers.items()}
          body = await r.read()
      except (aiohttp.ClientError, TimeoutError) as e:
        last_err = f"{type(e).__name__}: {e}"
        log.warning(
          "GET %s failed (%s), attempt %d/%d", url, type(e).__name__, attempt + 1, self._retries + 1
        )
        if attempt < self._retries:
          await self._sleep(self._backoff(attempt))
        continue

      if status in RETRY_STATUSES:
        last_err = f"HTTP {status}"
        wait = parse_retry_after(rheaders) if status == 429 else None
        if status == 429 and wait is not None and wait > self._max_rl_wait:
          self._blocked_until[host] = time.time() + wait
          raise RateLimited(url, wait)
        log.warning("GET %s -> HTTP %d, attempt %d/%d", url, status, attempt + 1, self._retries + 1)
        if attempt < self._retries:
          await self._sleep(wait if wait is not None else self._backoff(attempt))
        continue
      if status >= 400:
        raise SourceError(f"GET {urlsplit(url).netloc}{urlsplit(url).path} -> HTTP {status}")
      try:
        data = json.loads(body)
      except ValueError as e:
        raise SourceError(f"GET {urlsplit(url).netloc}{urlsplit(url).path}: invalid JSON") from e
      resp = JsonResponse(data, status, rheaders, time.time())
      if cache_ttl > 0:
        self._cache[key] = (time.monotonic() + cache_ttl, resp)
      return resp
    raise SourceError(
      f"GET {urlsplit(url).netloc}{urlsplit(url).path} failed after retries: {last_err}"
    )
