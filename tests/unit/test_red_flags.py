"""Red flag registry (methodology §21) — H4's exact firing condition plus a false-positive
guard, and confirmation that the buyback/M&A-dependent detectors correctly return None (not a
fabricated result) given this MVP's data gap."""

from packages.engines.wealth_engine import red_flags


def test_h4_fires_on_melting_ice_cube_pattern():
    flag = red_flags.revenue_decline_masked_by_margin_expansion(
        revenue_growth_yoy=-0.05, ebitda_margin_current=0.30, ebitda_margin_prior=0.25,
        ebitda_growth_yoy=0.02, threshold_pp=2,
    )
    assert flag is not None
    assert flag.code == "REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION"
    assert flag.mechanism.value == "informational"  # H4: never a score deduction


def test_h4_does_not_fire_just_under_threshold():
    flag = red_flags.revenue_decline_masked_by_margin_expansion(
        revenue_growth_yoy=-0.05, ebitda_margin_current=0.251, ebitda_margin_prior=0.25,
        ebitda_growth_yoy=0.02, threshold_pp=2,
    )
    assert flag is None


def test_h4_does_not_fire_when_revenue_growing():
    flag = red_flags.revenue_decline_masked_by_margin_expansion(
        revenue_growth_yoy=0.05, ebitda_margin_current=0.30, ebitda_margin_prior=0.25,
        ebitda_growth_yoy=0.10, threshold_pp=2,
    )
    assert flag is None


def test_earnings_fcf_divergence_fires():
    flag = red_flags.earnings_fcf_divergence(net_income_growth=0.10, fcf_growth=-0.05)
    assert flag is not None


def test_earnings_fcf_divergence_does_not_fire_when_both_growing():
    flag = red_flags.earnings_fcf_divergence(net_income_growth=0.10, fcf_growth=0.08)
    assert flag is None


def test_buyback_dependent_detectors_return_none_not_a_fabricated_result():
    """Data gap, not a methodology decision — see implementation spec §2.3. These must never
    invent a firing result from absent data."""
    assert red_flags.acquisition_driven_growth() is None
    assert red_flags.debt_funded_buybacks() is None


def test_restatement_detected_fires_on_differing_values_same_period():
    from datetime import datetime

    records = [(100.0, datetime(2025, 8, 1)), (105.0, datetime(2025, 9, 15))]
    flag = red_flags.restatement_detected(records)
    assert flag is not None
    assert flag.code == "RESTATEMENT_DETECTED"


def test_restatement_not_detected_when_values_match():
    from datetime import datetime

    records = [(100.0, datetime(2025, 8, 1)), (100.0, datetime(2025, 9, 15))]
    assert red_flags.restatement_detected(records) is None


def test_all_sixteen_codes_are_registered():
    assert len(red_flags.ALL_RED_FLAG_CODES) == 16
    assert set(red_flags.REGISTRY.keys()) == set(red_flags.ALL_RED_FLAG_CODES)
