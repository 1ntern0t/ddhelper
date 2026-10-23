# Proposal: ddhelper, a read-only helper bot for the Doginal Dogs Discord

*From @1nternot (builder and holder). One page for the mod team. Nothing goes live without your approval.*

## What it does
- **Sales alerts in Discord.** Each new sale on market.doginaldogs.com is posted once to one channel you choose: dog #, DOGE price, and tx link. Sales recorded without an on-chain tx id are clearly flagged.
- **Floor-move alerts.** Posted only on meaningful moves (default ±10% and ≥2,000 DOGE, at most once an hour).
- **`/floor`**: official floor, listings, 24h/7d volume, plus a Doggy Market comparison that warns when its listings look stale.
- **`/sales`**: the last few sales. **`/card renza`**: DDL TCG card lookup from ddltcg.com's official card list.
- **Daily digest**, once a day, in one channel: market summary, posts from @doginaldogs / @DDLTCG / @barkmeta, Bark's daily Space, @DDSalesBot activity, and upcoming events (e.g. DDMIAMI, Dec 7–9). `/digest` shows it privately on demand.

It complements @DDSalesBot (X only), the DDL Companion and Legends Brackets. It doesn't replace them.

## Opt-in and control
- You choose the channel(s), or none at all. Alerts and the scheduled digest are each off unless a channel is configured.
- Slash commands are registered to this server only. You can restrict them by role or channel under *Server Settings → Integrations*.
- Trial first: a private test server or a single mod-only channel, then expand if you like it. Kick it any time; it keeps nothing in your server.

## Read-only, minimal permissions
- Permissions: **View Channel + Send Messages** only (integer 3072). No admin, no manage-anything, no reactions, no roles.
- Intents: **GUILDS only**. It **cannot read messages** (no Message Content intent), and it doesn't see the member list or presences.
- It never pings: `allowed_mentions` is none, and `@everyone`/`@here` in upstream text is neutralised.
- **No DMs**, ever. No wallet connections, no links asking anyone to sign anything, no trading features.

## Data handling
- Inputs: public market data, public X posts, the public DDL card list, and a hand-edited events file. Nothing from Discord is stored.
- Stored: a small local SQLite file holding ids of sales already posted (dedupe), the last floor baseline, and the date of the last digest. No user data, no message logs, no wallet addresses shown.
- Secrets (bot token, X token) are kept in environment variables, never in code or logs.
- It is a polite client: identifying User-Agent, polling every 5 minutes, caching, backoff on errors.

## What I'm asking the team
1. Is a bot like this welcome, and in which channel(s)?
2. The market site's data comes from **internal, undocumented endpoints**. May the bot use them at a 5-minute cadence, or is there an approved feed or API you'd prefer?
3. Anything you'd want changed or added (trait filters, tournament reminders, DDMiami FAQ)?

Open source (MIT). Happy to hand over hosting or the bot application to the team if you prefer.
