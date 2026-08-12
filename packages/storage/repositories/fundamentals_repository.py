"""Point-in-time repository for the three normalized financial-statement DTOs.

This is the only place in the codebase that turns "give me the fundamentals for TICKER as of
DATE" into a query against `packages.storage.models.fundamentals`. Callers (Wealth Engine
ingestion) never see SQL; they get back the same canonical DTOs
(`packages.shared.schemas.IncomeStatement/BalanceSheet/CashFlowStatement`) a provider returns.

Point-in-time rule (architecture v1.0 §04, rule 19 / continuity brief §7): `available_at <= as_of`
is applied **independently per statement type** — there is no single query that joins all three
and filters once, because IncomeStatement/BalanceSheet/CashFlowStatement carry independent
provenance (an amendment can restate one without the others). `get_income_statements`,
`get_balance_sheets`, and `get_cash_flow_statements` are three separate queries against three
separate tables; nothing here assumes they share a `reported_at` or `available_at`.

Within one statement type, a given `period_end` can have multiple rows (restatements — a 10-K/A
filed later with the same period but a different `reported_at`/`available_at`). The PIT-correct
choice for "what did we know as of `as_of`" is: among rows for that `period_end` with
`available_at <= as_of`, take the one with the greatest `available_at` (the most recent
knowledge, never a future one). This is a per-`period_end` selection, done with a
`ROW_NUMBER() OVER (PARTITION BY period_end ORDER BY available_at DESC)` window — not a single
global "latest row" pick, which would incorrectly let one period's late amendment shadow another
period's plain filing.
"""

from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement
from packages.storage.models.fundamentals import (
    BalanceSheetModel,
    CashFlowStatementModel,
    IncomeStatementModel,
)

# -- generic PIT selection -----------------------------------------------------------------


