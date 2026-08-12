"""Accounting Quality / Red Flags registry (methodology §21). 16 codes, each a deterministic
detector — no LLM anywhere in this file (principle 9). Each detector is a pure function taking
exactly the raw values it needs and returning `RedFlag | None`.

Of the 16, 9 have a deterministic, data-available rule implementable in this MVP; 7 cannot fire
in Phase 1B for documented, non-methodology reasons (a missing OPEN threshold the methodology
never assigned a number to, or a raw input this MVP's schema/providers don't yet carry) — they
stay registered (nothing here changes an existing red-flag *definition*, per rule 3) but their
detector always returns `None`, with the reason stated in its docstring rather than silently
omitted."""

from enum import StrEnum

from pydantic import BaseModel

from packages.quant_core.results import MetricResult, MetricStatus

ALL_RED_FLAG_CODES = (
    "EARNINGS_FCF_DIVERGENCE",
    "RECEIVABLES_GROWTH_OUTPACING_REVENUE",
    "INVENTORY_GROWTH_OUTPACING_REVENUE",
    "MARGIN_DETERIORATION_TREND",
    "AGGRESSIVE_CAPITALIZATION",
    "HIGH_SBC_RELATIVE_TO_FCF",
    "DILUTION_OUTPACING_BUYBACK",
    "ACQUISITION_DRIVEN_GROWTH",
    "DEBT_FUNDED_BUYBACKS",
    "UNUSUAL_TAX_EFFECTS",
    "ONE_TIME_GAINS_INFLATING_EARNINGS",
    "DECLINING_CASH_CONVERSION",
    "WORKING_CAPITAL_DRIVEN_FCF",
    "RESTATEMENT_DETECTED",
    "GUIDANCE_MISS_PATTERN",
    "REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION",
)


class RedFlagSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class RedFlagMechanism(StrEnum):
    INFORMATIONAL = "informational"
    CAPPED_DEDUCTION = "capped_deduction"


class RedFlag(BaseModel):
    code: str
    description: str
    severity: RedFlagSeverity
    evidence: list[str]
    affected_scores: list[str] = []
    # Defaults to informational — a new detector can't silently start deducting from a score
    # (methodology §21: only a documented, capped subset does).
    mechanism: RedFlagMechanism = RedFlagMechanism.INFORMATIONAL
    deduction_amount: float | None = None


# ---------------------------------------------------------------------------
# Implementable detectors (9) — deterministic rule available with this MVP's inputs.
# ---------------------------------------------------------------------------


def earnings_fcf_divergence(net_income_growth: float | None, fcf_growth: float | None) -> RedFlag | None:
    if net_income_growth is None or fcf_growth is None:
        return None
    if net_income_growth > 0 and fcf_growth <= 0:
        return RedFlag(
            code="EARNINGS_FCF_DIVERGENCE",
            description="Net Income growing while FCF does not",
            severity=RedFlagSeverity.MEDIUM,
            evidence=[f"net_income_growth={net_income_growth:.2%}", f"fcf_growth={fcf_growth:.2%}"],
            affected_scores=["FCF_SCORE"],
        )
    return None


def receivables_growth_outpacing_revenue(receivables_growth: float | None, revenue_growth: float | None) -> RedFlag | None:
    if receivables_growth is None or revenue_growth is None:
        return None
    if receivables_growth > revenue_growth:
        return RedFlag(
            code="RECEIVABLES_GROWTH_OUTPACING_REVENUE",
            description="Receivables growing faster than revenue",
            severity=RedFlagSeverity.LOW,
            evidence=[f"receivables_growth={receivables_growth:.2%}", f"revenue_growth={revenue_growth:.2%}"],
            affected_scores=["QUALITY_SCORE"],
        )
    return None


def inventory_growth_outpacing_revenue(inventory_growth: float | None, revenue_growth: float | None) -> RedFlag | None:
    if inventory_growth is None or revenue_growth is None:
        return None
    if inventory_growth > revenue_growth:
        return RedFlag(
            code="INVENTORY_GROWTH_OUTPACING_REVENUE",
            description="Inventory growing faster than revenue",
            severity=RedFlagSeverity.LOW,
            evidence=[f"inventory_growth={inventory_growth:.2%}", f"revenue_growth={revenue_growth:.2%}"],
            affected_scores=["QUALITY_SCORE"],
        )
    return None


def margin_deterioration_trend(trailing_margins: list[float] | None) -> RedFlag | None:
    """Fires on any strictly-declining trailing margin sequence — a directional (not
    magnitude-thresholded) rule, since the methodology names the concept without a number."""
    if not trailing_margins or len(trailing_margins) < 3:
        return None
    if all(trailing_margins[i] > trailing_margins[i + 1] for i in range(len(trailing_margins) - 1)):
        return RedFlag(
            code="MARGIN_DETERIORATION_TREND",
            description="Margins declining across consecutive periods",
            severity=RedFlagSeverity.MEDIUM,
            evidence=[f"trailing_margins={trailing_margins}"],
            affected_scores=["QUALITY_SCORE"],
        )
    return None


