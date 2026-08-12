"""Point-in-time correctness primitives (architecture v1.0 §04, rule 19).

Every data point that can feed a trading decision or a backtest carries enough
timestamps to answer "what did the system know at that point in time?" and to
let the Backtest Engine filter out anything that would not actually have been
knowable yet — the standard way look-ahead bias creeps into a backtest.

Two mixins, because two different things get confused if merged into one:

- `ProvenanceFields` — general audit trail for any stored value: who supplied
  it, when it happened, when it entered the system.
- `PeriodicRecordFields` — the fundamentals/estimates-specific distinction
  between the period a number *describes* and when it was *published*.
"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class ProvenanceFields(BaseModel):
    """Attach to any DTO that a backtest or an audit trail might need to trust."""

    source: str
    observed_at: datetime | None = None
    effective_at: datetime | None = None
    # The only field the Backtest Engine is allowed to filter on. If a query
    # needs "what did we know as of date X", it compares X against this.
    available_at: datetime
    ingested_at: datetime | None = None
    raw_payload: dict[str, Any] | None = None


class PeriodicRecordFields(BaseModel):
    """For quarterly/periodic data (fundamentals, analyst estimates) where the
    period described and the publish date are never the same thing."""

    period_end: date
    reported_at: date
    available_at: datetime
