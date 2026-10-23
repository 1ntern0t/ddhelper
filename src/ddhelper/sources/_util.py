from __future__ import annotations

from datetime import UTC, datetime


def parse_iso(ts: str | None) -> datetime | None:
  """Parse an ISO-8601 timestamp (with trailing Z) into an aware UTC datetime."""
  if not ts:
    return None
  try:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
  except ValueError:
    return None
  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=UTC)
  return dt.astimezone(UTC)
