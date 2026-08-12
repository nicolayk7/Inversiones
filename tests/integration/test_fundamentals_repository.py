"""Point-in-time correctness of `packages.storage.repositories.fundamentals_repository` against
a real Postgres (infra/docker-compose.yml). Uses a synthetic ticker so it never touches real
AAPL rows written by the ingestion vertical test."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete

from packages.shared.schemas import BalanceSheet, IncomeStatement
from packages.storage.db import SessionLocal
from packages.storage.models.fundamentals import BalanceSheetModel, IncomeStatementModel
from packages.storage.repositories import fundamentals_repository as repo

pytestmark = pytest.mark.integration

TICKER = "TESTPIT"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s
    # Cleanup uses its own connection — reusing `s` post-yield has been flaky under
    # pytest-asyncio's greenlet bridge on Windows/asyncpg (spurious "another operation is in
    # progress"); a fresh session sidesteps it entirely.
    async with SessionLocal() as cleanup:
        await cleanup.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == TICKER))
        await cleanup.execute(delete(BalanceSheetModel).where(BalanceSheetModel.ticker == TICKER))
        await cleanup.commit()


async def test_available_at_excludes_future_knowledge(session):
    stmt = IncomeStatement(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 2, 1),
        available_at=_dt("2024-02-01T23:59:59"), source="test", revenue=100.0,
    )
    await repo.save_income_statements(session, [stmt])

    before = await repo.get_income_statements(session, TICKER, _dt("2024-01-01T00:00:00"))
    assert before == []

    after = await repo.get_income_statements(session, TICKER, _dt("2024-02-02T00:00:00"))
    assert len(after) == 1
    assert after[0].revenue == 100.0


async def test_restatement_uses_most_recent_knowledge_not_latest_row(session):
    """Same period_end, filed twice (an amendment). PIT retrieval must pick, for a given as_of,
    the most recent available_at that does not exceed as_of — not simply 'the last row inserted'."""
    original = BalanceSheet(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 2, 1),
        available_at=_dt("2024-02-01T23:59:59"), source="test", total_assets=1000.0,
    )
    restated = BalanceSheet(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 6, 1),
        available_at=_dt("2024-06-01T23:59:59"), source="test", total_assets=1050.0,
    )
    await repo.save_balance_sheets(session, [original, restated])

    as_of_before_restatement = await repo.get_balance_sheets(session, TICKER, _dt("2024-03-01T00:00:00"))
    assert len(as_of_before_restatement) == 1
    assert as_of_before_restatement[0].total_assets == 1000.0

    as_of_after_restatement = await repo.get_balance_sheets(session, TICKER, _dt("2024-07-01T00:00:00"))
    assert len(as_of_after_restatement) == 1
    assert as_of_after_restatement[0].total_assets == 1050.0


async def test_two_periods_independently_selected_and_limited(session):
    older = IncomeStatement(
        ticker=TICKER, period_end=date(2022, 12, 31), reported_at=date(2023, 2, 1),
        available_at=_dt("2023-02-01T23:59:59"), source="test", revenue=90.0,
    )
    newer = IncomeStatement(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 2, 1),
        available_at=_dt("2024-02-01T23:59:59"), source="test", revenue=100.0,
    )
    await repo.save_income_statements(session, [older, newer])

    result = await repo.get_income_statements(session, TICKER, _dt("2025-01-01T00:00:00"), limit=2)
    assert [r.revenue for r in result] == [100.0, 90.0]  # period_end desc

    limited = await repo.get_income_statements(session, TICKER, _dt("2025-01-01T00:00:00"), limit=1)
    assert [r.revenue for r in limited] == [100.0]


async def test_upsert_is_idempotent_on_same_vintage(session):
    stmt = IncomeStatement(
        ticker=TICKER, period_end=date(2023, 12, 31), reported_at=date(2024, 2, 1),
        available_at=_dt("2024-02-01T23:59:59"), source="test", revenue=100.0,
    )
    await repo.save_income_statements(session, [stmt])
    await repo.save_income_statements(session, [stmt])  # re-ingest, same vintage

    result = await repo.get_income_statements(session, TICKER, _dt("2025-01-01T00:00:00"))
    assert len(result) == 1
