"""Phase 7C-1: `trailing_yoy_growth_rates` construction (Growth Consistency's input series,
Revenue-based, quarterly — Growth Trailing Decision Audit Decisions 1/2).

Deterministic, synthetic data seeded directly through the repository (real Postgres via
infra/docker-compose.yml) — same technique already used by test_wealth_api.py and
test_wealth_engine_live_aapl.py's WIREPIT fixtures, for the same reason: a constructed "N
quarters spanning M years, some PIT-ineligible" scenario needs to be exact and reproducible, not
whatever happens to be true of live data on a given day. Real AAPL validation lives in
tests/integration/test_wealth_engine_live_aapl.py / a manual check reported separately — this
file is about the construction LOGIC being correct.
"""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete

from packages.engines.wealth_engine import data_ingestion
from packages.engines.wealth_engine.data_ingestion import _QUARTERLY_SOURCE
from packages.quant_core.regime import SectorProfile
from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement
from packages.storage.db import SessionLocal
from packages.storage.models.fundamentals import (
    BalanceSheetModel,
    CashFlowStatementModel,
    IncomeStatementModel,
)
from packages.storage.repositories import fundamentals_repository as repo

pytestmark = pytest.mark.integration

TICKER = "TRAILPIT"
COLLISION_TICKER = "TRAILCOL"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _q(ticker: str, period_end: str, filed: str, revenue: float, source: str = _QUARTERLY_SOURCE) -> IncomeStatement:
    return IncomeStatement(
        ticker=ticker, period_end=date.fromisoformat(period_end), reported_at=date.fromisoformat(filed),
        available_at=_dt(f"{filed}T23:59:59"), source=source, revenue=revenue,
    )


def _annual(ticker: str, period_end: str, filed: str, revenue: float) -> IncomeStatement:
    return IncomeStatement(
        ticker=ticker, period_end=date.fromisoformat(period_end), reported_at=date.fromisoformat(filed),
        available_at=_dt(f"{filed}T23:59:59"), source="sec_edgar", revenue=revenue,
        cogs=1.0, net_income=1.0,  # non-None, distinguishing an annual row from a quarterly one by shape too
    )


@pytest.fixture
async def seeded_minimal_fundamentals():
    """One prior-year annual statement so build_wealth_engine_input_from_storage doesn't raise
    for lack of any fundamentals at all — required regardless of what this test is actually
    checking (the trailing quarterly series)."""
    balance = BalanceSheet(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 2, 1),
        available_at=_dt("2024-02-01T20:00:00"), source="sec_edgar", total_assets=100.0,
    )
    cash_flow = CashFlowStatement(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 2, 1),
        available_at=_dt("2024-02-01T20:00:00"), source="sec_edgar",
    )
    async with SessionLocal() as s:
        await repo.save_income_statements(s, [_annual(TICKER, "2023-12-31", "2024-02-01", 1000.0)])
        await repo.save_balance_sheets(s, [balance])
        await repo.save_cash_flow_statements(s, [cash_flow])
    yield
    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == TICKER))
        await s.execute(delete(BalanceSheetModel).where(BalanceSheetModel.ticker == TICKER))
        await s.execute(delete(CashFlowStatementModel).where(CashFlowStatementModel.ticker == TICKER))
        await s.commit()


async def test_no_quarterly_data_yields_none_not_fabricated(seeded_minimal_fundamentals):
    """No quarterly rows ingested at all -> trailing_yoy_growth_rates must be None, never []
    or a fabricated series."""
    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 1, 1), session
        )
    assert inp.trailing_yoy_growth_rates is None


