"""Plain-text (Discord markdown) rendering. Pure functions; no I/O."""

from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .service import DigestData, FloorAlert, FloorReport
from .sources.cards import Card
from .sources.market import Sale

DISCORD_LIMIT = 2000
_TCO_RE = re.compile(r"\s*https://t\.co/\w+")
_MENTION_RE = re.compile(r"@(everyone|here)", re.I)


def doge(x: float) -> str:
  if abs(x - round(x)) < 0.005:
    return f"{x:,.0f} DOGE"
  return f"{x:,.2f} DOGE"


def plural(n: int, word: str) -> str:
  return f"{n} {word}" + ("" if n == 1 else "s")


def pct(x: float) -> str:
  return f"{x:+.1f}%"


def link(url: str) -> str:
  """Angle brackets stop Discord from unfurling a preview for the link."""
  return f"<{url}>"


def sanitize(text: str) -> str:
  """Neutralise mass mentions and user/role/channel pings in upstream text."""
  text = _MENTION_RE.sub("@\u200b\\1", text)
  return text.replace("<@", "<\u200b@").replace("<#", "<\u200b#")


class Renderer:
  def __init__(self, tz: ZoneInfo, tz_label: str = "ET", tx_explorer_url: str = "https://blockchair.com/dogecoin/transaction/{txid}"):
    self.tz = tz
    self.tz_label = tz_label
    self.tx_url = tx_explorer_url

  def ts(self, dt: datetime, fmt: str = "%a %b %-d, %-I:%M %p") -> str:
    return dt.astimezone(self.tz).strftime(fmt) + f" {self.tz_label}"

  # floor
  def floor(self, r: FloorReport) -> str:
    lines = ["**Doginal Dogs floor** (official market: market.doginaldogs.com)"]
    if r.stats:
      s = r.stats
      lines.append(f"Floor: **{doge(s.floor)}**  ·  Listed: **{s.listed:,}** / {s.supply:,}")
      lines.append(f"30d volume: {doge(s.volume_30d)} over {s.trades_30d} trades (avg {doge(s.avg_sale_30d)})")
    else:
      lines.append(f"⚠️ Official stats unavailable: {r.official_error}")
    if r.vol_24h and r.vol_7d:
      lines.append(f"24h volume: {doge(r.vol_24h.doge)} ({plural(r.vol_24h.count, 'sale')})  ·  "
                   f"7d volume: {doge(r.vol_7d.doge)} ({plural(r.vol_7d.count, 'sale')})")
      if r.vol_7d.without_tx:
        lines.append(f"ℹ️ {r.vol_7d.without_tx} of {r.vol_7d.count} sales in 7d have no tx id (manually recorded by the market; not verified on-chain).")
    elif r.sales_error:
      lines.append(f"⚠️ Sales feed unavailable: {r.sales_error}")
    lines.append("")
    if r.doggy:
      d = r.doggy
      cmp = ""
      if r.stats and r.stats.floor:
        cmp = f" ({pct((d.floor - r.stats.floor) / r.stats.floor * 100)} vs official)"
      lines.append(f"Doggy Market (secondary): floor {doge(d.floor)}{cmp}, {d.listed} listed, "
                   f"7d: {plural(d.trades_7d, 'trade')} / {doge(d.volume_7d)}")
      for w in r.doggy_warnings:
        lines.append(f"⚠️ {w}")
    else:
      lines.append(f"Doggy Market (secondary): unavailable ({r.doggy_error})")
    lines.append(f"-# Data as of {self.ts(r.generated_at)}. Market figures come from the official site's unofficial internal endpoints.")
    return "\n".join(lines)

  # sales
  def sale_line(self, s: Sale) -> str:
    title = f"#{s.dog_number}" if s.dog_number is not None else s.name
    head = f"**{title}** · {doge(s.price_doge)} · {self.ts(s.created_at)}"
    if s.has_tx:
      assert s.txid  # noqa: S101
      tail = f"tx `{s.txid[:10]}…{s.txid[-6:]}` {link(self.tx_url.format(txid=s.txid))}"
    else:
      tail = "⚠️ no tx id (manually recorded sale)"
      if s.otc:
        tail += " · OTC"
    return f"{head}\n  {tail} · {link(s.market_url)}"

  def sales(self, sales: list[Sale]) -> str:
    if not sales:
      return "No recent sales returned by the official market."
    lines = [f"**Recent Doginal Dogs sales** (latest {len(sales)}, official market)"]
    lines += [self.sale_line(s) for s in sales]
    manual = sum(1 for s in sales if not s.has_tx)
    if manual:
      lines.append(f"-# {manual} of {len(sales)} have no on-chain tx id in the market data (recorded manually); treat as unverified.")
    return "\n".join(lines)

  def sale_alert(self, s: Sale) -> str:
    return "🐶 **New Doginal Dogs sale**\n" + self.sale_line(s)

  def floor_alert(self, a: FloorAlert) -> str:
    arrow = "📈" if a.pct > 0 else "📉"
    extra = f" · {a.listed:,} listed" if a.listed is not None else ""
    return (f"{arrow} **Floor moved {pct(a.pct)}**: {doge(a.old)} → **{doge(a.new)}**{extra}\n"
            f"-# official market · {link('https://market.doginaldogs.com/')}")

  # cards
  def card(self, matches: list[Card], query: str, source: str) -> str:
    if not matches:
      return f"No DDL card matches “{sanitize(query)}”. Try a name (e.g. Renza) or a serial (e.g. V052)."
    c = matches[0]
    stats = []
    if c.mana is not None:
      stats.append(f"Mana {c.mana}")
    if c.type == "Creature":
      stats.append(f"ATK {c.attack if c.attack is not None else '-'} / HP {c.hp if c.hp is not None else '-'}")
    lines = [
      f"**{c.name}** ({c.serial}) · {c.rarity} {c.card_class} {c.type}",
      " · ".join(stats) if stats else "",
    ]
    if c.keywords:
      lines.append("Keywords: " + ", ".join(c.keywords))
    if c.description:
      lines.append(f"> {c.description}")
    if c.image_url:
      lines.append(f"Card image: {link(c.image_url)}")
    if len(matches) > 1:
      lines.append("Other matches: " + ", ".join(f"{m.name} ({m.serial})" for m in matches[1:]))
    lines.append(f"-# Source: {source}. DDL TCG card data © Doginal Dogs.")
    return "\n".join(x for x in lines if x)

  # digest
  def digest(self, d: DigestData) -> str:
    day = d.generated_at.astimezone(self.tz).strftime("%a %b %-d, %Y")
    out = [f"## 🐶 Doginal Dogs daily digest · {day}"]
    f = d.floor
    out.append("**Market** (official)")
    if f.stats:
      line = f"Floor **{doge(f.stats.floor)}**"
      if d.floor_24h_ago:
        line += f" ({pct((f.stats.floor - d.floor_24h_ago) / d.floor_24h_ago * 100)} 24h"
        if d.floor_7d_ago:
          line += f", {pct((f.stats.floor - d.floor_7d_ago) / d.floor_7d_ago * 100)} 7d"
        line += ")"
      line += f" · {f.stats.listed:,} listed"
      out.append(line)
    if f.vol_24h is not None:
      out.append(f"24h: {plural(f.vol_24h.count, 'sale')}, {doge(f.vol_24h.doge)}"
                 + (f" · 7d: {plural(f.vol_7d.count, 'sale')}, {doge(f.vol_7d.doge)}" if f.vol_7d else ""))
    if d.sales:
      top = sorted(d.sales, key=lambda s: s.price_doge, reverse=True)[:3]
      out.append("Top sales: " + ", ".join(
        f"#{s.dog_number if s.dog_number is not None else '?'} {doge(s.price_doge)}{'' if s.has_tx else '*'}" for s in top))
      if any(not s.has_tx for s in top):
        out.append("-# * manually recorded, no tx id")
    if f.doggy and f.doggy_warnings:
      out.append(f"Doggy Market floor {doge(f.doggy.floor)} — ⚠️ {f.doggy_warnings[0]}")

    if d.posts or d.sales_bot_posts is not None:
      out.append("\n**On X (last 24h)**")
      for user, posts in d.posts.items():
        if not posts:
          out.append(f"@{user}: no new original posts")
          continue
        for p in posts[:3]:
          text = sanitize(_TCO_RE.sub("", p.text).strip().replace("\n", " "))
          if p.space_urls:
            text = "🎙️ X Space " + (text or "")
          elif not text:
            text = "(link/media post)"
          if len(text) > 140:
            text = text[:139] + "…"
          out.append(f"@{user} · {self.ts(p.created_at, '%-I:%M %p')}: {text} {link(p.url)}")
      if d.sales_bot_posts is not None:
        out.append(f"@DDSalesBot posted {plural(d.sales_bot_posts, 'sale update')}.")

    if d.recurring_today or d.events:
      out.append("\n**Upcoming**")
      for r, at in d.recurring_today:
        out.append(f"Today {self.ts(at, '%-I:%M %p')}: {r.name}" + (f" {link(r.url)}" if r.url else "")
                   + (f"\n-# {r.note}" if r.note else ""))
      today = d.generated_at.astimezone(self.tz).date()
      for e in d.events:
        days = (e.start - today).days
        when = "happening now" if days <= 0 else f"in {days} day{'s' if days != 1 else ''}"
        span = e.start.strftime("%b %-d") + (f"–{e.end.strftime('%-d' if e.end.month == e.start.month else '%b %-d')}" if e.end != e.start else "")
        out.append(f"{e.name}: {span}, {e.start.year} ({when})" + (f" · {e.location}" if e.location else "")
                   + (f" {link(e.url)}" if e.url else ""))
    if d.gaps:
      out.append("\n**Gaps**")
      out += [f"- {g}" for g in d.gaps]
    out.append(f"-# Generated {self.ts(d.generated_at)} by ddhelper (read-only community bot).")
    return "\n".join(out)


def chunk(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
  """Split on line boundaries so each chunk fits a Discord message."""
  chunks: list[str] = []
  cur = ""
  for line in text.split("\n"):
    while len(line) > limit:
      if cur:
        chunks.append(cur)
        cur = ""
      chunks.append(line[:limit])
      line = line[limit:]
    candidate = f"{cur}\n{line}" if cur else line
    if len(candidate) > limit:
      chunks.append(cur)
      cur = line
    else:
      cur = candidate
  if cur:
    chunks.append(cur)
  return chunks
