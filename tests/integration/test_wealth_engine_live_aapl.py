"""The first full vertical, end to end, with real data:

    SEC EDGAR (AAPL) -> normalized DTOs -> PostgreSQL -> point-in-time retrieval
    -> Quant Core -> Wealth Engine -> WealthEngineOutput

Two phases, run against two different sessions to keep them honest:

1. `ingest_fundamentals` — the only phase allowed to touch SEC EDGAR (live internet access to
   data.sec.gov, marked `integration` for the same reason `test_health.py` is).
2. Retrieval + compute — `SecEdgarFundamentalsProvider` is monkeypatched to a version that raises
   on construction for this phase, so if `build_wealth_engine_input_from_storage` (or anything it
   calls) ever reached for the provider instead of storage, this test would fail loudly instead of
   silently passing on a shortcut.

Market Data Foundation Phase 4 adds price wiring to the same vertical, below. Its no-bypass and
PIT tests use a synthetic ticker with data seeded directly through the repositories (same
technique as `tests/integration/test_wealth_api.py`) rather than a live Massive call — a
constructed "price A vs. price B, which one is knowable as of which date" scenario is not
something a live call against today's real market data can deterministically reproduce on demand,
and "Idealmente usar un rango pequeño y determinista" asks for exactly that determinism. The one
genuinely live Massive path is a separate, opt-in test gated on `MASSIVE_API_KEY` (mirrors
`tests/unit/test_massive_provider.py`'s live smoke test).
"""

import os
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from packages.engines.wealth_engine import data_ingestion
from packages.engines.wealth_engine.data_ingestion import _QUARTERLY_SOURCE
from packages.engines.wealth_engine.pipeline import compute_wealth_snapshot
from packages.quant_core.regime import SectorProfile
from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement, OHLCVBar
from packages.storage.db import SessionLocal
from packages.storage.models.fundamentals import (
    BalanceSheetModel,
    CashFlowStatementModel,
    IncomeStatementModel,
)
from packages.storage.models.prices import PriceBarModel
from packages.storage.repositories import fundamentals_repository, prices_repository

pytestmark = pytest.mark.integration

TICKER = "AAPL"


async def _delete_annual_aapl_rows(session: AsyncSession) -> None:
    """Cleanup scoped to exactly what this suite re-ingests (annual statements) — never touches
    quarterly-sourced rows (source == _QUARTERLY_SOURCE). Regression guard for a real incident
    found during the MVP-0 responsible-output audit: the original, unscoped
    `delete(IncomeStatementModel).where(ticker == TICKER)` wiped Phase 7C-1's quarterly revenue
    series every time this suite ran, silently degrading `growth_score` to `INSUFFICIENT_DATA`
    for AAPL with no error or warning anywhere. Same source-scoping technique
    `test_trailing_yoy_growth_rates.py` already uses. See
    `test_clean_aapl_storage_never_deletes_quarterly_rows` below for the direct regression test."""
    await session.execute(delete(IncomeStatementModel).where(
        IncomeStatementModel.ticker == TICKER, IncomeStatementModel.source != _QUARTERLY_SOURCE,
    ))
    await session.execute(delete(BalanceSheetModel).where(BalanceSheetModel.ticker == TICKER))
    await session.execute(delete(CashFlowStatementModel).where(CashFlowStatementModel.ticker == TICKER))
    await session.commit()


@pytest.fixture
async def clean_aapl_storage():
    async with SessionLocal() as s:
        await _delete_annual_aapl_rows(s)
    yield
    # No teardown: the ingested AAPL rows (annual + quarterly, both re-ingested by the test body
    # below) are this vertical's demonstration dataset, not scratch data, and re-running this
    # suite is idempotent (ingest upserts on the same vintage).


def _provider_construction_forbidden(*args, **kwargs):
    raise AssertionError(
        "build_wealth_engine_input_from_storage must never construct a FundamentalsProvider — "
        "retrieval is storage-only by construction"
    )


