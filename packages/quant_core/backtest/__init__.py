"""Point-in-time query helpers for the Backtest Engine — the only place allowed to filter by
available_at for historical simulation (architecture v1.0, rule 19). A minimal version is part of
the MVP thin-slice (decision #1); walk-forward optimization and transaction-cost modeling are
Phase 2 depth.

`latest_eligible` below is the pure-Python primitive Wealth Engine (Phase 1B) actually calls —
the same `available_at <= as_of` invariant, applied without a live storage layer, per the Phase 1B
implementation spec §10.1's mixed-cadence reconciliation decision. `as_of_filter` remains a Phase 1
stub (SQL query-fragment generation needs the storage layer that doesn't exist yet) — Wealth Engine
does not depend on it."""

from collections.abc import Callable, Iterable, Sequence
from datetime import date, datetime
from typing import TypeVar

T = TypeVar("T")


def as_of_filter(available_at_column: str, as_of: object) -> object:
    """Point-in-time predicate builder: available_at <= as_of. Returns a query filter fragment
    once the storage layer for the relevant table exists (Phase 1)."""
    raise NotImplementedError("Backtest Engine (minimal) — Phase 1, needs a storage layer")


def latest_eligible(
    records: Iterable[T],
    as_of: datetime | date,
    key: Callable[[T], datetime | date],
) -> T | None:
    """"What would we have known as of this date" for one entity's time series of point-in-time
    records: the record with the latest `key(record)` that is still <= `as_of`. Returns None if
    nothing was eligible yet.

    `key` is a caller-supplied accessor (usually `lambda r: r.available_at`) so this one function
    covers both `PeriodicRecordFields`-based DTOs (IncomeStatement, BalanceSheet,
    CashFlowStatement, FundamentalsRecord) and any other point-in-time-stamped record, without
    assuming a specific attribute name.
    """
    eligible = [r for r in records if key(r) <= as_of]
    if not eligible:
        return None
    return max(eligible, key=key)


def latest_price_as_of(bars: Sequence, as_of: date):
    """Reconciliation for the one mixed-cadence case where the earlier side has no explicit
    `available_at`: this function keys on `ts` only.

    NOTE (Market Data Foundation Phase 1): `OHLCVBar` now carries a real `available_at` field —
    the "reversible later" this docstring originally flagged has happened. This function was
    NOT updated to key on `available_at`, and must not be assumed PIT-correct against bars that
    have one: it still filters on `.ts`, which would silently ignore a bar's real publication
    vintage. It remains valid only for the narrower case it was built for (a bar list with no
    vintage timestamp at all). PIT retrieval against the new `available_at` field lives in
    `packages.storage.repositories.prices_repository` (SQL-side, same
    `available_at <= as_of` invariant, applied via the correct field) — see that module's
    docstring for the full reasoning."""
    return latest_eligible(bars, as_of, key=lambda bar: bar.ts)

