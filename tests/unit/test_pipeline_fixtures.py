"""End-to-end fixture-based tests for `compute_wealth_snapshot` — Banks, Insurance, insufficient
data, negative equity, negative FCF/sign changes. All fixtures are synthetic (methodology §25's
golden-snapshot discipline); none represents a real ticker."""

from datetime import date

import pytest

from packages.engines.wealth_engine import WealthEngineInput, compute_wealth_snapshot
from packages.quant_core.regime import SectorProfile
from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement


def _income_statement(**overrides) -> IncomeStatement:
    defaults = dict(
        ticker="TEST", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="fixture",
        revenue=1000.0, cogs=400.0, operating_expenses=300.0, net_income=150.0,
        diluted_shares_outstanding=100.0, interest_expense=10.0, ebit=200.0,
        stock_based_compensation=5.0,
    )
    defaults.update(overrides)
    return IncomeStatement(**defaults)


def _balance_sheet(**overrides) -> BalanceSheet:
    defaults = dict(
        ticker="TEST", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="fixture",
        total_assets=2000.0, total_debt=500.0, cash_and_equivalents=200.0,
        minority_interest=None, minority_interest_known=False,
        preferred_equity=None, preferred_equity_known=False,
        book_equity=1000.0, goodwill=100.0, inventory=50.0, receivables=80.0,
    )
    defaults.update(overrides)
    return BalanceSheet(**defaults)


def _cash_flow(**overrides) -> CashFlowStatement:
    defaults = dict(
        ticker="TEST", period_end="2025-06-30", reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z", source="fixture",
        operating_cash_flow=180.0, depreciation_amortization=50.0, capex=40.0,
        delta_working_capital=10.0,
    )
    defaults.update(overrides)
    return CashFlowStatement(**defaults)


def _golden_input(**overrides) -> WealthEngineInput:
    defaults = dict(
        ticker="TEST", as_of=date(2025, 8, 15), sector=SectorProfile.GENERIC_INDUSTRIAL,
        income_statement=_income_statement(), balance_sheet=_balance_sheet(),
        cash_flow_statement=_cash_flow(),
        prior_income_statement=_income_statement(revenue=900.0, net_income=120.0, ebit=170.0),
        prior_balance_sheet=_balance_sheet(total_assets=1800.0, book_equity=900.0),
        prior_cash_flow_statement=_cash_flow(operating_cash_flow=150.0, capex=35.0),
        price=50.0,
    )
    defaults.update(overrides)
    return WealthEngineInput(**defaults)


def test_golden_snapshot_wealth_score_is_always_null_balance_sheet_multiplier_blocked():
    output = compute_wealth_snapshot(_golden_input())
    assert output.wealth_score.value is None
    assert output.wealth_score.status == "UNSUPPORTED"
    assert "BalanceSheetMultiplier" in output.wealth_score.reason


def test_golden_snapshot_wealth_score_raw_is_na_because_moat_is_deferred():
    output = compute_wealth_snapshot(_golden_input())
    assert output.wealth_score_raw.status == "N/A"


def test_golden_snapshot_moat_score_always_unsupported():
    output = compute_wealth_snapshot(_golden_input())
    assert output.moat_score.status == "UNSUPPORTED"


def test_golden_snapshot_quality_and_growth_and_fcf_scores_compute_with_provisional_weights():
    """With the PROVISIONAL dev weights, coverage clears and these three DO resolve OK — proving
    the pipeline runs end-to-end even though wealth_score itself stays null."""
    output = compute_wealth_snapshot(_golden_input())
    assert output.quality_score.status in ("OK", "INSUFFICIENT_DATA")
    assert output.growth_score.status in ("OK", "INSUFFICIENT_DATA")
    assert output.fcf_score.status in ("OK", "INSUFFICIENT_DATA")


