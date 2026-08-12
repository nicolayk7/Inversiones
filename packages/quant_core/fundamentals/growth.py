"""Growth raw metrics (methodology §3). Pure functions, no I/O, no LLM.

Net Income Growth is deliberately NOT exposed here as a `GROWTH_SCORE` composition input — per
the Phase 1B implementation spec §3, it is a diagnostic/reliability-adjustment signal for EPS
Growth only (methodology §3: "EPS vs Net Income growth split is mandatory"). See
`eps_growth_quality_adjustment` below."""

import statistics

from packages.quant_core.results import MetricResult


def yoy_growth(current: float | None, prior: float | None, *, name: str = "Growth") -> MetricResult:
    if current is None or prior is None:
        return MetricResult.na(f"{name} — missing current or prior period")
    if prior == 0:
        return MetricResult.na(f"{name} — prior period is zero, YoY % undefined")
    return MetricResult.ok((current - prior) / abs(prior))


def cagr(begin: float | None, end: float | None, years: float) -> MetricResult:
    if begin is None or end is None:
        return MetricResult.na("CAGR — missing begin or end value")
    if begin <= 0 or years <= 0:
        return MetricResult.na("CAGR — begin value must be positive and years > 0")
    return MetricResult.ok((end / begin) ** (1 / years) - 1)


def eps_growth_quality_adjustment(eps_growth: float | None, net_income_growth: float | None) -> str | None:
    """Net Income Growth's ONLY role in Growth scoring: flag when EPS growth outpaces it
    (buyback-driven share-count reduction, not business growth). Returns a reason string when the
    gap looks buyback-driven, else None — this is NOT a MetricResult and NOT a composition input;
    it only informs how EPSGrowth is weighted/labeled inside GROWTH_SCORE and feeds the §21
    DILUTION_OUTPACING_BUYBACK red-flag family.

    IMPLEMENTATION-DETAIL DECISION: the methodology says "materially outpaces" (§3) but never
    assigns that word a number, and it isn't in the OPEN-parameter table either (§26/§14 of the
    implementation spec) — inventing a magnitude cutoff here would be inventing a methodology
    value, which is out of scope. Smallest reversible choice: fire on ANY positive gap
    (eps_growth > net_income_growth), not a magnitude threshold. Revisit once/if "materially" is
    given an explicit, approved number.
    """
    if eps_growth is None or net_income_growth is None:
        return None
    if eps_growth > net_income_growth:
        return "EPS growth outpaces Net Income growth — possibly buyback-driven, not organic"
    return None


def growth_consistency(trailing_yoy_growth_rates: list[float] | None) -> MetricResult:
    """Trailing 5yr quarterly stddev of YoY growth (methodology §3) — caller supplies the
    already-windowed series; this function doesn't know about the 5yr window itself."""
    if not trailing_yoy_growth_rates or len(trailing_yoy_growth_rates) < 2:
        return MetricResult.na("Growth consistency — needs >= 2 periods")
    return MetricResult.ok(statistics.pstdev(trailing_yoy_growth_rates))


def growth_acceleration(trailing_4q_growth: float | None, prior_4q_growth: float | None) -> MetricResult:
    """Trailing 4Q vs. prior 4Q (methodology §3) — needs 8 quarters of underlying history to
    exist at all; that's a structural/mechanical minimum (not itself an OPEN calibratable
    parameter), enforced by the caller supplying `None` when insufficient history exists."""
    if trailing_4q_growth is None or prior_4q_growth is None:
        return MetricResult.na("Growth acceleration — needs 8 quarters of history (trailing 4Q vs prior 4Q)")
    return MetricResult.ok(trailing_4q_growth - prior_4q_growth)
