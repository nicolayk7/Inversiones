"""Sector classification and the Wealth Engine sector gates (methodology §4, C4). Pure functions,
no I/O, no LLM. This is the single, centralized enforcement point for principle 4 (Banks/Insurance
-> WEALTH_SCORE = N/A) — every caller must route through these two gate functions rather than
re-implementing the sector check inline, so the rule can't be silently bypassed at a new call
site."""

from enum import StrEnum

from packages.quant_core.results import MetricResult


class SectorProfile(StrEnum):
    GENERIC_INDUSTRIAL = "generic_industrial"
    CYCLICALS_ENERGY = "cyclicals_energy"
    UTILITIES = "utilities"
    FINANCIALS_BANKS = "financials_banks"
    FINANCIALS_INSURANCE = "financials_insurance"
    CONSUMER_STAPLES_RETAIL = "consumer_staples_retail"
    REIT = "reit"  # likely excluded from Universe v1 anyway, methodology §23


_FINANCIALS = (SectorProfile.FINANCIALS_BANKS, SectorProfile.FINANCIALS_INSURANCE)


def wealth_score_eligibility(sector: SectorProfile) -> MetricResult:
    """QUALITY_SCORE, FCF_SCORE, BALANCE_SHEET_SCORE, WEALTH_SCORE, business_quality_composite,
    and valuation_quadrant are all UNSUPPORTED for Banks and Insurance (C4) — no formula exists
    for either sector, none is invented here. This gate is unconditional: it does not depend on
    whether VALUATION_SCORE itself resolves OK (see `valuation_score_eligibility` below, which is
    a genuinely separate gate)."""
    if sector in _FINANCIALS:
        return MetricResult.unsupported(
            "C4 sector-specific Quality/FCF/Balance-Sheet methodology not yet approved "
            f"(sector={sector.value})"
        )
    return MetricResult.ok(1.0)  # eligible; may still be blocked upstream (e.g. Moat deferral)


def valuation_score_eligibility(sector: SectorProfile) -> MetricResult:
    """Separate gate from wealth_score_eligibility — Banks and Insurance are NOT the same case
    for VALUATION_SCORE specifically (Phase 1B design decision, Insurance-valuation round).
    Banks' diagnostic set (P/B, P/TBV, ROE-justified P/B) is settled methodology and computable.
    Insurance's ("P/B, P/TBV where meaningful — not otherwise designed") is not a deterministic
    rule an implementer can code against, so it is UNSUPPORTED pending its own explicit,
    dedicated sector-specific approval."""
    if sector == SectorProfile.FINANCIALS_INSURANCE:
        return MetricResult.unsupported(
            "Insurance valuation set ('P/B, P/TBV where meaningful') is not a deterministic "
            "rule — requires explicit sector-specific approval before implementation"
        )
    return MetricResult.ok(1.0)


def applies_cycle_normalization(sector: SectorProfile) -> bool:
    return sector == SectorProfile.CYCLICALS_ENERGY


def leverage_band_profile(sector: SectorProfile) -> str:
    """Which OPEN leverage-band config key applies (methodology §6, H8)."""
    return "leverage_bands_utilities" if sector == SectorProfile.UTILITIES else "leverage_bands_generic"
