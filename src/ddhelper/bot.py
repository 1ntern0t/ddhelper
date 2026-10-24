"""Discord bot: slash commands + background alert/digest jobs. Read-only towards upstreams."""

from __future__ import annotations

import logging
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import tasks

from .config import Settings
from .events import load_events
from .http import HttpClient, SourceError
from .render import Renderer, chunk, untrusted
from .service import Helper
from .sources.cards import Card, validate_query
from .state import State

log = logging.getLogger(__name__)

# Least privilege: only the non-privileged GUILDS intent (channel cache).
# No message content, members or presence intents; slash commands do not need them.
INTENTS = discord.Intents.none()
INTENTS.guilds = True

# View Channel (1024) + Send Messages (2048). Interaction replies need no extra perms.
INVITE_PERMISSIONS = 3072
INVITE_URL_TEMPLATE = (
  "https://discord.com/oauth2/authorize?client_id={application_id}"
  f"&scope=bot%20applications.commands&permissions={INVITE_PERMISSIONS}"
)

NO_MENTIONS = discord.AllowedMentions.none()


def card_embed(c: Card, source: str, others: list[Card]) -> discord.Embed:
  e = discord.Embed(title=f"{c.name} ({c.serial})", description=c.description or None)
  e.add_field(name="Class", value=c.card_class or "-")
  e.add_field(name="Type", value=c.type or "-")
  e.add_field(name="Rarity", value=c.rarity or "-")
  if c.mana is not None:
    e.add_field(name="Mana", value=str(c.mana))
  if c.type == "Creature":
    e.add_field(
      name="ATK / HP",
      value=f"{c.attack if c.attack is not None else '-'} / {c.hp if c.hp is not None else '-'}",
    )
  if c.keywords:
    e.add_field(name="Keywords", value=", ".join(c.keywords), inline=False)
  if others:
    e.add_field(
      name="Other matches", value=", ".join(f"{m.name} ({m.serial})" for m in others), inline=False
    )
  if c.image_url:
    e.set_image(url=c.image_url)
  e.set_footer(text=f"Source: {source}. DDL TCG card data © Doginal Dogs.")
  return e


class DDHelperBot(discord.Client):
  def __init__(
    self, settings: Settings, http: HttpClient, helper: Helper, state: State, renderer: Renderer
  ):
    super().__init__(intents=INTENTS, allowed_mentions=NO_MENTIONS)
    self.settings = settings
    self.http_client = http
    self.helper = helper
    self.state = state
    self.renderer = renderer
    self.tree = app_commands.CommandTree(self)
    self.tree.on_error = self.on_app_command_error
    self._warned_channels: set[int] = set()
    self.sales_loop.change_interval(seconds=settings.sales_poll_seconds)
    self.floor_loop.change_interval(seconds=settings.floor_poll_seconds)
    self.digest_loop.change_interval(time=settings.digest_time.replace(tzinfo=settings.tz))

  async def setup_hook(self) -> None:
    assert self.settings.guild_id  # noqa: S101 - checked by require_discord()
    guild = discord.Object(id=self.settings.guild_id)
    register_commands(self, guild)
    await self.tree.sync(guild=guild)
    if self.settings.alert_channel_id:
      self.sales_loop.start()
      self.floor_loop.start()
    else:
      log.info("ALERT_CHANNEL_ID not set: sales/floor alerts disabled")
    if self.settings.digest_channel_id:
      self.digest_loop.start()
    else:
      log.info("DIGEST_CHANNEL_ID not set: scheduled digest disabled")

  async def close(self) -> None:
    for loop in (self.sales_loop, self.floor_loop, self.digest_loop):
      loop.cancel()
    await self.http_client.close()
    self.state.close()
    await super().close()

  async def on_ready(self) -> None:
    log.info(
      "logged in as %s (id %s); invite: %s",
      self.user,
      self.user.id if self.user else "?",
      INVITE_URL_TEMPLATE.format(application_id=self.application_id),
    )

  async def on_app_command_error(
    self, itx: discord.Interaction, error: app_commands.AppCommandError
  ) -> None:
    if isinstance(error, app_commands.CommandOnCooldown):
      msg = f"Slow down a little: try again in {error.retry_after:.0f}s."
    else:
      log.exception("command %s failed", itx.command.name if itx.command else "?", exc_info=error)
      msg = "Something went wrong fetching that. Please try again later."
    if itx.response.is_done():
      await itx.followup.send(msg, ephemeral=True)
    else:
      await itx.response.send_message(msg, ephemeral=True)

  async def _channel(self, channel_id: int) -> discord.abc.Messageable | None:
    ch = self.get_channel(channel_id)
    if ch is None:
      try:
        ch = await self.fetch_channel(channel_id)
      except (discord.NotFound, discord.Forbidden):
        ch = None
    if not isinstance(ch, discord.TextChannel | discord.Thread):
      if channel_id not in self._warned_channels:
        log.error("channel %s not found or not a text channel/thread", channel_id)
        self._warned_channels.add(channel_id)
      return None
    me = ch.guild.me
    if me is not None:
      perms = ch.permissions_for(me)
      if not (perms.view_channel and perms.send_messages):
        if channel_id not in self._warned_channels:
          log.error("missing View Channel / Send Messages in channel %s", channel_id)
          self._warned_channels.add(channel_id)
        return None
    return ch

  async def _post(self, channel_id: int, text: str) -> None:
    ch = await self._channel(channel_id)
    if ch is None:
      return
    for part in chunk(text):
      await ch.send(part, allowed_mentions=NO_MENTIONS, suppress_embeds=True)

  # An exception escaping a tasks.loop body stops that loop for good, so each
  # iteration logs unexpected errors and tries again on the next cycle.
  @tasks.loop(seconds=300)
  async def sales_loop(self) -> None:
    try:
      new = await self.helper.poll_new_sales(self.state)
      assert self.settings.alert_channel_id  # noqa: S101
      for s in new:
        await self._post(self.settings.alert_channel_id, self.renderer.sale_alert(s))
    except SourceError as e:
      log.warning("sales poll skipped: %s", e)
    except Exception:
      log.exception("sales poll failed; retrying next cycle")

  @tasks.loop(seconds=300)
  async def floor_loop(self) -> None:
    try:
      alert = await self.helper.poll_floor(self.state)
      if alert:
        assert self.settings.alert_channel_id  # noqa: S101
        await self._post(self.settings.alert_channel_id, self.renderer.floor_alert(alert))
    except SourceError as e:
      log.warning("floor poll skipped: %s", e)
    except Exception:
      log.exception("floor poll failed; retrying next cycle")

  @tasks.loop(hours=24)
  async def digest_loop(self) -> None:
    today = datetime.now(self.settings.tz).date().isoformat()
    if self.state.get("digest_last_date") == today:
      log.info("digest already posted today")
      return
    try:
      data = await self.helper.digest()
      assert self.settings.digest_channel_id  # noqa: S101
      await self._post(self.settings.digest_channel_id, self.renderer.digest(data))
    except Exception:
      log.exception("digest failed; will try again at the next scheduled time")
      return
    self.state.set("digest_last_date", today)

  @sales_loop.before_loop
  @floor_loop.before_loop
  @digest_loop.before_loop
  async def _wait_ready(self) -> None:
    await self.wait_until_ready()


