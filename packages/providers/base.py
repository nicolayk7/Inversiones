"""The nine data provider interfaces (architecture v1.0 §04). Engines depend on
these Protocols, never on a concrete SDK — swapping the options data tier
from EOD-only to delayed/real-time in Phase 2 (decision #1) must not touch
Options Intelligence.

Every method that can feed a backtest takes an `as_of` cutoff: `None` means
"latest known", a `date` means "only what was available_at <= as_of" — the
Backtest Engine is the only caller expected to pass a real value there.

No implementations here — that starts per-provider in Phase 1. This module
is the contract only.
"""

from datetime import date, datetime
from typing import Protocol

from packages.shared.schemas import (
    AnalystEstimate,
    BalanceSheet,
    CashFlowStatement,
    CorporateAction,
    EconomicCalendarEvent,
    FilingRecord,
    FundamentalsRecord,
    IncomeStatement,
    MacroObservation,
    NewsItem,
    OHLCVBar,
    OptionContract,
)


class MarketDataProvider(Protocol):
    def get_daily_bars(self, ticker: str, start: date, end: date) -> list[OHLCVBar]: ...


class FundamentalsProvider(Protocol):
    def get_quarterly_fundamentals(
        self, ticker: str, as_of: date | None = None
    ) -> list[FundamentalsRecord]: ...

    # Normalized statement methods — Phase 1B design decision (see
    # docs/wealth-engine-phase1b-implementation-spec.md §2.2): Quant Core needs raw statement
    # line items, not FundamentalsRecord's pre-computed ratios. Added alongside
    # get_quarterly_fundamentals rather than replacing it — no existing caller is broken.
    def get_income_statements(
        self, ticker: str, as_of: date | None = None
    ) -> list[IncomeStatement]: ...

    def get_balance_sheets(self, ticker: str, as_of: date | None = None) -> list[BalanceSheet]: ...

    def get_cash_flow_statements(
        self, ticker: str, as_of: date | None = None
    ) -> list[CashFlowStatement]: ...


class OptionsProvider(Protocol):
    """EOD-only for MVP (architecture v1.0, decision #1) — one snapshot per
    trading day, not a continuous feed. Delayed/real-time is a Phase 2
    swap-in behind this same interface."""

    def get_chain(self, ticker: str, as_of: date | None = None) -> list[OptionContract]: ...


class MacroProvider(Protocol):
    def get_series(
        self, series_id: str, start: date, end: date, as_of: date | None = None
    ) -> list[MacroObservation]: ...


class NewsProvider(Protocol):
    def get_news(self, ticker: str, since: datetime) -> list[NewsItem]: ...


class CorporateActionsProvider(Protocol):
    def get_actions(self, ticker: str, start: date, end: date) -> list[CorporateAction]: ...


class EconomicCalendarProvider(Protocol):
    def get_upcoming_events(
        self, start: date, end: date, importance: str | None = None
    ) -> list[EconomicCalendarEvent]: ...


class FilingsProvider(Protocol):
    def get_filings(
        self, ticker: str, filing_type: str | None = None, as_of: date | None = None
    ) -> list[FilingRecord]: ...


class AnalystEstimatesProvider(Protocol):
    def get_estimates(
        self, ticker: str, period_end: date, as_of: date | None = None
    ) -> list[AnalystEstimate]: ...


__all__ = [
    "MarketDataProvider",
    "FundamentalsProvider",
    "OptionsProvider",
    "MacroProvider",
    "NewsProvider",
    "CorporateActionsProvider",
    "EconomicCalendarProvider",
    "FilingsProvider",
    "AnalystEstimatesProvider",
]
