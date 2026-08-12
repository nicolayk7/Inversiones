"""WEALTH_SCORE eligibility (methodology C4, principle 4; BalanceSheetMultiplier decision).
Two independent gates apply, checked in order:

1. Sector gate (Banks/Insurance -> UNSUPPORTED, C4) — delegated to
   `packages.quant_core.regime.sector_profile.wealth_score_eligibility`, the single centralized
   enforcement point (do not re-implement this check inline elsewhere).
2. BalanceSheetMultiplier gate — BLOCKED (Category C), not defaulted. `wealth_score` is `null`/
   `UNSUPPORTED` in Phase 1B UNCONDITIONALLY, even for a non-Financials ticker whose
   WEALTH_SCORE_RAW would otherwise resolve OK. The unadjusted composite is exposed separately
   as `WEALTH_SCORE_RAW` (methodology's own name for it, §14) — never under the name
   `wealth_score`. No multiplier, curve, or penalty value is invented anywhere in this module.
"""

from packages.quant_core.regime.sector_profile import SectorProfile
from packages.quant_core.regime.sector_profile import wealth_score_eligibility as _sector_gate
from packages.quant_core.results import MetricResult

_BALANCE_SHEET_MULTIPLIER_REASON = (
    "BalanceSheetMultiplier not yet approved (Category C, mechanism and curve both BLOCKED) — "
    "wealth_score is null in Phase 1B unconditionally. See wealth_score_raw for the unadjusted "
    "composite (methodology's own WEALTH_SCORE_RAW name) and balance_sheet_score for the "
    "independently-visible leverage risk signal."
)


def wealth_score(sector: SectorProfile) -> MetricResult:
    """Always UNSUPPORTED in Phase 1B — see module docstring. `sector` is still consulted so the
    *reason* reported is the more specific one when both gates would otherwise apply, and so a
    future removal of the BalanceSheetMultiplier block doesn't silently skip the sector gate."""
    sector_gate = _sector_gate(sector)
    if not sector_gate.is_ok:
        return sector_gate  # Banks/Insurance — C4, more specific than the multiplier block
    return MetricResult.unsupported(_BALANCE_SHEET_MULTIPLIER_REASON)
