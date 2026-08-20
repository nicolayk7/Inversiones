"""Explicitly separate ingestion/retrieval flows connecting live data to the Wealth Engine — no
Provider -> Engine shortcut (architecture v1.0 §04's dependency direction; continuity brief's
"regla principal"):

- `ingest_fundamentals`: FundamentalsProvider -> canonical DTO -> `fundamentals_repository.save_*`
  -> PostgreSQL. Only function in this module that touches a `FundamentalsProvider`.
- `ingest_price`: MarketDataProvider -> canonical DTO -> `prices_repository.save_daily_bars` ->
  PostgreSQL. Only function in this module that touches a `MarketDataProvider` (Market Data
  Foundation Phase 4) — same shape as `ingest_fundamentals`, deliberately, not a new pattern.
- `ingest_quarterly_revenue`: FundamentalsProvider's `get_quarterly_revenue` (Phase 7B) ->
  canonical `IncomeStatement` DTOs -> `fundamentals_repository.save_income_statements` ->
  PostgreSQL (Phase 7C-1). Same ingestion-only pattern as the two above.
- `build_wealth_engine_input_from_storage`: PostgreSQL -> `fundamentals_repository.get_*` +
  `prices_repository.get_price_as_of` (each independently point-in-time, `available_at <= as_of`)
  -> canonical DTOs -> `WealthEngineInput`. Never imports or calls a provider — retrieval is
  provider-agnostic by construction, not by convention; there is no code path in this function
  that could reach `SecEdgarFundamentalsProvider` or `MassiveMarketDataProvider`. Phase 7C-1 adds
  `trailing_yoy_growth_rates` to this same retrieval-only contract, built from whatever quarterly
  data `ingest_quarterly_revenue` has already persisted — never fabricated when absent.
"""

from datetime import date, datetime, time, timezone

from sqlalchemy.ext.asyncio import AsyncSession

import packages.quant_core.fundamentals as qf
from packages.engines.wealth_engine.pipeline import WealthEngineInput
from packages.providers.fundamentals.sec_edgar import SecEdgarFundamentalsProvider
from packages.providers.market.massive import MassiveMarketDataProvider
from packages.quant_core.regime import SectorProfile
from packages.storage.repositories import fundamentals_repository as repo
from packages.storage.repositories import prices_repository

# Distinct source tag for quarterly IncomeStatement rows sharing the same table as annual ones —
# see ingest_quarterly_revenue's docstring for why this distinction is load-bearing, not cosmetic:
# fundamentals_repository's PIT retrieval dedups strictly by (ticker, period_end), with no
# source-aware partitioning, so quarterly rows must be explicitly excluded/included client-side by
# every caller that needs one and not the other (both build_wealth_engine_input_from_storage's
# annual retrieval and _trailing_quarterly_revenue_yoy_growth's quarterly retrieval do this).
_QUARTERLY_SOURCE = "sec_edgar_quarterly"


async def ingest_fundamentals(
    ticker: str, session: AsyncSession, *, provider: SecEdgarFundamentalsProvider | None = None
) -> None:
    """Fetches current + prior full-fiscal-year statements from SEC EDGAR and persists them.
    Idempotent — re-ingesting the same filings upserts on `(ticker, period_end, source,
    reported_at)`, it does not duplicate rows (see `fundamentals_repository._upsert`)."""
    owns_provider = provider is None
    provider = provider or SecEdgarFundamentalsProvider()
    try:
        income_statements = provider.get_income_statements(ticker)
        balance_sheets = provider.get_balance_sheets(ticker)
        cash_flow_statements = provider.get_cash_flow_statements(ticker)
    finally:
        if owns_provider:
            provider.close()

    await repo.save_income_statements(session, income_statements)
    await repo.save_balance_sheets(session, balance_sheets)
    await repo.save_cash_flow_statements(session, cash_flow_statements)


async def ingest_price(
    ticker: str,
    start: date,
    end: date,
    session: AsyncSession,
    *,
    provider: MassiveMarketDataProvider | None = None,
) -> None:
    """Fetches daily bars for [start, end] from Massive and persists them. Idempotent —
    re-ingesting the same range upserts on `(ticker, ts, source, available_at)`, it does not
    duplicate rows (see `prices_repository.save_daily_bars`). Pure ingestion: no scoring, no
    Wealth Engine call — mirrors `ingest_fundamentals` exactly, same owns-provider pattern, no
    second HTTP client stood up here."""
    owns_provider = provider is None
    provider = provider or MassiveMarketDataProvider()
    try:
        bars = provider.get_daily_bars(ticker, start, end)
    finally:
        if owns_provider:
            provider.close()

    await prices_repository.save_daily_bars(session, bars)


