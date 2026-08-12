"""Balance sheet / financial strength raw metrics (methodology §6). Pure functions, no I/O, no
LLM."""

from packages.quant_core.results import MetricResult


def net_debt(total_debt: float | None, cash_and_equivalents: float | None) -> MetricResult:
    if total_debt is None or cash_and_equivalents is None:
        return MetricResult.na("Net Debt — missing total debt or cash")
    return MetricResult.ok(total_debt - cash_and_equivalents)


def gaap_ebitda(
    revenue: float | None,
    cogs: float | None,
    operating_expenses: float | None,
    depreciation_amortization: float | None,
) -> MetricResult:
    """GAAP-consistent EBITDA (H6): Revenue - COGS - Opex + D&A, code-computed only. If any
    component is missing, N/A — there is NO fallback to a provider's "Adjusted EBITDA"; that is
    a hard rule (H6), not a coding convenience that could accidentally regress into one."""
    components = (revenue, cogs, operating_expenses, depreciation_amortization)
    if any(c is None for c in components):
        return MetricResult.na(
            "GAAP EBITDA — missing a GAAP component; NEVER backfilled from Adjusted EBITDA (H6)"
        )
    return MetricResult.ok(revenue - cogs - operating_expenses + depreciation_amortization)


def debt_to_ebitda(net_debt_value: float | None, ebitda: float | None) -> MetricResult:
    if net_debt_value is None or ebitda is None:
        return MetricResult.na("Net Debt/EBITDA — missing net debt or EBITDA")
    if ebitda == 0:
        return MetricResult.na("Net Debt/EBITDA — EBITDA is zero")
    return MetricResult.ok(net_debt_value / ebitda)


def interest_coverage(ebit: float | None, interest_expense: float | None) -> MetricResult:
    if ebit is None or interest_expense is None:
        return MetricResult.na("Interest coverage — missing EBIT or interest expense")
    if interest_expense == 0:
        return MetricResult.na("Interest coverage — interest expense is zero")
    return MetricResult.ok(ebit / interest_expense)


def net_debt_to_fcf(net_debt_value: float | None, fcf: float | None) -> MetricResult:
    if net_debt_value is None or fcf is None:
        return MetricResult.na("Net Debt/FCF — missing net debt or FCF")
    if fcf == 0:
        return MetricResult.na("Net Debt/FCF — FCF is zero")
    return MetricResult.ok(net_debt_value / fcf)


def leverage_band(net_debt_to_ebitda: float | None, interest_coverage_value: float | None, bands: list[float]) -> MetricResult:
    """Classify into the generic leverage bands (methodology §6). `bands` is the 3-cutoff list
    [low, moderate, high] from the OPEN `leverage_bands_generic`/`leverage_bands_utilities`
    config (provisional, not calibrated) — Financial Stress is the 4th, implicit band above the
    top cutoff OR interest coverage < 2.0x."""
    if net_debt_to_ebitda is None:
        return MetricResult.na("Leverage band — missing Net Debt/EBITDA")
    low, moderate, high = bands
    if interest_coverage_value is not None and interest_coverage_value < 2.0:
        return MetricResult.ok(4)  # Financial Stress, forced by the interest-coverage trigger
    if net_debt_to_ebitda < 0:
        return MetricResult.ok(0)  # Net Cash
    if net_debt_to_ebitda <= low:
        return MetricResult.ok(1)  # Low Leverage
    if net_debt_to_ebitda <= moderate:
        return MetricResult.ok(2)  # Moderate Leverage
    if net_debt_to_ebitda <= high:
        return MetricResult.ok(3)  # High Leverage
    return MetricResult.ok(4)  # Financial Stress
