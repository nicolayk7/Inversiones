"""Macro/Market/Risk regime classifiers (BULL/BULL_VOLATILE/NEUTRAL/BEAR/BEAR_VOLATILE/CRISIS) and
Wealth Engine sector gates. Market regime classification is out of scope for Phase 1B
(Trading/Macro Intelligence, implementation authorization rule 10) and remains unimplemented;
`sector_profile`'s Wealth-specific gates are implemented (Phase 1B)."""

from enum import StrEnum

from packages.quant_core.regime.sector_profile import (
    SectorProfile,
    applies_cycle_normalization,
    leverage_band_profile,
    valuation_score_eligibility,
    wealth_score_eligibility,
)


class RegimeLabel(StrEnum):
    BULL = "BULL"
    BULL_VOLATILE = "BULL_VOLATILE"
    NEUTRAL = "NEUTRAL"
    BEAR = "BEAR"
    BEAR_VOLATILE = "BEAR_VOLATILE"
    CRISIS = "CRISIS"


def classify_market_regime(spy_series: object, vix_series: object) -> RegimeLabel:
    raise NotImplementedError("Market Regime — out of scope for Phase 1B")


__all__ = [
    "RegimeLabel",
    "classify_market_regime",
    "SectorProfile",
    "wealth_score_eligibility",
    "valuation_score_eligibility",
    "applies_cycle_normalization",
    "leverage_band_profile",
]