async def test_series_computed_from_same_quarter_prior_year(seeded_minimal_fundamentals):
    """Two years of Q1/Q2/Q3 (6 quarters) -> 3 valid YoY pairs (Q1'25 vs Q1'24, Q2'25 vs Q2'24,
    Q3'25 vs Q3'24), each computed via the same qf.yoy_growth formula used elsewhere."""
    quarters = [
        _q(TICKER, "2023-12-30", "2024-02-01", 100.0),
        _q(TICKER, "2024-03-30", "2024-05-01", 110.0),
        _q(TICKER, "2024-06-29", "2024-08-01", 120.0),
        _q(TICKER, "2024-12-28", "2025-02-01", 130.0),  # +30% vs 100
        _q(TICKER, "2025-03-29", "2025-05-01", 121.0),  # +10% vs 110
        _q(TICKER, "2025-06-28", "2025-08-01", 96.0),   # -20% vs 120
    ]
    async with SessionLocal() as s:
        await repo.save_income_statements(s, quarters)

    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 9, 1), session
        )

    assert inp.trailing_yoy_growth_rates is not None
    rates = sorted(inp.trailing_yoy_growth_rates)
    assert rates == pytest.approx(sorted([0.30, 0.10, -0.20]), abs=1e-9)

    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == TICKER, IncomeStatementModel.source == _QUARTERLY_SOURCE))
        await s.commit()


async def test_pit_excludes_quarters_not_yet_available(seeded_minimal_fundamentals):
    """A quarter whose available_at is after as_of must not contribute to the series — same
    available_at <= as_of guarantee as everywhere else in this system."""
    quarters = [
        _q(TICKER, "2023-12-30", "2024-02-01", 100.0),
        _q(TICKER, "2024-12-28", "2025-02-01", 130.0),  # available 2025-02-01
    ]
    async with SessionLocal() as s:
        await repo.save_income_statements(s, quarters)

    async with SessionLocal() as session:
        inp_before = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 1, 15), session
        )
    # Only the 2023-12-30 quarter is knowable as of 2025-01-15 — a single quarter can't form a
    # YoY pair with anything, so the series must be None, not a fabricated single-point series.
    assert inp_before.trailing_yoy_growth_rates is None

    async with SessionLocal() as session:
        inp_after = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 3, 1), session
        )
    assert inp_after.trailing_yoy_growth_rates == pytest.approx([0.30], abs=1e-9)

    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == TICKER, IncomeStatementModel.source == _QUARTERLY_SOURCE))
        await s.commit()


async def test_quarterly_rows_never_leak_into_the_annual_retrieval_path(seeded_minimal_fundamentals):
    """Regression test for a real bug caught during Phase 7C-1's own AAPL validation: a quarterly
    row's period_end can be MORE RECENT than the prior fiscal year's period_end (e.g. a Q3 quarter
    dated after last year's fiscal year-end but before this year's) — a naive limit=2 fetch on
    income_statements (which has no source-aware partitioning) would then pick that quarterly row
    as "prior_income_statement" instead of the true prior annual statement, corrupting
    Quality/FCF/Growth's YoY sub-metrics with an annual-vs-quarterly mismatch (cogs/net_income/
    diluted_shares all silently None). This must never happen: prior_income_statement must always
    be the true prior ANNUAL statement, regardless of what quarterly data exists in between."""
    annual_current = _annual(TICKER, "2024-12-31", "2025-02-01", 5000.0)
    quarterly_between = _q(TICKER, "2024-06-30", "2024-08-01", 1200.0)  # between the two annual years

    async with SessionLocal() as s:
        await repo.save_income_statements(s, [annual_current, quarterly_between])

    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 3, 1), session
        )

    assert inp.income_statement.period_end.isoformat() == "2024-12-31"
    assert inp.prior_income_statement is not None
    assert inp.prior_income_statement.period_end.isoformat() == "2023-12-31"  # the true prior YEAR
    assert inp.prior_income_statement.source != _QUARTERLY_SOURCE
    assert inp.prior_income_statement.cogs is not None  # proves it's the full annual row, not the quarterly stub

    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(
            IncomeStatementModel.ticker == TICKER,
            IncomeStatementModel.period_end.in_([date(2024, 12, 31), date(2024, 6, 30)]),
        ))
        await s.commit()


