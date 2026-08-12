"""OPEN-parameter loader — every value is the same illustrative number already logged OPEN in
the methodology; the file is PROVISIONAL and rejected under production, same pattern as
component weights (rule 6)."""

import pytest

from packages.shared.open_parameters import ProvisionalOpenParametersRejectedError, load_open_parameters


def test_provisional_open_parameters_load_in_dev():
    params = load_open_parameters("v1.0", allow_provisional=True)
    assert params.status.value == "PROVISIONAL"
    assert params["h4_margin_expansion_threshold_pp"] == 2
    assert params["min_group_coverage_pct"] == 60


def test_provisional_open_parameters_rejected_under_production():
    with pytest.raises(ProvisionalOpenParametersRejectedError):
        load_open_parameters("v1.0", allow_provisional=False)


def test_every_canonical_open_parameter_is_present():
    params = load_open_parameters("v1.0", allow_provisional=True).values
    expected_keys = {
        "roe_soft_floor_pct_of_assets", "quality_tier_cutoff", "historical_valuation_bands_pct",
        "cost_of_capital_hurdle_pct", "leverage_bands_generic", "leverage_bands_utilities",
        "winsorization_bounds_pct", "peg_applicable_growth_range_pct",
        "gross_margin_peer_band_width_pp", "data_quality_staleness_qtrs",
        "cycle_normalization_window_yrs", "min_history_years", "structural_break_mcap_pct",
        "structural_break_revenue_yoy_pct", "working_capital_fcf_flag_threshold_pct",
        "debt_funded_buyback_score_ceiling", "h4_margin_expansion_threshold_pp",
        "min_group_coverage_pct", "universe_market_cap_floor_usd",
        "universe_liquidity_floor_usd_per_day", "universe_min_listed_history_yrs",
    }
    assert expected_keys <= set(params.keys())
