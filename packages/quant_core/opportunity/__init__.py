"""Opportunity ranking formula: combines wealth/trading/options scores + regime multipliers. Pure
code, no LLM — Risk is deliberately not a weighted input, it is a separate gate applied after
ranking (architecture v1.0, rule 8, rule 18). Implemented starting Phase 1."""


def rank_opportunities(
    candidates: list[dict[str, float]], weights_version: str = "v1.0"
) -> list[dict[str, float]]:
    raise NotImplementedError("Opportunity Engine — Phase 1")

