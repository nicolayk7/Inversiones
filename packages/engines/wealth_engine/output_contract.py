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
    as_of: str  # data vintage — the period_end of the statements actually used, NOT the caller's
    # requested cutoff (see requested_as_of below). Kept as-is for backwards compatibility;
    # responsible-output audit (2026-08) flagged this name as ambiguous — not renamed here.
    requested_as_of: str | None = None  # PIT cutoff the caller asked for (available_at <= this).
    # None only for WealthEngineInput constructed directly (e.g. test fixtures) without going
    # through build_wealth_engine_input_from_storage, which always sets it.
    sector: str

    # Distinct from weights_version below (frozen TOP-LEVEL weights, config/weights/v1.0.yaml,
    # genuinely approved) — this describes the SUB-METRIC ("component") weights within each group
    # (config/weights/wealth_components/*.yaml), which are all currently status: PROVISIONAL
    # (dev/test fixtures, not approved methodology values — see packages/shared/component_weights.py).
    # "PROVISIONAL" here means every quality_score/growth_score/fcf_score/valuation_score value in
    # this response was computed using an unapproved sub-metric weighting; "APPROVED" would mean
    # all four groups' weight files carry status: APPROVED. Worst-status-wins across the four
    # groups (any PROVISIONAL group makes this PROVISIONAL) — never fabricated as APPROVED.
    component_weights_status: str

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
