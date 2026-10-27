# Changelog

## Unreleased (2026-10-27)

### Fixed
- `/floor` and the daily digest now flag a floor shown next to **0 listed**. The official stats
  endpoint keeps reporting the last floor price after every listing is gone, so the floor isn't
  something anyone can buy at. A live `dry-run floor` on 2026-10-27 showed exactly this:
  47,000 DOGE with 0 listed. Covered by a test in `tests/test_render.py`.

### Added
- `.gitleaksignore` covering two X API `next_token` pagination values in recorded fixtures
  (`tests/fixtures/x_tweets_*.json`). They are not credentials. With it in place, `gitleaks git`
  and `gitleaks dir` both report no leaks.