async def test_annual_rows_never_leak_into_the_quarterly_series(seeded_minimal_fundamentals):
    """The already-seeded annual 2023-12-31 row (source="sec_edgar") must never be mistaken for a
    quarterly point, regardless of how close its period_end is to real quarterly period_ends."""
    quarters = [
        _q(TICKER, "2024-03-30", "2024-05-01", 110.0),
        _q(TICKER, "2025-03-29", "2025-05-01", 121.0),
    ]
    async with SessionLocal() as s:
        await repo.save_income_statements(s, quarters)

    async with SessionLocal() as session:
        inp = await data_ingestion.build_wealth_engine_input_from_storage(
            TICKER, SectorProfile.GENERIC_INDUSTRIAL, date(2025, 9, 1), session
        )
    assert inp.trailing_yoy_growth_rates == pytest.approx([0.10], abs=1e-9)

    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == TICKER, IncomeStatementModel.source == _QUARTERLY_SOURCE))
        await s.commit()


# -- ingest_quarterly_revenue: Q4-exclusion / no collision with the annual row -----------------


class _FakeProvider:
    """Duck-typed stand-in for SecEdgarFundamentalsProvider — no network. Returns a controlled
    quarterly series (including a would-be-colliding Q4) and a matching fiscal-year-end set, to
    prove ingest_quarterly_revenue's Q4-exclusion logic without touching real SEC data."""

    def __init__(self, quarters: list[IncomeStatement], fiscal_year_ends: set[str]):
        self._quarters = quarters
        self._fiscal_year_ends = fiscal_year_ends

    def get_quarterly_revenue(self, ticker: str, num_quarters: int = 24) -> list[IncomeStatement]:
        return self._quarters

    def _full_fiscal_years(self, ticker: str) -> list[dict]:
        return [{"end": end} for end in self._fiscal_year_ends]

    def close(self) -> None:
        pass


async def test_ingest_quarterly_revenue_excludes_q4_and_does_not_collide_with_annual():
    """Q4's period_end coincides with the fiscal year's own period_end (2024-09-28 here, matching
    an already-ingested annual row for that exact date) — ingest_quarterly_revenue must NOT
    persist it, and the pre-existing annual row must remain exactly as it was (not overwritten,
    not duplicated, still retrievable as the normal annual statement)."""
    async with SessionLocal() as s:
        await repo.save_income_statements(s, [_annual(COLLISION_TICKER, "2024-09-28", "2024-11-01", 5000.0)])

    fake_quarters = [
        _q(COLLISION_TICKER, "2023-12-30", "2024-02-01", 1000.0),
        _q(COLLISION_TICKER, "2024-03-30", "2024-05-01", 1100.0),
        _q(COLLISION_TICKER, "2024-06-29", "2024-08-01", 1200.0),
        _q(COLLISION_TICKER, "2024-09-28", "2024-11-01", 1700.0),  # Q4 — same period_end as the annual row
    ]
    provider = _FakeProvider(fake_quarters, fiscal_year_ends={"2024-09-28"})

    async with SessionLocal() as s:
        await data_ingestion.ingest_quarterly_revenue(COLLISION_TICKER, s, provider=provider)

    async with SessionLocal() as s:
        quarterly_rows = await repo.get_income_statements(
            s, COLLISION_TICKER, _dt("2030-01-01T00:00:00"), limit=None
        )
    by_period = {r.period_end.isoformat(): r for r in quarterly_rows}

    # Q4 (2024-09-28) was NOT persisted under the quarterly source — the annual row is the only
    # thing at that period_end, completely unaffected (still full revenue=5000, still source
    # "sec_edgar", not overwritten by the 1700 Q4 figure or duplicated into a second row).
    assert by_period["2024-09-28"].revenue == 5000.0
    assert by_period["2024-09-28"].source == "sec_edgar"

    # Q1/Q2/Q3 WERE persisted correctly under the quarterly source.
    assert by_period["2023-12-30"].revenue == 1000.0
    assert by_period["2023-12-30"].source == _QUARTERLY_SOURCE
    assert by_period["2024-06-29"].revenue == 1200.0

    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == COLLISION_TICKER))
        await s.commit()
