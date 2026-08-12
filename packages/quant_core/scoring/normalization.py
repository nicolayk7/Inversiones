"""Normalization Engine (methodology §13). Every metric becomes a 0-100 sub-score before entering
any weighted aggregation. Five methods are named in the methodology (percentile ranking, z-score,
fixed-bound min-max, sector-relative percentile, historical percentile) — sector-relative and
historical percentile both reduce to the same `percentile_rank` primitive applied against a
different caller-supplied distribution (peer set vs. own-history), so this module implements the
underlying primitives rather than five separate named functions; which distribution to pass is
the caller's responsibility (an IMPLEMENTATION-DETAIL simplification, not a methodology change —
§13 itself describes the five methods as differing only in which distribution/bounds are used).

Winsorization vs. clipping: winsorizing caps at a *sample-derived* percentile (needs a
distribution); clipping caps at a *fixed domain value* (economic plausibility, e.g. ROIC capped
at 100%). Both are implemented, kept distinct.
"""

from packages.quant_core.results import MetricResult


def clip(value: float, floor: float, ceiling: float) -> float:
    """Fixed-domain clipping — e.g. ROIC capped at 100% (methodology §13). The raw value is
    always preserved by the caller for display; only the score contribution is clipped here."""
    return max(floor, min(ceiling, value))


def winsorize(value: float, distribution: list[float], lower_pct: float, upper_pct: float) -> float:
    """Sample-derived percentile capping. `distribution` must include enough points to compute
    percentiles meaningfully — with a single-ticker MVP and no live Universe (methodology §23 is
    still OPEN), callers typically pass a synthetic/test distribution; this is a structural MVP
    limitation, not a methodology shortcut (see implementation report)."""
    if not distribution:
        return value
    sorted_dist = sorted(distribution)
    n = len(sorted_dist)
    lower_idx = int(round(lower_pct / 100 * (n - 1)))
    upper_idx = int(round(upper_pct / 100 * (n - 1)))
    lower_bound = sorted_dist[lower_idx]
    upper_bound = sorted_dist[upper_idx]
    return clip(value, lower_bound, upper_bound)


def min_max_normalize(value: float | None, floor: float, ceiling: float) -> MetricResult:
    """Fixed-bound min-max -> 0-100. Methodology §13's prescribed method for margins,
    ROIC/ROE/ROIIC-family "level" metrics: "Requires domain-reasoned floor/ceiling, not sample
    min/max" — `floor`/`ceiling` must be domain-reasoned bounds supplied by the caller, never
    derived from the sample itself."""
    if value is None:
        return MetricResult.na("Normalization — missing value")
    if ceiling == floor:
        return MetricResult.na("Normalization — floor and ceiling are equal, cannot normalize")
    clipped = clip(value, floor, ceiling)
    score = (clipped - floor) / (ceiling - floor) * 100
    return MetricResult.ok(score)


def percentile_rank(value: float | None, distribution: list[float]) -> MetricResult:
    """value's percentile rank (0-100) within `distribution` — the shared primitive behind both
    "sector-relative percentile" (distribution = peer set) and "historical (own-history)
    percentile" (distribution = the ticker's own trailing window), per this module's docstring."""
    if value is None:
        return MetricResult.na("Percentile rank — missing value")
    if not distribution:
        return MetricResult.na("Percentile rank — empty distribution")
    n = len(distribution)
    rank = sum(1 for d in distribution if d <= value)
    return MetricResult.ok(rank / n * 100)
