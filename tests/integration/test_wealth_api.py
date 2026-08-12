"""POST /v1/wealth/compute — ticker+as_of boundary, reading from storage (real Postgres via
infra/docker-compose.yml). Seeds fixture statements directly through the repository (the same
path `ingest_fundamentals` would populate) rather than calling live SEC EDGAR — this test is
about the API/storage contract, not about SEC data quality (see
tests/integration/test_wealth_engine_live_aapl.py for that)."""

from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete

from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement
from packages.storage.db import SessionLocal
from packages.storage.models.fundamentals import (
    BalanceSheetModel,
    CashFlowStatementModel,
    IncomeStatementModel,
)
from packages.storage.repositories import fundamentals_repository as repo

pytestmark = pytest.mark.integration

TICKER = "APITEST"


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest.fixture
async def seeded_statements():
    income = IncomeStatement(
        ticker=TICKER, period_end=date(2025, 6, 30), reported_at=date(2025, 8, 1),
        available_at=_dt("2025-08-01T20:00:00"), source="fixture",
        revenue=1000.0, cogs=400.0, operating_expenses=300.0, net_income=150.0,
        diluted_shares_outstanding=100.0, interest_expense=10.0, ebit=200.0,
    )
    balance = BalanceSheet(
        ticker=TICKER, period_end=date(2025, 6, 30), reported_at=date(2025, 8, 1),
        available_at=_dt("2025-08-01T20:00:00"), source="fixture",
        total_assets=2000.0, total_debt=500.0, cash_and_equivalents=200.0,
        book_equity=1000.0, goodwill=100.0,
    )
    cash_flow = CashFlowStatement(
        ticker=TICKER, period_end=date(2025, 6, 30), reported_at=date(2025, 8, 1),
        available_at=_dt("2025-08-01T20:00:00"), source="fixture",
        operating_cash_flow=180.0, depreciation_amortization=50.0, capex=40.0,
    )
    async with SessionLocal() as s:
        await repo.save_income_statements(s, [income])
        await repo.save_balance_sheets(s, [balance])
        await repo.save_cash_flow_statements(s, [cash_flow])
    yield
    async with SessionLocal() as s:
        await s.execute(delete(IncomeStatementModel).where(IncomeStatementModel.ticker == TICKER))
        await s.execute(delete(BalanceSheetModel).where(BalanceSheetModel.ticker == TICKER))
        await s.execute(delete(CashFlowStatementModel).where(CashFlowStatementModel.ticker == TICKER))
        await s.commit()


async def test_compute_endpoint_reads_from_storage_not_payload(api_client, seeded_statements):
    response = await api_client.post(
        "/v1/wealth/compute",
        json={"ticker": TICKER, "as_of": "2025-08-15", "sector": "generic_industrial"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["wealth_score"]["value"] is None
    assert body["wealth_score"]["status"] == "UNSUPPORTED"
    assert "BalanceSheetMultiplier" in body["wealth_score"]["reason"]


async def test_compute_endpoint_banks_sector_unsupported_quality(api_client, seeded_statements):
    response = await api_client.post(
        "/v1/wealth/compute",
        json={"ticker": TICKER, "as_of": "2025-08-15", "sector": "financials_banks"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["quality_score"]["status"] == "UNSUPPORTED"


async def test_compute_endpoint_404_when_nothing_ingested_for_ticker(api_client):
    response = await api_client.post(
        "/v1/wealth/compute",
        json={"ticker": "NEVERINGESTED", "as_of": "2025-08-15"},
    )
    assert response.status_code == 404
