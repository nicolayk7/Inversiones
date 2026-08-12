"""FCF raw metrics (methodology §5). Pure functions, no I/O, no LLM.

`FCF_SCORE`'s four sub-metrics are FCF Margin, FCF Growth-or-Trajectory, FCF Conversion, FCF
Consistency. FCF Yield is deliberately NOT here (C1 — it lives exclusively in valuation.py /
VALUATION_SCORE)."""

from packages.quant_core.results import MetricResult


def compute_fcf(operating_cash_flow: float | None, capex: float | None) -> MetricResult:
    """FCF = Operating Cash Flow - CapEx (methodology §5, standard definition)."""
    if operating_cash_flow is None or capex is None:
        return MetricResult.na("FCF — missing operating cash flow or capex")
    return MetricResult.ok(operating_cash_flow - capex)


def fcf_conversion(fcf: float | None, net_income: float | None) -> MetricResult:
    """FCF Conversion = FCF / Net Income — hard N/A whenever Net Income <= 0 (C2), evaluated
    before any other N/A handling, regardless of FCF's own sign. Closes the sign-flip bug where
    both FCF and NI negative would otherwise compute a plausible-looking positive ratio."""
    if net_income is None:
        return MetricResult.na("FCF Conversion — missing Net Income")
    if net_income <= 0:
        return MetricResult.na("FCF Conversion — N/A when Net Income <= 0 (C2)")
    if fcf is None:
        return MetricResult.na("FCF Conversion — missing FCF")
    return MetricResult.ok(fcf / net_income)


def _sign(x: float) -> int:
    if x > 0:
        return 1
    if x < 0:
        return -1
    return 0


def fcf_growth_or_trajectory(
    prior_fcf: float | None,
    current_fcf: float | None,
    prior_fcf_margin: float | None,
    current_fcf_margin: float | None,
) -> tuple[str, MetricResult]:
    """M2's exact, corrected (Rev. 4) sign-safe switch:

        uses_trajectory = (prior_fcf <= 0) OR (sign(current_fcf) != sign(prior_fcf))

    NOT merely "prior_fcf <= 0" — that alone misses prior_fcf > 0, current_fcf < 0 (a company
    falling INTO negative FCF), which the two-condition disjunction form correctly routes to
    Trajectory. Returns (metric_name, MetricResult) so the caller/output layer can tell which of
    the two always-available formulas was used.
    """
    if prior_fcf is None or current_fcf is None:
        return "fcf_growth_or_trajectory", MetricResult.na(
            "FCF Growth/Trajectory — missing prior or current period FCF"
        )

    uses_trajectory = (prior_fcf <= 0) or (_sign(current_fcf) != _sign(prior_fcf))

    if uses_trajectory:
        if prior_fcf_margin is None or current_fcf_margin is None:
            return "fcf_trajectory_pp", MetricResult.na(
                "FCF Trajectory — missing prior or current FCF margin"
            )
        return "fcf_trajectory_pp", MetricResult.ok(current_fcf_margin - prior_fcf_margin)

    return "fcf_growth_pct", MetricResult.ok((current_fcf - prior_fcf) / abs(prior_fcf))


def fcf_consistency(trailing_fcf: list[float] | None) -> MetricResult:
    """% of trailing periods FCF-positive — a simple, always-available consistency proxy
    (methodology §5: "Volatility across periods, % of periods FCF-positive")."""
    if not trailing_fcf:
        return MetricResult.na("FCF consistency — no trailing FCF history")
    positive_periods = sum(1 for f in trailing_fcf if f > 0)
    return MetricResult.ok(positive_periods / len(trailing_fcf))
