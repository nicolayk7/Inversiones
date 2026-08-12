"""SQLAlchemy tables for the three normalized financial-statement DTOs
(`packages.shared.schemas.IncomeStatement/BalanceSheet/CashFlowStatement`).

Mirrors each DTO field-for-field — these tables are the persisted form of the same canonical
shape Quant Core already consumes, not a redesign.

Uniqueness / point-in-time design (architecture v1.0 §04, rule 19):

- A surrogate `id` primary key, plus a `(ticker, period_end, source, reported_at)` unique
  constraint. `reported_at` is part of the key deliberately: a restatement (10-K/A) reports the
  same `period_end` again with a *different* `reported_at`/`available_at`, and must land as a new
  row, never overwrite the original — history is append-only so `available_at <= as_of` retrieval
  can reconstruct what was knowable at any past moment.
- `(ticker, period_end, available_at)` index — the point-in-time retrieval shape: "rows for this
  ticker/period, ordered by when they became knowable."
- `(ticker, available_at)` index — the "give me everything knowable for this ticker as of X"
  shape used to find which period_ends even exist as of a cutoff.

No `ON DELETE`/cascade behavior needed: these tables have no foreign keys to each other by
design (§7 of the continuity brief) — each statement type keeps independent provenance, so a
restated BalanceSheet must never be assumed to imply a restated IncomeStatement.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.storage.base import Base


class IncomeStatementModel(Base):
    __tablename__ = "income_statements"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "source", "reported_at", name="uq_income_statement_vintage"),
        Index("ix_income_statements_ticker_period_available", "ticker", "period_end", "available_at"),
        Index("ix_income_statements_ticker_available", "ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    reported_at: Mapped[date] = mapped_column(Date, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    revenue: Mapped[float | None] = mapped_column(Float, nullable=True)
    cogs: Mapped[float | None] = mapped_column(Float, nullable=True)
    operating_expenses: Mapped[float | None] = mapped_column(Float, nullable=True)
    net_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    diluted_shares_outstanding: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_expense: Mapped[float | None] = mapped_column(Float, nullable=True)
    ebit: Mapped[float | None] = mapped_column(Float, nullable=True)
    stock_based_compensation: Mapped[float | None] = mapped_column(Float, nullable=True)


class BalanceSheetModel(Base):
    __tablename__ = "balance_sheets"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "source", "reported_at", name="uq_balance_sheet_vintage"),
        Index("ix_balance_sheets_ticker_period_available", "ticker", "period_end", "available_at"),
        Index("ix_balance_sheets_ticker_available", "ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    reported_at: Mapped[date] = mapped_column(Date, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    total_assets: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Float, nullable=True)
    cash_and_equivalents: Mapped[float | None] = mapped_column(Float, nullable=True)
    minority_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    minority_interest_known: Mapped[bool] = mapped_column(nullable=False, default=False)
    preferred_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    preferred_equity_known: Mapped[bool] = mapped_column(nullable=False, default=False)
    book_equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    goodwill: Mapped[float | None] = mapped_column(Float, nullable=True)
    inventory: Mapped[float | None] = mapped_column(Float, nullable=True)
    receivables: Mapped[float | None] = mapped_column(Float, nullable=True)


class CashFlowStatementModel(Base):
    __tablename__ = "cash_flow_statements"
    __table_args__ = (
        UniqueConstraint("ticker", "period_end", "source", "reported_at", name="uq_cash_flow_statement_vintage"),
        Index("ix_cash_flow_statements_ticker_period_available", "ticker", "period_end", "available_at"),
        Index("ix_cash_flow_statements_ticker_available", "ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    reported_at: Mapped[date] = mapped_column(Date, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    operating_cash_flow: Mapped[float | None] = mapped_column(Float, nullable=True)
    depreciation_amortization: Mapped[float | None] = mapped_column(Float, nullable=True)
    capex: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta_working_capital: Mapped[float | None] = mapped_column(Float, nullable=True)