async def test_aapl_real_data_flows_provider_to_storage_to_wealth_engine(clean_aapl_storage, monkeypatch):
    # Phase 1 — ingestion: SEC EDGAR -> canonical DTOs -> PostgreSQL. Both annual
    # (ingest_fundamentals) and quarterly (ingest_quarterly_revenue, Phase 7C-1) are ingested here
    # so this test always leaves AAPL's storage complete, regardless of what earlier runs left
    # behind — see _delete_annual_aapl_rows above for why the cleanup fixture no longer touches
    # quarterly rows.
    async with SessionLocal() as ingest_session:
        await data_ingestion.ingest_fundamentals(TICKER, ingest_session)
    async with SessionLocal() as ingest_session:
        await data_ingestion.ingest_quarterly_revenue(TICKER, ingest_session)

    # Phase 2 — retrieval + compute: provider construction is now forbidden. If retrieval bypassed
    # storage and called the provider directly, this monkeypatch makes that fail immediately.
    monkeypatch.setattr(data_ingestion, "SecEdgarFundamentalsProvider", _provider_construction_forbidden)

    async with SessionLocal() as retrieval_session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date.today(), retrieval_session
        )

    # Real data sanity checks — not exact values (those change every filing), just that real
    # numbers came back from storage, not None/fabricated placeholders.
    assert inp.income_statement.revenue is not None
    assert inp.income_statement.revenue > 0
    assert inp.prior_income_statement is not None
    assert inp.prior_income_statement.period_end < inp.income_statement.period_end

    # Quarterly revenue series (Phase 7C-1) must have survived this test's own cleanup+ingest —
    # the exact regression this fix guards against.
    assert inp.trailing_yoy_growth_rates is not None
    assert len(inp.trailing_yoy_growth_rates) >= 2

    output = compute_wealth_snapshot(inp)

    # wealth_score is null by design (BalanceSheetMultiplier blocked) — not a failure.
    assert output.wealth_score.status == "UNSUPPORTED"
    assert "BalanceSheetMultiplier" in output.wealth_score.reason

    # wealth_score_raw is N/A by design (Moat permanently deferred) — not a failure.
    assert output.wealth_score_raw.status == "N/A"
    assert "moat" in output.wealth_score_raw.reason

    # Quality and FCF should resolve OK from real Apple data (coverage clears with real inputs).
    assert output.quality_score.status == "OK"
    assert output.fcf_score.status == "OK"

    # Growth, too, now that quarterly data is guaranteed present — the direct proof that
    # restoring the quarterly series (not just having it exist in isolation) actually matters.
    assert output.growth_score.status == "OK"

    # ROIC is a raw, unclipped metric — must not be silently absent.
    assert output.roic is not None


async def test_clean_aapl_storage_never_deletes_quarterly_rows():
    """Direct regression test for the MVP-0 audit finding (see _delete_annual_aapl_rows above):
    seed a synthetic AAPL quarterly row, run the exact cleanup clean_aapl_storage uses, and
    confirm the quarterly row survives untouched — only annual-sourced rows may be removed.

    _delete_annual_aapl_rows also unconditionally clears balance_sheets/cash_flow_statements (§
    those tables carry no quarterly/annual distinction to preserve), so — same "restore what you
    remove" discipline this test exists to enforce on the fixture — this test re-ingests real
    annual data at the end via ingest_fundamentals, exactly like the main test above, so it can
    never itself leave AAPL's shared dev-DB row incomplete for a later test or demo."""
    marker_period_end = date(2030, 3, 31)  # far-future, cannot collide with real AAPL data
    quarterly_row = IncomeStatement(
        ticker=TICKER, period_end=marker_period_end, reported_at=date(2030, 5, 1),
        available_at=datetime(2030, 5, 1, 23, 59, 59, tzinfo=timezone.utc),
        source=_QUARTERLY_SOURCE, revenue=999.0,
    )
    async with SessionLocal() as s:
        await fundamentals_repository.save_income_statements(s, [quarterly_row])

    async with SessionLocal() as s:
        await _delete_annual_aapl_rows(s)

    async with SessionLocal() as s:
        remaining = await fundamentals_repository.get_income_statements(
            s, TICKER, datetime(2099, 1, 1, tzinfo=timezone.utc), limit=None
        )
    assert any(
        r.source == _QUARTERLY_SOURCE and r.period_end == marker_period_end for r in remaining
    ), "clean_aapl_storage's cleanup must never delete quarterly-sourced rows"

    # Remove the synthetic marker row this test added so it doesn't linger in the shared dev DB.
    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(
            IncomeStatementModel.ticker == TICKER,
            IncomeStatementModel.period_end == marker_period_end,
            IncomeStatementModel.source == _QUARTERLY_SOURCE,
        ))
        await s.commit()

    # Restore what this test's own call to _delete_annual_aapl_rows removed (annual income
    # statements, balance sheets, cash flow statements) — this test must never be the reason
    # AAPL's shared dev-DB data is left incomplete for whichever test/demo runs next.
    async with SessionLocal() as s:
        await data_ingestion.ingest_fundamentals(TICKER, s)


