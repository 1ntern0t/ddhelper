# ddhelper: Doginal Dogs community helper bot (v1)

A small, **read-only** Discord bot for the Doginal Dogs community. It fills two gaps:
no daily digest of announcements, Spaces and events, and no Discord-native sales and
floor alerts (@DDSalesBot posts to X only). It complements the existing tools
(@DDSalesBot, the DDL Companion, legendsbrackets.com) and does not replace them.

## Features

| Command / job | What it does |
|---|---|
| `/floor` | Official floor, listed count, 30d stats, 24h and 7d volume (computed from the sales feed, with how many sales lack a tx id), and a Doggy Market comparison with staleness warnings |
| `/sales [n]` | The latest *n* (1–10) official-market sales with tx id + explorer link. Sales with no tx id are flagged as manually recorded |
| `/card <name>` | DDL TCG card lookup by name, partial name, fuzzy name or serial (`V52`, `V052`), with autocomplete and the official card render |
| `/digest` | On-demand digest, visible only to the caller |
| Daily digest | Posted at `DIGEST_TIME` (default 09:00 ET) to `DIGEST_CHANNEL_ID`: market summary, floor change 24h/7d, top sales, X posts from tracked accounts (last 24h), upcoming events from `config/events.toml`, plus a **Gaps** section listing any source that was down |
| Sales alerts | Polls every `SALES_POLL_SECONDS` (default 300). New sales are deduped in SQLite. The first run only seeds state, so it never floods the channel |
| Floor-move alerts | Fires when the floor moves ≥ `FLOOR_ALERT_PCT` (default 10%) **and** ≥ `FLOOR_ALERT_MIN_DOGE` from the last alerted level, at most once per cooldown |
| `dry-run` CLI | `python -m ddhelper dry-run floor\|sales\|digest\|card <name>\|alerts` fetches live data and prints exactly what would be posted. No Discord token needed |

