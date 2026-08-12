"""Quality raw metrics — ROIC (with/ex goodwill), DuPont ROE, ROA, margins, margin stability,
ROIIC. Pure functions, no I/O, no LLM (methodology §4). Every function returns a `MetricResult`,
never a bare float, so N/A/LOW_RELIABILITY reasons survive to the caller (spec §6)."""

import statistics

from packages.quant_core.results import MetricResult


def roic(nopat: float | None, invested_capital: float | None) -> MetricResult:
    """ROIC computed WITH goodwill (H5) — `invested_capital` must already include goodwill
    as-reported; that's the caller's responsibility (this function doesn't know about goodwill
    at all, it just divides). See `roic_ex_goodwill` for the diagnostic-only counterpart."""
    if nopat is None or invested_capital is None:
        return MetricResult.na("ROIC — missing NOPAT or Invested Capital")
    if invested_capital == 0:
        return MetricResult.na("ROIC — Invested Capital is zero")
    return MetricResult.ok(nopat / invested_capital)


def roic_ex_goodwill(nopat: float | None, invested_capital_ex_goodwill: float | None) -> MetricResult:
    """Diagnostic-only (H5) — never feeds QUALITY_SCORE."""
    if nopat is None or invested_capital_ex_goodwill is None:
        return MetricResult.na("ROIC_ex_goodwill — missing NOPAT or ex-goodwill Invested Capital")
    if invested_capital_ex_goodwill == 0:
        return MetricResult.na("ROIC_ex_goodwill — ex-goodwill Invested Capital is zero")
    return MetricResult.ok(nopat / invested_capital_ex_goodwill)


def roiic(delta_nopat: float | None, delta_invested_capital: float | None) -> MetricResult:
    if delta_nopat is None or delta_invested_capital is None:
        return MetricResult.na("ROIIC — needs two consecutive periods")
    if delta_invested_capital == 0:
        return MetricResult.na("ROIIC — ΔInvested Capital is zero")
    return MetricResult.ok(delta_nopat / delta_invested_capital)


def roic_spread(roic_result: MetricResult, cost_of_capital_hurdle_pct: float) -> MetricResult:
    """ROIC minus the (OPEN, provisional) cost-of-capital hurdle rate — QUALITY_SCORE rewards
    the spread, not the absolute ROIC level (methodology §4)."""
    if not roic_result.is_ok:
        return MetricResult.na(f"ROIC spread — underlying ROIC unavailable ({roic_result.reason})")
    return MetricResult.ok(roic_result.value - cost_of_capital_hurdle_pct / 100)


def roe_dupont(
    net_income: float | None,
    revenue: float | None,
    total_assets: float | None,
    book_equity: float | None,
    *,
    roe_soft_floor_pct_of_assets: float,
) -> MetricResult:
    """DuPont decomposition (Net Margin x Asset Turnover x Financial Leverage), with C3's two
    floors applied exactly:

    - Hard floor: book_equity <= 0 -> N/A (not tunable — dividing by zero/negative equity is
      not economically meaningful).
    - Soft floor: 0 < book_equity < roe_soft_floor_pct_of_assets * total_assets -> computed, but
      flagged LOW_RELIABILITY (still an OPEN, provisional threshold — see
      config/wealth_engine/open_parameters_v1.0.yaml).
    """
    if book_equity is None:
        return MetricResult.na("ROE excluded — book equity unavailable")
    if book_equity <= 0:
        return MetricResult.na("ROE excluded — book equity <= 0")
    if net_income is None or revenue is None or total_assets is None:
        return MetricResult.na("ROE excluded — missing net income, revenue, or total assets")
    if revenue == 0 or total_assets == 0:
        return MetricResult.na("ROE excluded — revenue or total assets is zero")

    net_margin = net_income / revenue
    asset_turnover = revenue / total_assets
    financial_leverage = total_assets / book_equity
    roe = net_margin * asset_turnover * financial_leverage

    if book_equity < roe_soft_floor_pct_of_assets * total_assets:
        return MetricResult.low_reliability(roe, "ROE reliability reduced — thin equity base")
    return MetricResult.ok(roe)


def roa(net_income: float | None, total_assets: float | None) -> MetricResult:
    if net_income is None or total_assets is None:
        return MetricResult.na("ROA — missing net income or total assets")
    if total_assets == 0:
        return MetricResult.na("ROA — total assets is zero")
    return MetricResult.ok(net_income / total_assets)


def _margin(numerator: float | None, revenue: float | None, name: str) -> MetricResult:
    if numerator is None or revenue is None:
        return MetricResult.na(f"{name} — missing numerator or revenue")
    if revenue == 0:
        return MetricResult.na(f"{name} — revenue is zero")
    return MetricResult.ok(numerator / revenue)


def gross_margin(gross_profit: float | None, revenue: float | None) -> MetricResult:
    return _margin(gross_profit, revenue, "Gross margin")


def operating_margin(operating_income: float | None, revenue: float | None) -> MetricResult:
    return _margin(operating_income, revenue, "Operating margin")


def fcf_margin(fcf: float | None, revenue: float | None) -> MetricResult:
    return _margin(fcf, revenue, "FCF margin")


def ebitda_margin(ebitda: float | None, revenue: float | None) -> MetricResult:
    return _margin(ebitda, revenue, "EBITDA margin")


def margin_stability(trailing_margins: list[float] | None) -> MetricResult:
    """Trailing stddev of margins — stable-or-expanding beats volatile at the same average
    (methodology §4). Lower stddev = more stable; this returns the raw stddev (a "smaller is
    better" raw metric), normalization/inversion happens at the scoring layer."""
    if not trailing_margins or len(trailing_margins) < 2:
        return MetricResult.na("Margin stability — needs >= 2 periods")
    return MetricResult.ok(statistics.pstdev(trailing_margins))
