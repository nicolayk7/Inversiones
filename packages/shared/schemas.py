"""Base DTOs returned by provider interfaces (packages/providers/base.py).

Each one mirrors the corresponding table sketched in the architecture doc
(§05) closely enough that mapping to a real SQLAlchemy model later is
mechanical. Fields beyond what Phase 0 needs are intentionally omitted —
providers are not implemented yet, so a speculative full schema would just be
guesswork to redo later.
"""

from datetime import date, datetime

from pydantic import BaseModel

from packages.shared.point_in_time import PeriodicRecordFields, ProvenanceFields


class OHLCVBar(BaseModel):
    """`ts` is the trading day the bar describes; `available_at` is when *this system* could have
    known it — the two are NOT assumed equal (Market Data Foundation Phase 1 decision). A provider
    without a real publication-lag timestamp must still populate `available_at` via an explicit,
    documented convention in its own adapter (see `packages.providers.fundamentals.sec_edgar`'s
    `_available_at` for the equivalent pattern on the fundamentals side) — never leave it assumed
    equal to `ts` silently."""

    ticker: str
    ts: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    available_at: datetime
    source: str


class FundamentalsRecord(PeriodicRecordFields):
    ticker: str
    revenue: float | None = None
    eps: float | None = None
    fcf: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    roic: float | None = None
    roe: float | None = None
    net_debt: float | None = None
    debt_ebitda: float | None = None
    source: str


class IncomeStatement(PeriodicRecordFields):
    """Normalized statement DTO (Phase 1B design decision: normalized financial-statement
    concepts, not a flat FundamentalsRecord extension — see
    docs/wealth-engine-phase1b-implementation-spec.md §2.2). Carries its own point-in-time
    provenance independently of BalanceSheet/CashFlowStatement — do not assume a matching
    period_end implies a matching reported_at/source; an amendment can restate one statement
    without the others (§2.2's cross-statement consistency requirement)."""

    ticker: str
    revenue: float | None = None
    cogs: float | None = None
    operating_expenses: float | None = None
    net_income: float | None = None
    diluted_shares_outstanding: float | None = None
    interest_expense: float | None = None
    ebit: float | None = None
    stock_based_compensation: float | None = None
    source: str


class BalanceSheet(PeriodicRecordFields):
    """See IncomeStatement docstring — same normalized-statement, independent-provenance design.

    `minority_interest_known` / `preferred_equity_known` carry the M4 "known to be $0 vs.
    genuinely unsourced" distinction explicitly, since a bare `None` can't distinguish them:
    unknown=False means "not known to exist, correct to default to $0"; unknown=True with the
    amount itself None means "known to exist, but the figure could not be sourced" (→ EV = N/A,
    never silently defaulted)."""

    ticker: str
    total_assets: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    minority_interest: float | None = None
    minority_interest_known: bool = False
    preferred_equity: float | None = None
    preferred_equity_known: bool = False
    book_equity: float | None = None
    goodwill: float | None = None
    inventory: float | None = None
    receivables: float | None = None
    source: str


class CashFlowStatement(PeriodicRecordFields):
    """See IncomeStatement docstring — same normalized-statement, independent-provenance design."""

    ticker: str
    operating_cash_flow: float | None = None
    depreciation_amortization: float | None = None
    capex: float | None = None
    delta_working_capital: float | None = None
    source: str


class OptionContract(BaseModel):
    ticker: str
    captured_at: datetime
    expiration: date
    strike: float
    option_type: str  # "call" | "put"
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    open_interest: int | None = None
    volume: int | None = None


class MacroObservation(BaseModel):
    series_id: str
    ts: date
    value: float
    available_at: datetime  # first-publication vintage (architecture v1.0, decision #10)


class NewsItem(BaseModel):
    ticker: str | None
    headline: str
    url: str | None = None
    published_at: datetime


class CorporateAction(BaseModel):
    ticker: str
    action_type: str  # "split" | "dividend" | "spinoff"
    effective_at: date
    ratio: float | None = None
    amount: float | None = None
    source: str


class EconomicCalendarEvent(BaseModel):
    event_type: str  # "FOMC" | "CPI" | "PCE" | "NFP" | "GDP" | "ISM" | "JOBLESS_CLAIMS" | "EARNINGS"
    ticker: str | None = None  # set only for EARNINGS
    scheduled_at: datetime
    importance: str  # "high" | "medium" | "low"
    consensus: float | None = None
    previous: float | None = None
    actual: float | None = None
    actual_reported_at: datetime | None = None


class FilingRecord(BaseModel):
    ticker: str
    filing_type: str  # "10-K" | "10-Q" | "8-K" | "transcript"
    filed_at: date
    available_at: datetime
    url: str | None = None


class AnalystEstimate(BaseModel):
    ticker: str
    period_end: date
    metric: str  # "eps" | "revenue"
    consensus: float | None = None
    high: float | None = None
    low: float | None = None
    num_analysts: int | None = None
    available_at: datetime


__all__ = [
    "ProvenanceFields",
    "PeriodicRecordFields",
    "OHLCVBar",
    "FundamentalsRecord",
    "IncomeStatement",
    "BalanceSheet",
    "CashFlowStatement",
    "OptionContract",
    "MacroObservation",
    "NewsItem",
    "CorporateAction",
    "EconomicCalendarEvent",
    "FilingRecord",
    "AnalystEstimate",
]