# ==============================================================================================
# Market Data Foundation Phase 4 — price wiring: no-bypass and PIT, deterministic/synthetic.
# ==============================================================================================

PIT_TICKER = "WIREPIT"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.fixture
async def seeded_wirepit_fundamentals_and_prices():
    """Minimal single-period fundamentals (so build_wealth_engine_input_from_storage doesn't
    raise for lack of any statements) plus two price vintages for the PIT scenario, all seeded
    directly through the repositories — no provider involved."""
    income = IncomeStatement(
        ticker=PIT_TICKER, period_end=date(2025, 3, 31), reported_at=date(2025, 5, 1),
        available_at=_dt("2025-05-01T20:00:00"), source="fixture",
        revenue=1000.0, net_income=100.0, diluted_shares_outstanding=50.0, ebit=150.0,
    )
    balance = BalanceSheet(
        ticker=PIT_TICKER, period_end=date(2025, 3, 31), reported_at=date(2025, 5, 1),
        available_at=_dt("2025-05-01T20:00:00"), source="fixture",
        total_assets=2000.0, total_debt=500.0, cash_and_equivalents=200.0, book_equity=1000.0,
    )
    cash_flow = CashFlowStatement(
        ticker=PIT_TICKER, period_end=date(2025, 3, 31), reported_at=date(2025, 5, 1),
        available_at=_dt("2025-05-01T20:00:00"), source="fixture",
        operating_cash_flow=180.0, capex=40.0,
    )
    price_a = OHLCVBar(  # ts=06-10, available_at=06-10T21:00 — knowable as of 06-10
        ticker=PIT_TICKER, ts=date(2025, 6, 10), open=100.0, high=101.0, low=99.0, close=100.0,
        volume=1_000_000, available_at=_dt("2025-06-10T21:00:00"), source="fixture",
    )
    price_b = OHLCVBar(  # ts=06-11, available_at=06-11T21:00 — NOT knowable as of 06-10
        ticker=PIT_TICKER, ts=date(2025, 6, 11), open=104.0, high=106.0, low=103.0, close=105.0,
        volume=1_100_000, available_at=_dt("2025-06-11T21:00:00"), source="fixture",
    )

    async with SessionLocal() as s:
        await fundamentals_repository.save_income_statements(s, [income])
        await fundamentals_repository.save_balance_sheets(s, [balance])
        await fundamentals_repository.save_cash_flow_statements(s, [cash_flow])
        await prices_repository.save_daily_bars(s, [price_a, price_b])
    yield
    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == PIT_TICKER))
        await s.execute(delete(BalanceSheetModel).where(BalanceSheetModel.ticker == PIT_TICKER))
        await s.execute(delete(CashFlowStatementModel).where(CashFlowStatementModel.ticker == PIT_TICKER))
        await s.execute(delete(PriceBarModel).where(PriceBarModel.ticker == PIT_TICKER))
        await s.commit()


async def test_price_retrieval_never_calls_massive_provider(
    seeded_wirepit_fundamentals_and_prices, monkeypatch
):
    """No-bypass, obligatory (§11): with the provider poisoned to raise on construction, retrieval
    must still succeed — proving `build_wealth_engine_input_from_storage` gets price from Storage,
    never from Massive."""

    def _provider_construction_forbidden(*args, **kwargs):
        raise AssertionError(
            "build_wealth_engine_input_from_storage must never construct a MarketDataProvider — "
            "retrieval is storage-only by construction"
        )

    monkeypatch.setattr(data_ingestion, "MassiveMarketDataProvider", _provider_construction_forbidden)

    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            PIT_TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 6, 10), session
        )

    assert inp.price == 100.0  # price_a — retrieved from storage, Massive never touched


