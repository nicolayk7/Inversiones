"""Wealth/Quality/Growth/FCF/Valuation composite scores, computed from config/weights (frozen,
versioned — never LLM-generated, architecture v1.0 rule 9) and the sub-metric weight
architecture approved in the Phase 1B design closure (packages/shared/component_weights.py).

Trading/Options composite scores are out of scope for Phase 1B (implementation authorization
rule 10 / non-goal) and remain unimplemented stubs, unchanged from Phase 0."""

from packages.quant_core.scoring.composition import (
    business_quality_composite,
    compose_score,
    group_coverage,
    wealth_score_raw,
)
from packages.quant_core.scoring.normalization import clip, min_max_normalize, percentile_rank, winsorize


def trading_score(component_scores: dict[str, float], weights_version: str = "v1.0") -> float:
    raise NotImplementedError("Trading Engine — out of scope for Phase 1B")


def options_score(component_scores: dict[str, float], weights_version: str = "v1.0") -> float:
    raise NotImplementedError("Options Intelligence — out of scope for Phase 1B")


__all__ = [
    "compose_score",
    "group_coverage",
    "wealth_score_raw",
    "business_quality_composite",
    "clip",
    "winsorize",
    "min_max_normalize",
    "percentile_rank",
    "trading_score",
    "options_score",
]