async def ingest_quarterly_revenue(
    ticker: str,
    session: AsyncSession,
    *,
    num_quarters: int = 24,
    provider: SecEdgarFundamentalsProvider | None = None,
) -> None:
    """Fetches Phase 7B's quarterly Revenue series and persists Q1/Q2/Q3 only — Q4 is
    deliberately excluded here (Phase 7C-1 scope decision, not a Phase 7B limitation).

    Why: Q4's `period_end` always coincides exactly with its fiscal year's own `period_end` (the
    fourth quarter ends when the fiscal year ends). `fundamentals_repository`'s point-in-time
    retrieval dedups strictly by `(ticker, period_end)` — it has no `source`-aware partitioning,
    by design, since nothing before this phase ever needed two independently-sourced rows for the
    same period_end. Persisting Q4 there would create exactly that: a second row competing with
    the annual `IncomeStatement` already stored under `ingest_fundamentals` for the identical
    period_end, and the existing repository could arbitrarily surface either one to every OTHER
    caller of `get_income_statements` (including the main Quality/FCF/Growth retrieval path this
    phase must not disturb). Persisting Q4 safely would need a schema-level cadence discriminator
    — out of this phase's authorized scope (no Storage/Repository changes). Q1/Q2/Q3 carry no such
    risk: their period_ends never coincide with any fiscal year end (verified against real AAPL
    data across 8 fiscal years), so they coexist safely with annual rows under the existing
    per-period_end dedup.

    Persisted under `source="sec_edgar_quarterly"` — distinct from `ingest_fundamentals`'s
    `"sec_edgar"` — so `save_income_statements`'s upsert key `(ticker, period_end, source,
    reported_at)` never collides with an annual row even in the (unobserved) case of a shared
    period_end; retrieval separates the two by filtering on this same field, in Python, after the
    existing `get_income_statements` call — no repository change needed.
    """
    owns_provider = provider is None
    provider = provider or SecEdgarFundamentalsProvider()
    try:
        quarters = provider.get_quarterly_revenue(ticker, num_quarters=num_quarters)
        fiscal_year_ends = {fy["end"] for fy in provider._full_fiscal_years(ticker)}
    finally:
        if owns_provider:
            provider.close()

    non_q4 = [q for q in quarters if q.period_end.isoformat() not in fiscal_year_ends]
    relabeled = [q.model_copy(update={"source": _QUARTERLY_SOURCE}) for q in non_q4]

    await repo.save_income_statements(session, relabeled)


def _end_of_day_utc(d: date) -> datetime:
    # Mirrors SecEdgarFundamentalsProvider._available_at's end-of-day-UTC convention for a plain
    # date cutoff — "as of this date" means "everything knowable by the end of that date".
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


async def _trailing_quarterly_revenue_yoy_growth(
    session: AsyncSession, ticker: str, as_of_cutoff: datetime
) -> list[float] | None:
    """Growth Consistency's input series (methodology §3: "trailing 5yr quarterly stddev of YoY
    growth"; Decision 1 of the Growth Trailing Decision Audit: Revenue). Reads whatever
    `ingest_quarterly_revenue` has already persisted (`source="sec_edgar_quarterly"`) — never
    calls a provider, same retrieval-only contract as the rest of this function. Returns `None`
    if nothing has been ingested, or if fewer than 2 YoY comparisons can be formed — never a
    fabricated or partially-filled series (continuity brief §8).

    Pairing rule: each quarter is matched against the closest OTHER retrieved quarter whose
    `period_end` falls 340-390 days earlier — the same "same quarter, one year earlier" concept
    `_full_fiscal_years`/`get_quarterly_revenue` already use, tolerant of Apple-style 52/53-week
    fiscal calendars (Phase 7B audit). The math itself is `packages.quant_core.fundamentals.
    yoy_growth`, unchanged — this function only assembles which pairs to feed it.
    """
    quarterly = await repo.get_income_statements(session, ticker, as_of_cutoff, limit=None)
    quarterly = sorted(
        (q for q in quarterly if q.source == _QUARTERLY_SOURCE), key=lambda q: q.period_end
    )
    if len(quarterly) < 2:
        return None

    rates: list[float] = []
    for i, current in enumerate(quarterly):
        candidates = [
            prior for prior in quarterly[:i]
            if 340 <= (current.period_end - prior.period_end).days <= 390
        ]
        if not candidates:
            continue
        prior = max(candidates, key=lambda p: p.period_end)
        result = qf.yoy_growth(current.revenue, prior.revenue, name="Quarterly Revenue YoY")
        if result.is_ok:
            rates.append(result.value)

    return rates or None


