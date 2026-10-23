# Test fixtures

Real responses recorded on **2026-10-23 around 11:56 AM ET** (one request each,
identifying User-Agent). Nothing here is synthetic.

| File | Source |
|---|---|
| `market_stats.json` | `market.doginaldogs.com/api/trpc/listings.getStats` (unofficial, undocumented) |
| `market_activity_page1.json`, `market_activity_page2.json` | `.../activity.getGlobal` with `{"limit":50}` and the returned cursor |
| `market_floor_7d.json` | `.../listings.getHistoricalFloorPrice` with `{"timeRange":"7d"}` |
| `doggy_collection.json` | `https://api.doggy.market/nfts/doginaldogs` |
| `ddl_cards_subset.json` | 8 of the 111 cards from `https://ddltcg.com/data/cards.json` (allowed by robots.txt). Trimmed to keep the redistributed copy minimal; card data © Doginal Dogs. |
| `x_users_by.json`, `x_tweets_*.json` | X API v2 `GET /2/users/by` and `GET /2/users/:id/tweets` (`exclude=retweets,replies`), recorded through a read-only X API v2 proxy. The proxy-added per-post `url` field was removed; everything else is as returned. `x_tweets_DDLTCG.json` is genuinely empty (no original posts since Oct 16). |

The market activity files contain public Dogecoin wallet addresses as returned by
the API. The bot never displays addresses.