def register_commands(bot: DDHelperBot, guild: discord.abc.Snowflake) -> None:
  tree, helper, r = bot.tree, bot.helper, bot.renderer
  per_user = app_commands.checks.cooldown(1, 10.0, key=lambda i: i.user.id)

  @tree.command(
    name="floor",
    description="Official floor, listings, 24h/7d volume, Doggy Market comparison",
    guild=guild,
  )
  @per_user
  async def floor_cmd(itx: discord.Interaction) -> None:
    await itx.response.defer(thinking=True)
    rep = await helper.floor_report()
    for part in chunk(r.floor(rep)):
      await itx.followup.send(part, allowed_mentions=NO_MENTIONS, suppress_embeds=True)

  @tree.command(name="sales", description="Recent sales on the official market", guild=guild)
  @app_commands.describe(n="How many sales (1-10)")
  @per_user
  async def sales_cmd(itx: discord.Interaction, n: app_commands.Range[int, 1, 10] = 5) -> None:
    await itx.response.defer(thinking=True)
    try:
      text = r.sales(await helper.recent_sales(n))
    except SourceError as e:
      text = f"⚠️ Official market unavailable right now ({untrusted(str(e))})."
    for part in chunk(text):
      await itx.followup.send(part, allowed_mentions=NO_MENTIONS, suppress_embeds=True)

  @tree.command(
    name="card",
    description="Look up a DDL TCG card by name or serial (e.g. Renza, V052)",
    guild=guild,
  )
  @app_commands.describe(name="Card name or serial")
  @per_user
  async def card_cmd(itx: discord.Interaction, name: app_commands.Range[str, 1, 40]) -> None:
    try:
      q = validate_query(name)
    except ValueError as e:
      await itx.response.send_message(str(e), ephemeral=True)
      return
    await itx.response.defer(thinking=True)
    try:
      matches = await helper.find_card(q)
    except SourceError as e:
      await itx.followup.send(
        f"⚠️ Card data unavailable right now ({untrusted(str(e))}).", allowed_mentions=NO_MENTIONS
      )
      return
    if not matches:
      await itx.followup.send(r.card([], q, helper.cards.name), allowed_mentions=NO_MENTIONS)
      return
    await itx.followup.send(
      embed=card_embed(matches[0], helper.cards.name, matches[1:]), allowed_mentions=NO_MENTIONS
    )

  @card_cmd.autocomplete("name")
  async def card_autocomplete(
    itx: discord.Interaction, current: str
  ) -> list[app_commands.Choice[str]]:
    try:
      cards = await helper.cards.all_cards()
    except SourceError:
      return []
    cur = current.strip().lower()
    hits = [c for c in cards if not cur or cur in c.name.lower() or cur == c.serial.lower()]
    return [app_commands.Choice(name=f"{c.name} ({c.serial})", value=c.serial) for c in hits[:25]]

  @tree.command(
    name="digest", description="Today's Doginal Dogs digest (only you can see it)", guild=guild
  )
  @app_commands.checks.cooldown(1, 60.0, key=lambda i: i.user.id)
  async def digest_cmd(itx: discord.Interaction) -> None:
    await itx.response.defer(thinking=True, ephemeral=True)
    text = r.digest(await helper.digest())
    for part in chunk(text):
      await itx.followup.send(
        part, ephemeral=True, allowed_mentions=NO_MENTIONS, suppress_embeds=True
      )


def run_bot(settings: Settings) -> None:
  settings.require_discord()
  http = HttpClient(settings.user_agent, timeout=settings.http_timeout)
  helper = Helper(settings, http, events=load_events(settings.events_file))
  state = State(settings.db_path)
  renderer = Renderer(settings.tz, tx_explorer_url=settings.tx_explorer_url)
  bot = DDHelperBot(settings, http, helper, state, renderer)
  assert settings.discord_token  # noqa: S101
  bot.run(settings.discord_token, log_handler=None)
