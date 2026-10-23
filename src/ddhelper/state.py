"""Small SQLite state store: seen sales (dedupe), key/value (baselines, last digest)."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_sales (
  sale_id INTEGER PRIMARY KEY,
  seen_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
"""


class State:
  def __init__(self, path: str | Path):
    self.path = str(path)
    if self.path != ":memory:":
      Path(self.path).parent.mkdir(parents=True, exist_ok=True)
    self._db = sqlite3.connect(self.path)
    self._db.execute("PRAGMA journal_mode=WAL")
    self._db.executescript(_SCHEMA)
    self._db.commit()

  def close(self) -> None:
    self._db.close()

  # seen sales
  def filter_unseen(self, ids: Iterable[int]) -> list[int]:
    ids = list(ids)
    if not ids:
      return []
    # Only "?" placeholders are interpolated; values are bound parameters.
    sql = "SELECT sale_id FROM seen_sales WHERE sale_id IN (" + ",".join("?" * len(ids)) + ")"  # noqa: S608
    seen = {r[0] for r in self._db.execute(sql, ids)}
    return [i for i in ids if i not in seen]

  def mark_seen(self, ids: Iterable[int]) -> None:
    now = time.time()
    self._db.executemany(
      "INSERT OR IGNORE INTO seen_sales(sale_id, seen_at) VALUES (?, ?)", [(i, now) for i in ids]
    )
    self._db.commit()

  def prune_seen(self, keep_seconds: float = 90 * 86400) -> None:
    self._db.execute("DELETE FROM seen_sales WHERE seen_at < ?", (time.time() - keep_seconds,))
    self._db.commit()

  # kv
  def get(self, key: str, default: Any = None) -> Any:
    row = self._db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default

  def set(self, key: str, value: Any) -> None:
    self._db.execute(
      "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?) "
      "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
      (key, json.dumps(value), time.time()),
    )
    self._db.commit()
