"""Wealth Engine — "what should I own?" (methodology). Phase 1B MVP: deterministic
DATA -> CALCULATION -> NORMALIZATION -> SCORING -> DECISION SUPPORT pipeline, no agents
(rule 10), no BalanceSheetMultiplier (blocked), no Moat aggregation (deferred)."""

from packages.engines.wealth_engine.output_contract import RedFlagOut, ScoredField, WealthEngineOutput
from packages.engines.wealth_engine.pipeline import WealthEngineInput, compute_wealth_snapshot

__all__ = [
    "WealthEngineInput",
    "WealthEngineOutput",
    "ScoredField",
    "RedFlagOut",
    "compute_wealth_snapshot",
]