async def build_wealth_engine_input_from_storage(
    ticker: str,
    sector: SectorProfile,
    as_of: date,
    session: AsyncSession,
    *,
    price: float | None = None,
) -> WealthEngineInput:
    """Retrieval-only: reads point-in-time statements already persisted by `ingest_fundamentals`
    and (if not overridden by the caller) the point-in-time price persisted by `ingest_price`.
    Raises if fewer than 1 fiscal year of fundamentals is in storage for `ticker` as of `as_of` —
    this function never falls back to fetching from a provider.

    `price`: explicit override, unchanged from before this phase (e.g. for tests supplying a
    synthetic price without touching Storage). When left `None` (the default — no override), the
    point-in-time price is looked up via `prices_repository.get_price_as_of`; if none is eligible
    yet, `price` stays `None` — never fabricated, never forward-filled from a later or default
    value (continuity brief §8).

    Phase 7C-1 correctness note: `fundamentals_repository.get_income_statements` dedups strictly
    by `(ticker, period_end)`, with no awareness of `source` — since `ingest_quarterly_revenue`
    now also writes into `income_statements` (Q1/Q2/Q3, more recent period_ends than a prior
    fiscal year's), a plain `limit=2` call here would silently pick up a quarterly row as the
    "prior" annual statement instead of the true prior fiscal year (its `period_end` sorts more
    recently) — corrupting Quality/FCF/Growth's YoY sub-metrics with an annual-vs-quarterly
    mismatch. Fetched with a generous limit and filtered to exclude `_QUARTERLY_SOURCE` client-side
    (not restricted to `_ANNUAL_SOURCE` specifically — callers/tests may legitimately use other
    non-quarterly source labels, e.g. synthetic fixtures; only the quarterly rows are the ones
    that must never be mistaken for an annual statement) — exactly the same technique
    `_trailing_quarterly_revenue_yoy_growth` uses for the reverse filter — no repository change
    needed for either direction."""
    as_of_cutoff = _end_of_day_utc(as_of)

    income_statements_all = await repo.get_income_statements(session, ticker, as_of_cutoff, limit=None)
    income_statements = [s for s in income_statements_all if s.source != _QUARTERLY_SOURCE][:2]
    balance_sheets = await repo.get_balance_sheets(session, ticker, as_of_cutoff, limit=2)
    cash_flow_statements = await repo.get_cash_flow_statements(session, ticker, as_of_cutoff, limit=2)

    if not income_statements or not balance_sheets or not cash_flow_statements:
        raise ValueError(
            f"No statements in storage for {ticker!r} as_of={as_of} — "
            "call ingest_fundamentals(ticker, session) first"
        )

    current_income, prior_income = income_statements[0], (income_statements[1] if len(income_statements) > 1 else None)
    current_balance, prior_balance = balance_sheets[0], (balance_sheets[1] if len(balance_sheets) > 1 else None)
    current_cf, prior_cf = cash_flow_statements[0], (cash_flow_statements[1] if len(cash_flow_statements) > 1 else None)

    if price is None:
        price_bar = await prices_repository.get_price_as_of(session, ticker, as_of_cutoff)
        price = price_bar.close if price_bar is not None else None

    trailing_yoy_growth_rates = await _trailing_quarterly_revenue_yoy_growth(session, ticker, as_of_cutoff)

    return WealthEngineInput(
        ticker=ticker,
        as_of=date.fromisoformat(current_income.period_end.isoformat()),
        # The caller's original PIT cutoff, preserved as-is — added for API contract clarity
        # (responsible-output audit, 2026-08); does not change the as_of_cutoff filtering above in
        # any way, purely an additional, distinct field.
        requested_as_of=as_of,
        sector=sector,
        income_statement=current_income,
        balance_sheet=current_balance,
        cash_flow_statement=current_cf,
        prior_income_statement=prior_income,
        prior_balance_sheet=prior_balance,
        prior_cash_flow_statement=prior_cf,
        price=price,
        trailing_yoy_growth_rates=trailing_yoy_growth_rates,
    )