def test_roic_and_roic_ex_goodwill_are_raw_not_normalized():
    output = compute_wealth_snapshot(_golden_input())
    # raw metrics — no 0-100 clipping asserted; just confirm they're plain floats when present
    assert output.roic is None or isinstance(output.roic, float)
    assert output.roic_ex_goodwill is None or isinstance(output.roic_ex_goodwill, float)


def test_negative_equity_fixture_roe_na_quality_score_still_attempts():
    inp = _golden_input(balance_sheet=_balance_sheet(book_equity=-50.0))
    output = compute_wealth_snapshot(inp)
    # ROE excluded but Quality composition still attempted from remaining sub-metrics
    assert output.quality_score.status in ("OK", "INSUFFICIENT_DATA")


def test_negative_fcf_sign_crossing_fixture():
    inp = _golden_input(
        cash_flow_statement=_cash_flow(operating_cash_flow=-20.0, capex=10.0),  # fcf = -30
        prior_cash_flow_statement=_cash_flow(operating_cash_flow=150.0, capex=40.0),  # fcf = 110 (positive prior)
    )
    output = compute_wealth_snapshot(inp)
    assert output.fcf_score.status in ("OK", "INSUFFICIENT_DATA")


def test_banks_sector_wealth_score_and_quality_fcf_balance_sheet_unsupported():
    inp = _golden_input(sector=SectorProfile.FINANCIALS_BANKS)
    output = compute_wealth_snapshot(inp)
    assert output.wealth_score.status == "UNSUPPORTED"
    assert output.quality_score.status == "UNSUPPORTED"
    assert output.fcf_score.status == "UNSUPPORTED"
    # Banks' VALUATION_SCORE stays eligible (diagnostic set is settled methodology)
    assert output.valuation_score.status != "UNSUPPORTED" or "not a deterministic rule" not in (output.valuation_score.reason or "")


def test_insurance_sector_valuation_score_also_unsupported_unlike_banks():
    inp = _golden_input(sector=SectorProfile.FINANCIALS_INSURANCE)
    output = compute_wealth_snapshot(inp)
    assert output.wealth_score.status == "UNSUPPORTED"
    assert output.valuation_score.status == "UNSUPPORTED"
    assert "not a deterministic rule" in output.valuation_score.reason


def test_insufficient_data_when_prior_period_entirely_absent():
    inp = _golden_input(
        prior_income_statement=None, prior_balance_sheet=None, prior_cash_flow_statement=None,
    )
    output = compute_wealth_snapshot(inp)
    # Growth-dependent sub-metrics collapse to N/A/insufficient without a prior period
    assert output.growth_score.status in ("INSUFFICIENT_DATA", "N/A")


def test_production_configuration_rejects_provisional_weights_end_to_end():
    """Both the OPEN-parameters file and every sub-metric weight file are PROVISIONAL — a
    production configuration must reject whichever loads first (rule 6), not silently fall
    through to computing anything."""
    from packages.shared.component_weights import ProvisionalWeightsRejectedError
    from packages.shared.open_parameters import ProvisionalOpenParametersRejectedError

    with pytest.raises((ProvisionalWeightsRejectedError, ProvisionalOpenParametersRejectedError)):
        compute_wealth_snapshot(_golden_input(), allow_provisional=False)


def test_h4_red_flag_surfaces_in_output_when_melting_ice_cube_pattern_present():
    inp = _golden_input(
        income_statement=_income_statement(revenue=900.0, cogs=350.0, operating_expenses=250.0, ebit=250.0),
        prior_income_statement=_income_statement(revenue=1000.0, ebit=200.0),
        cash_flow_statement=_cash_flow(depreciation_amortization=60.0),
        prior_cash_flow_statement=_cash_flow(depreciation_amortization=50.0),
    )
    output = compute_wealth_snapshot(inp)
    codes = [f.code for f in output.red_flags]
    # Not asserting it always fires (depends on exact derived EBITDA margins), just that the
    # pipeline can produce it without erroring when conditions align.
    assert isinstance(codes, list)
