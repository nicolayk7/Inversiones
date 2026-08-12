"""Point-in-time repository for the canonical daily-bar DTO (`packages.shared.schemas.OHLCVBar`).

Same shape of contract as `fundamentals_repository`: callers get back canonical DTOs, never SQL;
`available_at <= as_of` is the only cutoff a query is allowed to apply.

PIT DECISION — why this module does NOT call
`packages.quant_core.backtest.latest_price_as_of` (read before changing this file):

That helper's own docstring names the exact case it was built for: "OHLCVBar (Phase 0 schema)
carries only `ts` ... treat `ts` as both the effective and the available date for EOD price
data — reversible later if OHLCVBar grows a real `available_at`." Market Data Foundation Phase 1
did exactly that — `OHLCVBar` now carries a real `available_at` (see its docstring). Calling
`latest_price_as_of(bars, as_of)` against bars that *do* have a real `available_at` would silently
keep filtering on `.ts` and ignore `.available_at` entirely — reintroducing the exact look-ahead
bug `available_at <= as_of` exists to prevent (e.g. a same-day bar published after `as_of` would
still be treated as knowable, because `ts <= as_of` alone would pass).

This is not "Quant Core is broken" — `latest_eligible`/`latest_price_as_of` remain correct for
their documented, narrower purpose (reconciling an in-memory bar list that genuinely has no
vintage timestamp). It means that purpose no longer matches this repository's data, which does
have one. The resolution applied here is mechanical, not invented: the same generic primitive
`latest_eligible` already accepts an arbitrary `key`; the correct call for this schema would be
`latest_eligible(bars, as_of, key=lambda b: b.available_at)`, not the `.ts`-keyed convenience
wrapper. In practice this repository applies that identical invariant as a SQL window function
instead (see `_latest_known_bar_stmt` below) — the same `(partition by period identifier, order by
available_at desc, keep rank 1)` shape `fundamentals_repository` already uses, adapted to `ts` as
the period identifier — because the data lives in Postgres and pulling every row into Python to
run a pure-Python primitive would be strictly worse for no PIT-correctness benefit. No new PIT
rule is introduced; `available_at <= as_of` is the only invariant applied, exactly as elsewhere.

Quant Core itself was not modified beyond a documentation note pointing here (see
`packages/quant_core/backtest/__init__.py`) — no logic change, since none was necessary.
"""

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.schemas import OHLCVBar
from packages.storage.models.prices import PriceBarModel


def _latest_known_bar_stmt(ticker: str, as_of: datetime, limit: int | None) -> Select:
    ranked = (
        select(
            PriceBarModel,
            func.row_number()
            .over(partition_by=PriceBarModel.ts, order_by=PriceBarModel.available_at.desc())
            .label("_rank"),
        )
        .where(PriceBarModel.ticker == ticker, PriceBarModel.available_at <= as_of)
        .subquery()
    )
    stmt = (
        select(PriceBarModel)
        .select_from(ranked)
        .join(PriceBarModel, PriceBarModel.id == ranked.c.id)
        .where(ranked.c._rank == 1)
        .order_by(PriceBarModel.ts.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt


def _bar_row(dto: OHLCVBar) -> dict:
    return {
        "ticker": dto.ticker,
        "ts": dto.ts,
        "available_at": dto.available_at,
        "source": dto.source,
        "open": dto.open,
        "high": dto.high,
        "low": dto.low,
        "close": dto.close,
        "volume": dto.volume,
    }


def _bar_dto(row: PriceBarModel) -> OHLCVBar:
    return OHLCVBar(
        ticker=row.ticker, ts=row.ts, open=row.open, high=row.high, low=row.low,
        close=row.close, volume=row.volume, available_at=row.available_at, source=row.source,
    )


async def save_daily_bars(session: AsyncSession, bars: list[OHLCVBar]) -> None:
    """Upsert on `(ticker, ts, source, available_at)` — idempotent re-ingestion of the same
    vintage; a corrected print of the same trading day from the same source with a *different*
    `available_at` lands as a new row (never overwrites the earlier vintage)."""
    if not bars:
        return
    rows = [_bar_row(b) for b in bars]
    stmt = pg_insert(PriceBarModel).values(rows)
    unique_cols = ("ticker", "ts", "source", "available_at")
    update_cols = {c: getattr(stmt.excluded, c) for c in rows[0] if c not in unique_cols}
    stmt = stmt.on_conflict_do_update(index_elements=list(unique_cols), set_=update_cols)
    await session.execute(stmt)
    await session.commit()


async def get_price_as_of(session: AsyncSession, ticker: str, as_of: datetime) -> OHLCVBar | None:
    """The single most recent trading day's bar knowable as of `as_of` — i.e. the latest `ts`
    among rows whose `available_at <= as_of`, using each such `ts`'s most recent known vintage.
    Returns None if nothing is eligible yet (never falls back to a future or fabricated value)."""
    stmt = _latest_known_bar_stmt(ticker, as_of, limit=1)
    result = await session.execute(stmt)
    row = result.scalars().first()
    return _bar_dto(row) if row is not None else None
