from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any


def parse_iso(ts: Any) -> datetime | None:
  """Parse an ISO-8601 timestamp (with trailing Z) into an aware UTC datetime."""
  if not ts or not isinstance(ts, str):
    return None
  try:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
  except ValueError:
    return None
  if dt.tzinfo is None:
    dt = dt.replace(tzinfo=UTC)
  return dt.astimezone(UTC)


def finite_float(v: Any) -> float:
  """float(v), rejecting NaN/inf (json.loads accepts them). Raises TypeError/ValueError."""
  if isinstance(v, bool):
    raise TypeError("expected a number, got a bool")
  f = float(v)
  if not math.isfinite(f):
    raise ValueError(f"non-finite number: {v!r}")
  return f
