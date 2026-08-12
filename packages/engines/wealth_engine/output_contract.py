"""Nested `{value, status, reason}` output representation (Phase 1B implementation authorization,
decision 4 / implementation spec §11.1). This is ONE reasonable Pydantic serialization of the
approved *semantic* shape — field ordering, whether every field is wrapped, and the exact JSON
key layout are implementation details, not re-litigated methodology (spec §16 Q4 left the exact
API implementation open; this is that implementation, not a new design decision)."""

from pydantic import BaseModel

from packages.quant_core.results import MetricResult


class ScoredField(BaseModel):
    value: float | None
    status: str
    reason: str | None = None

    @classmethod
    def from_metric_result(cls, result: MetricResult) -> "ScoredField":
        return cls(value=result.value, status=result.status.value, reason=result.reason)


class RedFlagOut(BaseModel):
    code: str
    description: str
    severity: str
    evidence: list[str]
    affected_scores: list[str]
    mechanism: str


class WealthEngineOutput(BaseModel):
    """Reproduces the Phase 1A-approved output contract (methodology §24), restricted to the
    fields Phase 1B actually computes (implementation spec §11's Phase-1B-computable column) —
    agent-derived narrative fields (`thesis`, `why_it_matters`, `key_risks`, `catalysts`,
    `invalidation_conditions`) are omitted entirely rather than stubbed, since no agent runs in
    Phase 1B (rule 10)."""

    ticker: str
    as_of: str
    sector: str

    wealth_score: ScoredField  # always UNSUPPORTED in Phase 1B — see eligibility.py
    wealth_score_raw: ScoredField  # methodology's own name (§14); NOT the same field as wealth_score

    quality_score: ScoredField
    growth_score: ScoredField
    fcf_score: ScoredField
    valuation_score: ScoredField
    moat_score: ScoredField  # always UNSUPPORTED — deferred in full, no aggregation code exists
    capital_allocation_score: ScoredField
    balance_sheet_score: ScoredField
    business_quality_composite: ScoredField

    roic: float | None  # RAW metric, never normalized 0-100, may be negative — H5
    roic_ex_goodwill: float | None  # RAW, diagnostic-only — H5

    data_confidence: ScoredField
    data_quality: ScoredField

    red_flags: list[RedFlagOut]
    weights_version: str
