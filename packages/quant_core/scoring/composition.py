"""Composition layer (methodology §14). Two independent concerns, kept deliberately separate
(Phase 1B design decision, group coverage round):

- COVERAGE — whether enough sub-metrics are present to compute a group score at all. COUNT-based:
  `len(present) / len(total)`, never weight-weighted.
- WEIGHTING — how much each present sub-metric counts once coverage clears the bar. This is
  exactly what the sub-metric-weight blocker (implementation spec §0.2) gates: `compose_score`
  takes `weight_set` as a caller-supplied argument, never reads a hardcoded/embedded production
  value. The only weight sets that exist right now are the PROVISIONAL development fixtures under
  `config/weights/wealth_components/` — see `packages/shared/component_weights.py`.

`WEALTH_SCORE_RAW` and `business_quality_composite` use the FROZEN top-level weights from
`config/weights/v1.0.yaml` directly (untouched, unmodified) — a completely different, already
-approved config surface from the sub-metric one above.
"""

from packages.quant_core.results import MetricResult, MetricStatus


def group_coverage(sub_metrics: dict[str, MetricResult]) -> float:
    """COUNT-based coverage — human decision, group-coverage round of the Phase 1B design
    closure. `sub_metrics` must contain one entry per sub-metric this group is *supposed* to
    have (whether OK or not) — coverage is present-count / total-count, independent of any
    sub-metric's eventual weight."""
    if not sub_metrics:
        return 0.0
    present = sum(1 for m in sub_metrics.values() if m.status == MetricStatus.OK)
    return present / len(sub_metrics)


def compose_score(
    sub_metrics: dict[str, MetricResult],
    weight_set: dict[str, float],
    *,
    min_coverage_pct: float,
) -> MetricResult:
    """Generic, deterministic weighted-aggregation utility (implementation spec §5).

    `weight_set` must cover every key in `sub_metrics` (a `KeyError` on a missing key is
    intentional — silently ignoring an unweighted sub-metric would be worse than failing loudly).
    `min_coverage_pct` is a plain fraction in [0, 1] (the OPEN `min_group_coverage_pct` value,
    e.g. 60 -> 0.60, is the caller's responsibility to convert).
    """
    coverage = group_coverage(sub_metrics)
    if coverage < min_coverage_pct:
        return MetricResult.insufficient_data(
            f"Group coverage {coverage:.0%} below the {min_coverage_pct:.0%} threshold "
            f"({sum(1 for m in sub_metrics.values() if m.status == MetricStatus.OK)}/"
            f"{len(sub_metrics)} sub-metrics present)"
        )

    present = {k: v for k, v in sub_metrics.items() if v.status == MetricStatus.OK}
    if not present:
        return MetricResult.insufficient_data("No sub-metrics present")

    present_weight_total = sum(weight_set[k] for k in present)
    if present_weight_total == 0:
        return MetricResult.insufficient_data("Present sub-metrics carry zero combined weight")

    normalized_weight = {k: weight_set[k] / present_weight_total for k in present}
    value = sum(v.value * normalized_weight[k] for k, v in present.items())
    return MetricResult.ok(value)


def wealth_score_raw(component_scores: dict[str, MetricResult], wealth_weights: dict[str, float]) -> MetricResult:
    """WEALTH_SCORE_RAW = sum(frozen_weight[c] * component_score[c]) over the five approved
    top-level components (Quality/Growth/FCF/Moat/Valuation). This does NOT drop a missing
    component and renormalize over the rest — that would be an implicit change to the approved
    top-level weights (forbidden by rule 2 of the Phase 1B implementation authorization), unlike
    the explicitly-approved N/A-exclusion-and-renormalization rule that applies WITHIN a
    sub-metric group (§13). All five components must resolve OK, or this is N/A.

    In Phase 1B, MOAT_SCORE is permanently deferred/blocked (design decision 8 — no aggregation
    code exists at all, see packages/engines/wealth_engine/eligibility.py) with no live-ticker
    substitute, so this function will not resolve to OK for any real ticker until Moat scoring is
    separately designed and approved. It IS exercised in tests against a synthetic/fixture
    `MOAT_SCORE` MetricResult, to prove the arithmetic — never against live data.
    """
    required = ("quality", "growth", "fcf", "moat", "valuation")
    missing = [c for c in required if c not in component_scores or component_scores[c].status != MetricStatus.OK]
    if missing:
        return MetricResult.na(
            f"WEALTH_SCORE_RAW — component(s) not OK: {', '.join(missing)} "
            "(top-level weights are frozen and never renormalized over a partial set)"
        )
    return MetricResult.ok(
        sum(wealth_weights[c] * component_scores[c].value for c in required)
    )


def business_quality_composite(component_scores: dict[str, MetricResult], wealth_weights: dict[str, float]) -> MetricResult:
    """(0.25*QUALITY + 0.25*GROWTH + 0.15*FCF + 0.15*MOAT) / 0.80 — reuses the frozen top-level
    ratios exactly as they exist in config/weights/v1.0.yaml, rescaled at read time (C5). Not a
    new weight set; inherits WEALTH_SCORE_RAW's same "all four must be OK, no renormalization
    over a partial set" rule, and therefore the same Moat-deferral blocker."""
    required = ("quality", "growth", "fcf", "moat")
    missing = [c for c in required if c not in component_scores or component_scores[c].status != MetricStatus.OK]
    if missing:
        return MetricResult.na(f"business_quality_composite — component(s) not OK: {', '.join(missing)}")
    non_valuation_weight = sum(wealth_weights[c] for c in required)
    raw = sum(wealth_weights[c] * component_scores[c].value for c in required)
    return MetricResult.ok(raw / non_valuation_weight)
