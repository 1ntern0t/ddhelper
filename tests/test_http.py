"""Exercise the real HttpClient against a local aiohttp server (no external network)."""

import asyncio

import pytest
from aiohttp import web

from ddhelper.http import HttpClient, RateLimited, SourceError, parse_retry_after


@pytest.fixture
async def server():
  state = {"hits": {}, "ua": None, "plan": {}}

  async def handler(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    state["hits"][name] = state["hits"].get(name, 0) + 1
    state["ua"] = request.headers.get("User-Agent")
    plan = state["plan"].get(name, [])
    n = state["hits"][name] - 1
    step = plan[n] if n < len(plan) else (200, {}, '{"ok": true}')
    status, headers, body = step
    if status == "sleep":
      await asyncio.sleep(2)
      return web.json_response({"late": True})
    return web.Response(status=status, headers=headers, text=body, content_type="application/json")

  app = web.Application()
  app.router.add_get("/{name}", handler)
  runner = web.AppRunner(app)
  await runner.setup()
  site = web.TCPSite(runner, "127.0.0.1", 0)
  await site.start()
  port = site._server.sockets[0].getsockname()[1]
  state["base"] = f"http://127.0.0.1:{port}"
  yield state
  await runner.cleanup()


def client(sleeps, **kw):
  async def fake_sleep(s):
    sleeps.append(s)

  return HttpClient("ddhelper-test/1.0", sleep=fake_sleep, min_host_interval=0, **kw)


async def test_ua_and_success(server):
  sleeps = []
  async with client(sleeps) as c:
    r = await c.get_json(server["base"] + "/a")
  assert r.data == {"ok": True}
  assert server["ua"] == "ddhelper-test/1.0"


async def test_retries_5xx_then_succeeds(server):
  server["plan"]["b"] = [(503, {}, "{}"), (502, {}, "{}"), (200, {}, '{"v": 1}')]
  sleeps = []
  async with client(sleeps, retries=3) as c:
    r = await c.get_json(server["base"] + "/b")
  assert r.data == {"v": 1}
  assert server["hits"]["b"] == 3
  assert len(sleeps) == 2 and all(s > 0 for s in sleeps)


async def test_gives_up_after_retries(server):
  server["plan"]["c"] = [(500, {}, "{}")] * 10
  sleeps = []
  async with client(sleeps, retries=2) as c:
    with pytest.raises(SourceError, match="failed after retries"):
      await c.get_json(server["base"] + "/c")
  assert server["hits"]["c"] == 3


async def test_429_short_retry_after_is_honoured(server):
  server["plan"]["d"] = [(429, {"Retry-After": "7"}, "{}"), (200, {}, '{"ok": 1}')]
  sleeps = []
  async with client(sleeps) as c:
    r = await c.get_json(server["base"] + "/d")
  assert r.data == {"ok": 1}
  assert sleeps == [7.0]


async def test_429_long_wait_raises_and_blocks_host(server):
  server["plan"]["e"] = [(429, {"Retry-After": "900"}, "{}")]
  sleeps = []
  async with client(sleeps, max_rate_limit_wait=60) as c:
    with pytest.raises(RateLimited):
      await c.get_json(server["base"] + "/e")
    with pytest.raises(RateLimited):
      await c.get_json(server["base"] + "/a")  # same host is backed off without a request
  assert server["hits"].get("a") is None


async def test_4xx_not_retried(server):
  server["plan"]["f"] = [(404, {}, "{}")]
  async with client([]) as c:
    with pytest.raises(SourceError, match="HTTP 404"):
      await c.get_json(server["base"] + "/f")
  assert server["hits"]["f"] == 1


async def test_invalid_json(server):
  server["plan"]["g"] = [(200, {}, "<html>")]
  async with client([]) as c:
    with pytest.raises(SourceError, match="invalid JSON"):
      await c.get_json(server["base"] + "/g")


async def test_cache(server):
  async with client([]) as c:
    r1 = await c.get_json(server["base"] + "/h", cache_ttl=60)
    r2 = await c.get_json(server["base"] + "/h", cache_ttl=60)
    r3 = await c.get_json(server["base"] + "/h", params={"x": "1"}, cache_ttl=60)
  assert not r1.from_cache and r2.from_cache and not r3.from_cache
  assert server["hits"]["h"] == 2


async def test_timeout_retried(server):
  server["plan"]["t"] = [("sleep", {}, ""), (200, {}, '{"ok": 2}')]
  sleeps = []
  async with client(sleeps, timeout=0.5, retries=1) as c:
    r = await c.get_json(server["base"] + "/t")
  assert r.data == {"ok": 2}
  assert len(sleeps) == 1


def test_parse_retry_after():
  assert parse_retry_after({"Retry-After": "12"}) == 12
  assert parse_retry_after({"x-rate-limit-reset": "1100"}, now=1000) == 100
  assert parse_retry_after({}) is None


async def test_oversized_body_rejected(server):
  server["plan"]["big"] = [(200, {}, '{"x": "' + "a" * 5000 + '"}')]
  sleeps = []
  async with client(sleeps, max_bytes=1000) as c:
    with pytest.raises(SourceError, match="larger than 1000 bytes"):
      await c.get_json(server["base"] + "/big")
  assert server["hits"]["big"] == 1  # not retried


async def test_oversized_chunked_body_rejected():
  async def handler(request: web.Request) -> web.StreamResponse:
    resp = web.StreamResponse(headers={"Content-Type": "application/json"})
    resp.enable_chunked_encoding()
    await resp.prepare(request)
    await resp.write(b'{"x": "')
    for _ in range(50):
      await resp.write(b"a" * 1000)
    await resp.write(b'"}')
    await resp.write_eof()
    return resp

  app = web.Application()
  app.router.add_get("/s", handler)
  runner = web.AppRunner(app)
  await runner.setup()
  site = web.TCPSite(runner, "127.0.0.1", 0)
  await site.start()
  port = site._server.sockets[0].getsockname()[1]
  try:
    async with client([], max_bytes=10_000) as c:
      with pytest.raises(SourceError, match="larger than"):
        await c.get_json(f"http://127.0.0.1:{port}/s")
    async with client([], max_bytes=100_000) as c:
      r = await c.get_json(f"http://127.0.0.1:{port}/s")
      assert len(r.data["x"]) == 50_000
  finally:
    await runner.cleanup()