def _latest_known_per_period_stmt(model, ticker: str, as_of: datetime, limit: int | None) -> Select:
    ranked = (
        select(
            model,
            func.row_number()
            .over(partition_by=model.period_end, order_by=model.available_at.desc())
            .label("_rank"),
        )
        .where(model.ticker == ticker, model.available_at <= as_of)
        .subquery()
    )
    stmt = (
        select(model)
        .select_from(ranked)
        .join(model, model.id == ranked.c.id)
        .where(ranked.c._rank == 1)
        .order_by(model.period_end.desc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    return stmt


async def _upsert(session: AsyncSession, model, unique_cols: tuple[str, ...], rows: list[dict]) -> None:
    if not rows:
        return
    stmt = pg_insert(model).values(rows)
    update_cols = {c: getattr(stmt.excluded, c) for c in rows[0] if c not in unique_cols and c != "id"}
    stmt = stmt.on_conflict_do_update(index_elements=list(unique_cols), set_=update_cols)
    await session.execute(stmt)
    await session.commit()


# -- IncomeStatement -------------------------------------------------------------------------


def _income_statement_row(dto: IncomeStatement) -> dict:
    return {
        "ticker": dto.ticker,
        "period_end": dto.period_end,
        "reported_at": dto.reported_at,
        "available_at": dto.available_at,
        "source": dto.source,
        "revenue": dto.revenue,
        "cogs": dto.cogs,
        "operating_expenses": dto.operating_expenses,
        "net_income": dto.net_income,
        "diluted_shares_outstanding": dto.diluted_shares_outstanding,
        "interest_expense": dto.interest_expense,
        "ebit": dto.ebit,
        "stock_based_compensation": dto.stock_based_compensation,
    }


def _income_statement_dto(row: IncomeStatementModel) -> IncomeStatement:
    return IncomeStatement(
        ticker=row.ticker, period_end=row.period_end, reported_at=row.reported_at,
        available_at=row.available_at, source=row.source, revenue=row.revenue, cogs=row.cogs,
        operating_expenses=row.operating_expenses, net_income=row.net_income,
        diluted_shares_outstanding=row.diluted_shares_outstanding,
        interest_expense=row.interest_expense, ebit=row.ebit,
        stock_based_compensation=row.stock_based_compensation,
    )


async def save_income_statements(session: AsyncSession, statements: list[IncomeStatement]) -> None:
    await _upsert(
        session, IncomeStatementModel,
        ("ticker", "period_end", "source", "reported_at"),
        [_income_statement_row(s) for s in statements],
    )


async def get_income_statements(
    session: AsyncSession, ticker: str, as_of: datetime, limit: int | None = None
) -> list[IncomeStatement]:
    stmt = _latest_known_per_period_stmt(IncomeStatementModel, ticker, as_of, limit)
    result = await session.execute(stmt)
    return [_income_statement_dto(row) for row in result.scalars().all()]


# -- BalanceSheet ------------------------------------------------------------------------------


def _balance_sheet_row(dto: BalanceSheet) -> dict:
    return {
        "ticker": dto.ticker,
        "period_end": dto.period_end,
        "reported_at": dto.reported_at,
        "available_at": dto.available_at,
        "source": dto.source,
        "total_assets": dto.total_assets,
        "total_debt": dto.total_debt,
        "cash_and_equivalents": dto.cash_and_equivalents,
        "minority_interest": dto.minority_interest,
        "minority_interest_known": dto.minority_interest_known,
        "preferred_equity": dto.preferred_equity,
        "preferred_equity_known": dto.preferred_equity_known,
        "book_equity": dto.book_equity,
        "goodwill": dto.goodwill,
        "inventory": dto.inventory,
        "receivables": dto.receivables,
    }


def _balance_sheet_dto(row: BalanceSheetModel) -> BalanceSheet:
    return BalanceSheet(
        ticker=row.ticker, period_end=row.period_end, reported_at=row.reported_at,
        available_at=row.available_at, source=row.source, total_assets=row.total_assets,
        total_debt=row.total_debt, cash_and_equivalents=row.cash_and_equivalents,
        minority_interest=row.minority_interest, minority_interest_known=row.minority_interest_known,
        preferred_equity=row.preferred_equity, preferred_equity_known=row.preferred_equity_known,
        book_equity=row.book_equity, goodwill=row.goodwill, inventory=row.inventory,
        receivables=row.receivables,
    )


async def save_balance_sheets(session: AsyncSession, statements: list[BalanceSheet]) -> None:
    await _upsert(
        session, BalanceSheetModel,
        ("ticker", "period_end", "source", "reported_at"),
        [_balance_sheet_row(s) for s in statements],
    )


async def get_balance_sheets(
    session: AsyncSession, ticker: str, as_of: datetime, limit: int | None = None
) -> list[BalanceSheet]:
    stmt = _latest_known_per_period_stmt(BalanceSheetModel, ticker, as_of, limit)
    result = await session.execute(stmt)
    return [_balance_sheet_dto(row) for row in result.scalars().all()]


# -- CashFlowStatement -------------------------------------------------------------------------


def _cash_flow_statement_row(dto: CashFlowStatement) -> dict:
    return {
        "ticker": dto.ticker,
        "period_end": dto.period_end,
        "reported_at": dto.reported_at,
        "available_at": dto.available_at,
        "source": dto.source,
        "operating_cash_flow": dto.operating_cash_flow,
        "depreciation_amortization": dto.depreciation_amortization,
        "capex": dto.capex,
        "delta_working_capital": dto.delta_working_capital,
    }


def _cash_flow_statement_dto(row: CashFlowStatementModel) -> CashFlowStatement:
    return CashFlowStatement(
        ticker=row.ticker, period_end=row.period_end, reported_at=row.reported_at,
        available_at=row.available_at, source=row.source,
        operating_cash_flow=row.operating_cash_flow,
        depreciation_amortization=row.depreciation_amortization, capex=row.capex,
        delta_working_capital=row.delta_working_capital,
    )


async def save_cash_flow_statements(session: AsyncSession, statements: list[CashFlowStatement]) -> None:
    await _upsert(
        session, CashFlowStatementModel,
        ("ticker", "period_end", "source", "reported_at"),
        [_cash_flow_statement_row(s) for s in statements],
    )


async def get_cash_flow_statements(
    session: AsyncSession, ticker: str, as_of: datetime, limit: int | None = None
) -> list[CashFlowStatement]:
    stmt = _latest_known_per_period_stmt(CashFlowStatementModel, ticker, as_of, limit)
    result = await session.execute(stmt)
    return [_cash_flow_statement_dto(row) for row in result.scalars().all()]
