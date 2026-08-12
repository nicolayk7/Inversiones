"""Sector gates (methodology C4, principle 4/5) — Banks/Insurance vs. generic industrial, and
the Banks-vs-Insurance split for VALUATION_SCORE specifically (Phase 1B decision)."""

from packages.engines.wealth_engine.eligibility import wealth_score as eligibility_wealth_score
from packages.quant_core.regime.sector_profile import SectorProfile, valuation_score_eligibility, wealth_score_eligibility


def test_generic_industrial_is_eligible_for_quality_fcf_balance_sheet():
    assert wealth_score_eligibility(SectorProfile.GENERIC_INDUSTRIAL).is_ok


def test_banks_unsupported_for_quality_fcf_balance_sheet():
    result = wealth_score_eligibility(SectorProfile.FINANCIALS_BANKS)
    assert result.status.value == "UNSUPPORTED"


def test_insurance_unsupported_for_quality_fcf_balance_sheet():
    result = wealth_score_eligibility(SectorProfile.FINANCIALS_INSURANCE)
    assert result.status.value == "UNSUPPORTED"


def test_banks_are_eligible_for_valuation_score_insurance_is_not():
    """The exact distinction this round's design decision introduced: Banks and Insurance are
    NOT the same case for VALUATION_SCORE."""
    assert valuation_score_eligibility(SectorProfile.FINANCIALS_BANKS).is_ok
    insurance_result = valuation_score_eligibility(SectorProfile.FINANCIALS_INSURANCE)
    assert insurance_result.status.value == "UNSUPPORTED"
    assert "not a deterministic rule" in insurance_result.reason


def test_wealth_score_is_always_unsupported_regardless_of_sector():
    """BalanceSheetMultiplier blocker applies unconditionally — even a generic-industrial
    ticker whose WEALTH_SCORE_RAW might otherwise resolve still gets wealth_score=UNSUPPORTED."""
    generic = eligibility_wealth_score(SectorProfile.GENERIC_INDUSTRIAL)
    assert generic.status.value == "UNSUPPORTED"
    assert "BalanceSheetMultiplier" in generic.reason


def test_wealth_score_reports_sector_gate_reason_for_banks_not_multiplier_reason():
    result = eligibility_wealth_score(SectorProfile.FINANCIALS_BANKS)
    assert result.status.value == "UNSUPPORTED"
    assert "C4" in result.reason