async def test_price_retrieval_respects_pit_never_sees_future_price(
    seeded_wirepit_fundamentals_and_prices,
):
    """PIT, obligatory (§12): price A (available_at=06-10T21:00) and price B
    (available_at=06-11T21:00) both exist in storage. A query as_of=2025-06-10 must receive A,
    never B — even though B's `ts` (06-11) is not itself "in the future" relative to some other
    reference; what matters is strictly `available_at <= as_of`."""
    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            PIT_TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 6, 10), session
        )
    assert inp.price == 100.0

    # And as_of=06-11 (after B's available_at) correctly picks up B instead.
    async with SessionLocal() as session:
        inp_later = await data_ingestion.build_wealth_engine_input_from_storage(
            PIT_TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 6, 11), session
        )
    assert inp_later.price == 105.0


async def test_price_absent_from_storage_yields_none_not_fabricated(
    seeded_wirepit_fundamentals_and_prices,
):
    """as_of after fundamentals become available but before either price vintage exists: price
    must be None, never a fabricated or forward-filled value."""
    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            PIT_TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 6, 1), session
        )
    assert inp.price is None


async def test_fundamentals_only_retrieval_still_works_unaffected_by_price_wiring(
    seeded_wirepit_fundamentals_and_prices,
):
    """Regression guard: adding price retrieval must not disturb fundamentals-only behavior —
    quality/fcf-style scores still compute from the same seeded statements as before this phase."""
    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            PIT_TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 6, 10), session
        )
    assert inp.income_statement.revenue == 1000.0
    output = compute_wealth_snapshot(inp)
    assert output.wealth_score.status == "UNSUPPORTED"  # unaffected by price wiring


# -- Live Massive path (opt-in only) -----------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("MASSIVE_API_KEY"),
    reason="Live provider test: SKIPPED — credentials unavailable",
)
async def test_live_aapl_price_ingestion_wires_into_wealth_engine():
    """Real Massive call -> PostgreSQL -> retrieval -> WealthEngineInput.price. Only runs if
    MASSIVE_API_KEY is set. Small, deterministic range: two fixed historical trading days."""
    start, end = date(2024, 1, 2), date(2024, 1, 5)
    as_of = date(2024, 1, 8)  # after the ingested range, so the last bar is eligible

    async with SessionLocal() as session:
        await data_ingestion.ingest_fundamentals(TICKER, session)  # idempotent if already present
        await data_ingestion.ingest_price(TICKER, start, end, session)

    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, as_of, session
        )

    assert inp.price is not None
    assert inp.price > 0

    output = compute_wealth_snapshot(inp)
    # metric_profile (P/E, real price now available) feeds valuation_score's coverage; the
    # composed score can still legitimately read INSUFFICIENT_DATA here — historical_percentile
    # and sector_percentile remain out of scope (methodology §11/§23) — 1/3 sub-metrics present
    # is below the 60% group-coverage threshold. This is not a bug; see pipeline.py's
    # _valuation_sub_metrics.
    assert output.valuation_score.status in ("OK", "INSUFFICIENT_DATA")


# -- Live Finviz free-price path (opt-in only) --------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("RUN_FINVIZ_LIVE_TEST"),
    reason="Live scrape against the real finviz.com: SKIPPED by default (ToS caution) — set "
    "RUN_FINVIZ_LIVE_TEST=1 to opt in",
)
async def test_live_aapl_finviz_price_ingestion_wires_into_wealth_engine():
    """Mirrors test_live_aapl_price_ingestion_wires_into_wealth_engine above, but through the
    free Finviz path (ingest_finviz_price) instead of paid Massive — the $0-cost substitute this
    MVP needs when no MASSIVE_API_KEY is configured. Real Finviz scrape -> PostgreSQL -> retrieval
    -> WealthEngineInput.price, `as_of`=today (Finviz's free page has no historical snapshots — see
    finviz.py's module docstring — so, unlike the Massive test above, this cannot use a fixed past
    as_of; the ingested bar's own `ts`/`available_at` are both "now")."""
    async with SessionLocal() as session:
        await data_ingestion.ingest_fundamentals(TICKER, session)  # idempotent if already present
        await data_ingestion.ingest_finviz_price(TICKER, session)

    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date.today(), session
        )

    assert inp.price is not None
    assert inp.price > 0

    output = compute_wealth_snapshot(inp)
    assert output.valuation_score.status in ("OK", "INSUFFICIENT_DATA")