def dilution_outpacing_buyback(eps_growth: float | None, net_income_growth: float | None) -> RedFlag | None:
    """Inverse of the §3 EPS-vs-NI-growth check — same "any positive gap" rule as
    `growth.eps_growth_quality_adjustment` (no invented magnitude threshold, see that
    function's docstring)."""
    if eps_growth is None or net_income_growth is None:
        return None
    if eps_growth > net_income_growth:
        return RedFlag(
            code="DILUTION_OUTPACING_BUYBACK",
            description="EPS growth outpaces Net Income growth — possibly buyback-driven",
            severity=RedFlagSeverity.LOW,
            evidence=[f"eps_growth={eps_growth:.2%}", f"net_income_growth={net_income_growth:.2%}"],
            affected_scores=["GROWTH_SCORE"],
        )
    return None


def declining_cash_conversion(trailing_fcf_conversion: list[float] | None) -> RedFlag | None:
    if not trailing_fcf_conversion or len(trailing_fcf_conversion) < 3:
        return None
    if all(trailing_fcf_conversion[i] > trailing_fcf_conversion[i + 1] for i in range(len(trailing_fcf_conversion) - 1)):
        return RedFlag(
            code="DECLINING_CASH_CONVERSION",
            description="FCF/Net Income ratio falling over consecutive periods",
            severity=RedFlagSeverity.MEDIUM,
            evidence=[f"trailing_fcf_conversion={trailing_fcf_conversion}"],
            affected_scores=["FCF_SCORE"],
        )
    return None


def working_capital_driven_fcf(
    delta_nwc: float | None, ocf_growth_amount: float | None, *, threshold_pct: float
) -> RedFlag | None:
    """threshold_pct is the OPEN `working_capital_fcf_flag_threshold_pct` (provisional, 30) —
    caller-supplied, never hardcoded here."""
    if delta_nwc is None or ocf_growth_amount is None or ocf_growth_amount == 0:
        return None
    share = abs(delta_nwc) / abs(ocf_growth_amount)
    if share > threshold_pct / 100:
        return RedFlag(
            code="WORKING_CAPITAL_DRIVEN_FCF",
            description="Working-capital changes drive a disproportionate share of OCF growth",
            severity=RedFlagSeverity.LOW,
            evidence=[f"delta_nwc/ocf_growth={share:.1%}", f"threshold={threshold_pct}%"],
            affected_scores=["FCF_SCORE"],
        )
    return None


def restatement_detected(
    same_period_records: list[tuple[float, object]] | None,
) -> RedFlag | None:
    """Structural detection (methodology §16/§21): the same `(instrument_id, period_end,
    source)` re-ingested with a different value and a later `available_at`. Caller supplies
    `[(value, available_at), ...]` for one (ticker, period_end, source) key, already grouped."""
    if not same_period_records or len(same_period_records) < 2:
        return None
    values = {v for v, _ in same_period_records}
    if len(values) > 1:
        return RedFlag(
            code="RESTATEMENT_DETECTED",
            description="Same period_end/source re-ingested with a different value at a later available_at",
            severity=RedFlagSeverity.MEDIUM,
            evidence=[f"distinct_values={sorted(values)}"],
            affected_scores=["DATA_QUALITY_SCORE"],
        )
    return None


def revenue_decline_masked_by_margin_expansion(
    revenue_growth_yoy: float | None,
    ebitda_margin_current: float | None,
    ebitda_margin_prior: float | None,
    ebitda_growth_yoy: float | None,
    *,
    threshold_pp: float,
) -> RedFlag | None:
    """H4 — mechanism APPROVED, threshold OPEN. `threshold_pp` is the OPEN
    `h4_margin_expansion_threshold_pp` (provisional, 2) — never hardcoded here. Informational
    only (§21): does NOT apply a deduction to QUALITY_SCORE or GROWTH_SCORE."""
    if None in (revenue_growth_yoy, ebitda_margin_current, ebitda_margin_prior, ebitda_growth_yoy):
        return None
    margin_expansion_pp = (ebitda_margin_current - ebitda_margin_prior) * 100
    if revenue_growth_yoy < 0 and margin_expansion_pp > threshold_pp and ebitda_growth_yoy > 0:
        return RedFlag(
            code="REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION",
            description='"Melting ice cube" — revenue declining, margin expansion masks it in EBITDA growth',
            severity=RedFlagSeverity.MEDIUM,
            evidence=[
                f"revenue_growth_yoy={revenue_growth_yoy:.2%}",
                f"margin_expansion_pp={margin_expansion_pp:.2f}",
                f"ebitda_growth_yoy={ebitda_growth_yoy:.2%}",
            ],
            affected_scores=["GROWTH_SCORE"],
            mechanism=RedFlagMechanism.INFORMATIONAL,  # never a score deduction (H4 decision)
        )
    return None


