"""compose_score: COUNT-based coverage (not weight-weighted), N/A-exclusion-and-renormalization
within a group. wealth_score_raw/business_quality_composite: the frozen top-level weights are
never renormalized over a partial set — proven here by showing a missing MOAT_SCORE blocks the
whole formula rather than silently redistributing its weight."""

import pytest

from packages.quant_core.results import MetricResult
from packages.quant_core.scoring.composition import business_quality_composite, compose_score, group_coverage, wealth_score_raw


def test_group_coverage_is_count_based_not_weight_weighted():
    """A present-but-tiny-weight metric and a present-but-huge-weight metric must count the
    same toward coverage — proof that coverage never reads `weight_set` at all."""
    sub_metrics = {
        "a": MetricResult.ok(1.0),
        "b": MetricResult.na("missing"),
    }
    assert group_coverage(sub_metrics) == pytest.approx(0.5)


def test_compose_score_insufficient_data_below_threshold():
    sub_metrics = {"a": MetricResult.ok(10.0), "b": MetricResult.na("x"), "c": MetricResult.na("x")}
    weight_set = {"a": 0.34, "b": 0.33, "c": 0.33}
    result = compose_score(sub_metrics, weight_set, min_coverage_pct=0.60)
    assert result.status.value == "INSUFFICIENT_DATA"


def test_compose_score_excludes_na_and_renormalizes_within_group():
    sub_metrics = {"a": MetricResult.ok(10.0), "b": MetricResult.ok(20.0), "c": MetricResult.na("x")}
    weight_set = {"a": 0.5, "b": 0.3, "c": 0.2}
    result = compose_score(sub_metrics, weight_set, min_coverage_pct=0.60)
    assert result.is_ok
    # a and b renormalized: 0.5/0.8=0.625, 0.3/0.8=0.375
    expected = 10.0 * 0.625 + 20.0 * 0.375
    assert result.value == pytest.approx(expected)


def test_compose_score_synthetic_weights_never_claim_production_status():
    """This test's weight_set is explicitly synthetic — proving the math, not approving values
    (principle 2). Sanity check that equal-ish synthetic weights average correctly."""
    sub_metrics = {"x": MetricResult.ok(50.0), "y": MetricResult.ok(100.0)}
    weight_set = {"x": 0.5, "y": 0.5}
    result = compose_score(sub_metrics, weight_set, min_coverage_pct=0.5)
    assert result.value == pytest.approx(75.0)


WEALTH_WEIGHTS = {"quality": 0.25, "growth": 0.25, "fcf": 0.15, "moat": 0.15, "valuation": 0.20}


def test_wealth_score_raw_requires_all_five_no_renormalization():
    """The exact consequence of Moat being fully deferred in Phase 1B: WEALTH_SCORE_RAW cannot
    resolve OK for a real ticker, because there is no silent renormalization over the frozen
    top-level weights."""
    components = {
        "quality": MetricResult.ok(80.0), "growth": MetricResult.ok(70.0),
        "fcf": MetricResult.ok(60.0), "valuation": MetricResult.ok(50.0),
        "moat": MetricResult.unsupported("deferred"),
    }
    result = wealth_score_raw(components, WEALTH_WEIGHTS)
    assert result.status.value == "N/A"
    assert "moat" in result.reason


def test_wealth_score_raw_computes_with_synthetic_fixture_moat():
    """Only a synthetic/fixture MOAT_SCORE (never live) lets this formula's arithmetic be
    proven — exactly the same pattern used for sub-metric weight fixtures."""
    components = {
        "quality": MetricResult.ok(80.0), "growth": MetricResult.ok(70.0),
        "fcf": MetricResult.ok(60.0), "valuation": MetricResult.ok(50.0),
        "moat": MetricResult.ok(90.0),  # SYNTHETIC test fixture only
    }
    result = wealth_score_raw(components, WEALTH_WEIGHTS)
    assert result.is_ok
    expected = 0.25 * 80 + 0.25 * 70 + 0.15 * 60 + 0.15 * 90 + 0.20 * 50
    assert result.value == pytest.approx(expected)


def test_business_quality_composite_also_blocked_by_missing_moat():
    components = {
        "quality": MetricResult.ok(80.0), "growth": MetricResult.ok(70.0),
        "fcf": MetricResult.ok(60.0), "moat": MetricResult.unsupported("deferred"),
    }
    result = business_quality_composite(components, WEALTH_WEIGHTS)
    assert result.status.value == "N/A"


def test_business_quality_composite_rescales_frozen_ratios_with_fixture_moat():
    components = {
        "quality": MetricResult.ok(80.0), "growth": MetricResult.ok(70.0),
        "fcf": MetricResult.ok(60.0), "moat": MetricResult.ok(90.0),
    }
    result = business_quality_composite(components, WEALTH_WEIGHTS)
    assert result.is_ok
    raw = 0.25 * 80 + 0.25 * 70 + 0.15 * 60 + 0.15 * 90
    assert result.value == pytest.approx(raw / 0.80)