All posts use `allowed_mentions=none`, suppress link previews, and neutralise
`@everyone`/`@here` and `<@…>` in upstream text. The bot never DMs anyone and never
reads messages.

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e '.[dev]'
cp .env.example .env            # optional for dry-run
python -m ddhelper dry-run floor
python -m ddhelper dry-run sales -n 5
python -m ddhelper dry-run digest
python -m ddhelper dry-run card renza
python -m ddhelper dry-run alerts   # simulate two poll cycles with throwaway state
pytest -q && ruff check . && ruff format --check .
```

Run the bot: fill in `.env`, run `python -m ddhelper check-config`, then `python -m ddhelper run`.
Docker: `docker build -t ddhelper . && docker run --env-file .env -v ddhelper-data:/app/data ddhelper`.
systemd: see `deploy/ddhelper.service` (hardened unit, state in `/var/lib/ddhelper`).

## Configuration

Everything is set through environment variables; see `.env.example` for the full list.
Key ones:

- `DISCORD_TOKEN`, `DISCORD_GUILD_ID`: required for `run`. Commands are registered to that guild only, never globally.
- `ALERT_CHANNEL_ID`, `DIGEST_CHANNEL_ID`: leave empty to disable alerts or the scheduled digest.
- `X_BEARER_TOKEN`: X API v2 app-only token. Optional. Without it the digest says
  *"X posts not included: X_BEARER_TOKEN is not set."*
- `SALES_POLL_SECONDS`, `FLOOR_POLL_SECONDS`: default 300, minimum 60.
- `FLOOR_ALERT_PCT`, `FLOOR_ALERT_MIN_DOGE`, `FLOOR_ALERT_COOLDOWN_SECONDS`.
- `CARD_SOURCE=official|local`, `CARD_FILE`.
- `EVENTS_FILE`: a TOML list of events. Ships with DDMIAMI 2026 (Dec 7–9, Wynwood) and
  Bark's daily 5 PM ET Space, which is labelled as an observed pattern, not an official
  schedule. Add tournaments by hand; see the comments in the file.

## Discord setup

1. Create an application at https://discord.com/developers/applications and add a bot.
   Leave **all privileged intents off** (no Message Content, Server Members or Presence).
   The bot uses only the non-privileged `GUILDS` intent.
2. Invite URL template (replace `APPLICATION_ID`):

   ```
   https://discord.com/oauth2/authorize?client_id=APPLICATION_ID&scope=bot%20applications.commands&permissions=3072
   ```

   `3072` = **View Channel** (1024) + **Send Messages** (2048). Nothing else is needed.
   Slash-command replies use the interaction webhook. Mods can restrict the bot further
   with channel overrides, e.g. allow Send Messages only in the alert and digest channels.
3. Optionally, use *Server Settings → Integrations → ddhelper* to limit which roles or
   channels can use each command.

## Data sources and caveats

| Source | Used for | Status on 2026-10-23 | Caveat |
|---|---|---|---|
| market.doginaldogs.com `/api/trpc/listings.getStats`, `activity.getGlobal`, `listings.getHistoricalFloorPrice` | Floor, listed, volume, sales, floor history | ✅ worked | **Undocumented internal endpoints** the site's own frontend uses (found by reading its JS bundle). Not a public API; they may change or break without notice. **Ask the Doginal Dogs team (via Discord ticket) before relying on them** and switch to an official API if they offer one. Many sales have `isManual: true` and no `txid`; the bot flags these as unverified. One recorded row had a null price and is skipped. |
| api.doggy.market `/nfts/doginaldogs` | Secondary-venue comparison | ✅ worked | Floor was ~50% below the official floor, with 1 trade in 7d. Shown only with staleness warnings. |
| X API v2 (`/2/users/by`, `/2/users/:id/tweets`) | Digest posts from @doginaldogs, @barkmeta, @DDLTCG, @DDSalesBot | ⚠️ not tested live by the bot (no token on the build box) | Needs a bearer token. Logic is tested against real recorded responses. @barkmeta posts are keyword-filtered because most are general crypto/AI commentary. @DDSalesBot posts are only counted. User ids are cached; timelines are cached 10 min. 429s are honoured via `x-rate-limit-reset`. |
| ddltcg.com `/data/cards.json` | `/card` | ✅ worked (111 cards) | The official gallery's own data file, explicitly `Allow`ed in robots.txt. Fetched at most once per 6h. Card data and images © Doginal Dogs. |
| ddltcg.kushmetax.com (DDL Companion) | not used | ⛔ robots.txt `Disallow: /` | Not fetched. Collaborate with @KushMetaX instead. |
| legendsbrackets.com | not used | no public API found | Add tournaments to `config/events.toml` manually. |

If the official file moves, set `CARD_SOURCE=local` and point `CARD_FILE` at a JSON
file in the same schema: a list of objects with `id`, `name`, `class`, `type`,
`rarity`, `mana`, `attack`, `hp`, `keywords`, `description`. `{"cards": [...]}` also works.

### Polite-client behaviour

- The User-Agent identifies the bot: `ddhelper/0.1.0 (Doginal Dogs community helper bot; read-only; +https://x.com/1nternot)`.
- Polling defaults to 5 minutes (60 s floor). Slash commands share cached results
  (60 s for market data, 2 min Doggy, 6 h cards), so many users running `/floor` at once
  still cost only about three upstream requests per minute. Per-user cooldown is 10 s (60 s for `/digest`).
- At least 1 s between requests to the same host. Timeouts are 15 s. Up to 3 retries
  with jittered exponential backoff on network errors, timeouts and 5xx.
- 429: `Retry-After` / `x-rate-limit-reset` is honoured. If the wait is over 60 s the
  host is backed off and the cycle is skipped instead of blocking.
- When a source is down, the bot degrades gracefully: `/floor` shows what it has, and the
  digest lists the gap.

## Security

- Secrets live in env vars only. `Settings.__repr__` hides tokens, `.env` is git-ignored,
  the Docker image contains no secrets, and the systemd unit reads a root-owned `0600` env file.
- No token or `Authorization` header is ever logged. aiohttp debug logging is kept at WARNING.
- Least-privilege intents (`GUILDS` only) and permissions (3072). Commands are guild-scoped.
- Input validation: `/card` accepts 1–40 characters `[A-Za-z0-9 '\-.]` after NFKC
  normalisation. `/sales n` is range-checked by Discord (1–10) and clamped again server-side.
  Config values are range-checked, and X usernames are checked against `^[A-Za-z0-9_]{1,15}$`.
- SQLite uses bound parameters only. Wallet addresses from the market feed are never displayed.

## Getting mod approval

1. Join the server (discord.gg/doginaldogs), read #rules and onboarding, and open a
   **ticket**. The market contact page routes partnership and business requests through
   Discord. Share `PROPOSAL.md`.
2. Ask specifically: (a) is a community bot welcome, (b) may it use the market's internal
   endpoints or is there an approved feed, and (c) which channels, if any.
3. Offer a trial in a private test server first, or in a single mod-only channel.
   Mods keep full control through channel overrides and Integrations settings, and can
   kick the bot at any time. The bot needs no admin rights.

## Development

- Python 3.11+. Code uses **two-space indentation** (enforced by `ruff format`, `indent-width = 2`).
- `pytest -q` runs offline. It uses real recorded responses in `tests/fixtures/` (see
  its README) and a local aiohttp server for retry/backoff/rate-limit tests.
- Layout: `src/ddhelper/{config,http,state,service,render,events,bot,cli}.py`,
  `src/ddhelper/sources/{market,doggy,xapi,cards}.py`.

## Author

Built by xirion. GitHub [@1ntern0t](https://github.com/1ntern0t), X [@1nternot](https://x.com/1nternot). Ideas, bug reports and PRs welcome.

## License

MIT © 2026 xirion. Dependency licenses are listed in `THIRD_PARTY_LICENSES.md`.
Not affiliated with or endorsed by Doginal Dogs.
