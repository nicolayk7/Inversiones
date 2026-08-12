"""Valuation raw metrics (methodology §10). Pure functions, no I/O, no LLM. FCF Yield lives here
(C1) — it was removed from FCF_SCORE and belongs exclusively to VALUATION_SCORE."""

from packages.quant_core.results import MetricResult


def gaap_eps(net_income: float | None, diluted_shares: float | None) -> MetricResult:
    """GAAP EPS (H6): Net Income / diluted shares, code-computed only — never a company-reported
    "Adjusted EPS" fallback."""
    if net_income is None or diluted_shares is None:
        return MetricResult.na("GAAP EPS — missing net income or diluted shares")
    if diluted_shares == 0:
        return MetricResult.na("GAAP EPS — diluted shares is zero")
    return MetricResult.ok(net_income / diluted_shares)


def enterprise_value(
    market_cap: float | None,
    total_debt: float | None,
    minority_interest: float | None,
    minority_interest_known: bool,
    preferred_equity: float | None,
    preferred_equity_known: bool,
    cash_and_equivalents: float | None,
) -> MetricResult:
    """EV = Market Cap + Total Debt + Minority Interest + Preferred Equity - Cash (M4).

    Unavailable-component treatment, exactly as specified: minority interest / preferred equity
    default to $0 only when NOT known to exist (`*_known=False`); if known to exist but the
    figure itself is missing, EV is N/A — never silently defaulted to $0 in that case, since that
    would understate EV specifically for the companies where the omission matters most.
    """
    if market_cap is None or total_debt is None or cash_and_equivalents is None:
        return MetricResult.na("EV — missing market cap, total debt, or cash")

    if minority_interest is not None:
        mi = minority_interest
    elif not minority_interest_known:
        mi = 0.0
    else:
        return MetricResult.na("EV — known minority interest, figure unsourced (M4)")

    if preferred_equity is not None:
        pe = preferred_equity
    elif not preferred_equity_known:
        pe = 0.0
    else:
        return MetricResult.na("EV — known preferred equity, figure unsourced (M4)")

    return MetricResult.ok(market_cap + total_debt + mi + pe - cash_and_equivalents)


def market_cap(price: float | None, diluted_shares_outstanding: float | None) -> MetricResult:
    """Derived Quant Core input — combining a daily price with a quarterly share count is the
    canonical mixed-cadence case §10.1 of the implementation spec governs. The CALLER is
    responsible for resolving each side's own `available_at <= as_of` before calling this (see
    `packages.quant_core.backtest.latest_eligible`) — this function itself is just the product."""
    if price is None or diluted_shares_outstanding is None:
        return MetricResult.na("Market cap — missing price or diluted shares outstanding")
    return MetricResult.ok(price * diluted_shares_outstanding)


def pe_ratio(price: float | None, eps: MetricResult) -> MetricResult:
    """Requires positive trailing/forward GAAP EPS — else N/A (methodology §10)."""
    if price is None:
        return MetricResult.na("P/E — missing price")
    if not eps.is_ok or eps.value is None or eps.value <= 0:
        return MetricResult.na("P/E — requires positive GAAP EPS")
    return MetricResult.ok(price / eps.value)


def fcf_yield(fcf: float | None, market_cap_value: float | None) -> MetricResult:
    """C1 — FCF Yield lives exclusively in VALUATION_SCORE, never in FCF_SCORE."""
    if fcf is None or market_cap_value is None:
        return MetricResult.na("FCF Yield — missing FCF or market cap")
    if market_cap_value == 0:
        return MetricResult.na("FCF Yield — market cap is zero")
    return MetricResult.ok(fcf / market_cap_value)


def price_to_book(price: float | None, book_equity: float | None, diluted_shares: float | None) -> MetricResult:
    """P/B — the primary Financials-sector metric (Banks, per methodology §10's sector profile
    table; also the metric the Insurance sector gate currently blocks pending its own approval,
    see packages/quant_core/regime/sector_profile.py)."""
    if price is None or book_equity is None or diluted_shares is None:
        return MetricResult.na("P/B — missing price, book equity, or diluted shares")
    if diluted_shares == 0 or book_equity <= 0:
        return MetricResult.na("P/B — book equity must be positive and diluted shares nonzero")
    book_value_per_share = book_equity / diluted_shares
    return MetricResult.ok(price / book_value_per_share)