# ---------------------------------------------------------------------------
# Not computable in this MVP (7) — registered per rule 3 (no definition changed), always None.
# Each reason is either a missing OPEN threshold the methodology never assigned a number to, or
# a raw input this MVP's schema/providers don't carry yet.
# ---------------------------------------------------------------------------


def aggressive_capitalization(*_args, **_kwargs) -> None:
    """Not computable: the methodology names this concept (§5) without a deterministic firing
    rule or a capitalized-vs-expensed line-item split in any DTO. Not invented here."""
    return None


def high_sbc_relative_to_fcf(*_args, **_kwargs) -> None:
    """Not computable AS A FIRING DETECTOR: SBC/FCF (or SBC/Revenue) is trackable from
    IncomeStatement.stock_based_compensation, but the methodology (§5) never assigns "high" a
    number, and it isn't in the OPEN-parameter table either — inventing one would be inventing a
    methodology value. Compute and surface the ratio as a diagnostic if useful; do not fire this
    flag until a threshold is approved."""
    return None


def acquisition_driven_growth(*_args, **_kwargs) -> None:
    """Not computable: needs an M&A/acquisition CorporateAction, which does not exist in the
    current schema (action_type is split|dividend|spinoff only) — see implementation spec §2.3."""
    return None


def debt_funded_buybacks(*_args, **_kwargs) -> None:
    """Not computable: needs buyback-$ CorporateAction data, which does not exist in the current
    schema — see implementation spec §2.3. (`capital_allocation.debt_funded_buyback_flag`
    already returns UNSUPPORTED for the same reason at the metric layer.)"""
    return None


def unusual_tax_effects(*_args, **_kwargs) -> None:
    """Not computable: no tax-expense/effective-tax-rate field exists in IncomeStatement (out of
    scope for the raw-field gap identified in the design spec — genuinely a new, undiscovered
    gap, not silently worked around)."""
    return None


def one_time_gains_inflating_earnings(*_args, **_kwargs) -> None:
    """Not computable: no non-recurring/one-time-item line item exists in any statement DTO."""
    return None


def guidance_miss_pattern(*_args, **_kwargs) -> None:
    """Not computable: needs consensus-vs-actual EPS/revenue history wired specifically for
    guidance-beat-rate tracking; `AnalystEstimate` carries consensus but no realized "actual"
    field, and this isn't wired into Wealth Engine inputs in this MVP."""
    return None


REGISTRY: dict[str, object] = {
    "EARNINGS_FCF_DIVERGENCE": earnings_fcf_divergence,
    "RECEIVABLES_GROWTH_OUTPACING_REVENUE": receivables_growth_outpacing_revenue,
    "INVENTORY_GROWTH_OUTPACING_REVENUE": inventory_growth_outpacing_revenue,
    "MARGIN_DETERIORATION_TREND": margin_deterioration_trend,
    "AGGRESSIVE_CAPITALIZATION": aggressive_capitalization,
    "HIGH_SBC_RELATIVE_TO_FCF": high_sbc_relative_to_fcf,
    "DILUTION_OUTPACING_BUYBACK": dilution_outpacing_buyback,
    "ACQUISITION_DRIVEN_GROWTH": acquisition_driven_growth,
    "DEBT_FUNDED_BUYBACKS": debt_funded_buybacks,
    "UNUSUAL_TAX_EFFECTS": unusual_tax_effects,
    "ONE_TIME_GAINS_INFLATING_EARNINGS": one_time_gains_inflating_earnings,
    "DECLINING_CASH_CONVERSION": declining_cash_conversion,
    "WORKING_CAPITAL_DRIVEN_FCF": working_capital_driven_fcf,
    "RESTATEMENT_DETECTED": restatement_detected,
    "GUIDANCE_MISS_PATTERN": guidance_miss_pattern,
    "REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION": revenue_decline_masked_by_margin_expansion,
}


def applicable_fcf_red_flag_deductions(red_flags: list[RedFlag]) -> float:
    """Sums only the capped_deduction-mechanism flags whose affected_scores includes FCF_SCORE —
    the subtraction term methodology §14 specifies: FCF_SCORE = compose_score(...) -
    applicable_fcf_red_flag_deductions(...). No new deduction is invented; only flags already
    marked mechanism=CAPPED_DEDUCTION by their own detector contribute (none of the 16 above
    currently is — DEBT_FUNDED_BUYBACKS, the one capped-deduction flag in the methodology, is not
    computable in this MVP, so this sums to 0.0 until that data gap closes)."""
    return sum(
        f.deduction_amount or 0.0
        for f in red_flags
        if f.mechanism == RedFlagMechanism.CAPPED_DEDUCTION and "FCF_SCORE" in f.affected_scores
    )
