"""IncomeStatement/BalanceSheet/CashFlowStatement (Phase 1B design decision: normalized
financial-statement concepts, not a flat FundamentalsRecord extension) construct and carry
independent point-in-time provenance per statement."""

from packages.providers import base
from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement


def test_income_statement_constructs_with_pit_fields():
    stmt = IncomeStatement(
        ticker="AAPL", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="test", revenue=100.0, net_income=20.0,
    )
    assert stmt.period_end.isoformat() == "2025-06-30"
    assert stmt.revenue == 100.0


def test_balance_sheet_carries_known_vs_unknown_distinction_for_m4():
    known_zero = BalanceSheet(
        ticker="AAPL", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="test",
        minority_interest=None, minority_interest_known=False,
    )
    assert known_zero.minority_interest is None
    assert known_zero.minority_interest_known is False

    known_unsourced = BalanceSheet(
        ticker="AAPL", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="test",
        minority_interest=None, minority_interest_known=True,
    )
    assert known_unsourced.minority_interest_known is True


def test_cash_flow_statement_constructs():
    stmt = CashFlowStatement(
        ticker="AAPL", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="test",
        operating_cash_flow=50.0, capex=10.0,
    )
    assert stmt.operating_cash_flow == 50.0


def test_statements_carry_independent_provenance_not_assumed_matching():
    """Cross-statement consistency requirement (implementation spec §2.2): a BalanceSheet
    amendment can carry a different reported_at/source than the IncomeStatement for the same
    period_end — nothing in the DTOs forces them to match."""
    income = IncomeStatement(
        ticker="AAPL", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="provider-a",
    )
    balance = BalanceSheet(
        ticker="AAPL", period_end="2025-06-30", reported_at="2025-09-15",
        available_at="2025-09-15T20:00:00Z", source="provider-a-amendment",
    )
    assert income.reported_at != balance.reported_at
    assert income.source != balance.source


def test_fundamentals_provider_declares_normalized_statement_methods():
    cls = base.FundamentalsProvider
    for method in ("get_quarterly_fundamentals", "get_income_statements", "get_balance_sheets", "get_cash_flow_statements"):
        assert hasattr(cls, method), f"FundamentalsProvider must declare {method}()"
