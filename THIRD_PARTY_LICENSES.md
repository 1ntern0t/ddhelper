# Third-party licenses

ddhelper itself is MIT-licensed (see `LICENSE`). It does **not** vendor or modify any
third-party code; dependencies are installed from PyPI and keep their own license
files (in each package's `*.dist-info/` directory, including inside the Docker image).

Runtime dependencies (versions the tests were run against, collected with `pip-licenses`):

| Package | Version | License | Project |
|---|---|---|---|
| discord.py | 2.7.1 | MIT | https://github.com/Rapptz/discord.py |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | https://github.com/aio-libs/aiohttp |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | https://github.com/aio-libs/aiohappyeyeballs |
| aiosignal | 1.4.0 | Apache-2.0 | https://github.com/aio-libs/aiosignal |
| attrs | 26.1.0 | MIT | https://github.com/python-attrs/attrs |
| frozenlist | 1.8.0 | Apache-2.0 | https://github.com/aio-libs/frozenlist |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| multidict | 7.1.0 | Apache-2.0 | https://github.com/aio-libs/multidict |
| propcache | 0.5.4 | Apache-2.0 | https://github.com/aio-libs/propcache |
| yarl | 1.25.1 | Apache-2.0 | https://github.com/aio-libs/yarl |
| audioop-lts (Python ≥ 3.13 only) | 0.2.2 | PSF-2.0 | https://github.com/AbstractUmbra/audioop |

Development only (not shipped): pytest (MIT), pytest-asyncio (Apache-2.0), ruff (MIT).

If you redistribute a bundle that includes these packages (e.g. a Docker image),
keep their license and NOTICE files intact; Apache-2.0 requires it.

## Data

- DDL TCG card data and card images are © Doginal Dogs. The bot links to the
  official files on ddltcg.com; `tests/fixtures/ddl_cards_subset.json` holds 8 cards
  for testing only.
- Market data belongs to its respective operators (market.doginaldogs.com,
  doggy.market). X content belongs to its authors and is subject to the X Developer
  Agreement.
