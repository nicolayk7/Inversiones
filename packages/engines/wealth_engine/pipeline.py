"""Wealth Engine pipeline — DATA -> CALCULATION -> NORMALIZATION -> SCORING -> DECISION SUPPORT
(methodology §2). `compute_wealth_snapshot` is the single entry point.

IMPLEMENTATION-DETAIL DECISION (undocumented elsewhere, stated here): no concrete
`FundamentalsProvider` implementation exists yet (Phase 0 — `packages/providers/fundamentals` is
an empty stub), so this pipeline takes already-fetched statement DTOs directly as input rather
than calling a live provider. This is the smallest reversible choice available — a future
provider-backed caller can fetch the DTOs and call this same function unchanged; nothing here
assumes how they were obtained. `engines/wealth_engine` still only depends on `quant_core` and
the provider Protocol *types* (for input typing), never a concrete SDK.

SIMPLIFICATION, disclosed: `IncomeStatement` has no effective-tax-rate/tax-expense field (a data
gap this MVP surfaced but did not add a raw field for). NOPAT is therefore approximated as EBIT
(pre-tax operating income), overstating true after-tax NOPAT — this makes ROIC/ROIIC read
somewhat high versus a proper after-tax figure. Documented, not silently absorbed; the fix is a
future schema addition (`effective_tax_rate` or `tax_expense`), not a Phase 1B methodology call.
"""

from datetime import date

from pydantic import BaseModel

import packages.quant_core.fundamentals as qf
from packages.engines.wealth_engine import eligibility, red_flags
from packages.engines.wealth_engine.output_contract import RedFlagOut, ScoredField, WealthEngineOutput
from packages.quant_core.regime import SectorProfile, valuation_score_eligibility
from packages.quant_core.regime import wealth_score_eligibility as sector_gate_quality
from packages.quant_core.results import MetricResult
from packages.quant_core.scoring import business_quality_composite as bqc
from packages.quant_core.scoring import compose_score, wealth_score_raw as compute_wealth_score_raw
from packages.shared.component_weights import load_component_weights
from packages.shared.open_parameters import load_open_parameters
from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement
from packages.shared.weights import load_weights


class WealthEngineInput(BaseModel):
    ticker: str
    as_of: date
    sector: SectorProfile
    income_statement: IncomeStatement
    balance_sheet: BalanceSheet
    cash_flow_statement: CashFlowStatement
    prior_income_statement: IncomeStatement | None = None
    prior_balance_sheet: BalanceSheet | None = None
    prior_cash_flow_statement: CashFlowStatement | None = None
    price: float | None = None
    # Optional trailing series — absent by default, which correctly propagates to N/A in the
    # sub-metrics that need them (margin stability, growth consistency, FCF consistency,
    # acceleration), rather than a fabricated single-period estimate.
    trailing_margins: list[float] | None = None
    trailing_yoy_growth_rates: list[float] | None = None
    trailing_fcf: list[float] | None = None
    trailing_fcf_conversion: list[float] | None = None
    trailing_4q_growth: float | None = None
    prior_4q_growth: float | None = None


def _quality_sub_metrics(inp: WealthEngineInput, params) -> dict[str, MetricResult]:
    bs, prior_bs = inp.balance_sheet, inp.prior_balance_sheet
    inc = inp.income_statement

    invested_capital = None
    invested_capital_ex_goodwill = None
    if bs.total_debt is not None and bs.book_equity is not None and bs.cash_and_equivalents is not None:
        invested_capital = bs.total_debt + bs.book_equity - bs.cash_and_equivalents
        if bs.goodwill is not None:
            invested_capital_ex_goodwill = invested_capital - bs.goodwill

    nopat_approx = inc.ebit  # see module docstring — pre-tax approximation, disclosed

    roic_result = qf.roic(nopat_approx, invested_capital)
    hurdle = params["cost_of_capital_hurdle_pct"]
    hurdle_mid = sum(hurdle) / len(hurdle) if isinstance(hurdle, list) else hurdle

    delta_nopat = None
    delta_invested_capital = None
    if prior_bs is not None and inp.prior_income_statement is not None:
        prior_ic = None
        if prior_bs.total_debt is not None and prior_bs.book_equity is not None and prior_bs.cash_and_equivalents is not None:
            prior_ic = prior_bs.total_debt + prior_bs.book_equity - prior_bs.cash_and_equivalents
        if nopat_approx is not None and inp.prior_income_statement.ebit is not None:
            delta_nopat = nopat_approx - inp.prior_income_statement.ebit
        if invested_capital is not None and prior_ic is not None:
            delta_invested_capital = invested_capital - prior_ic

    gross_profit = None
    if inc.revenue is not None and inc.cogs is not None:
        gross_profit = inc.revenue - inc.cogs
    operating_income = inc.ebit  # operating income approximated by EBIT

    ebitda = qf.gaap_ebitda(inc.revenue, inc.cogs, inc.operating_expenses, inp.cash_flow_statement.depreciation_amortization)
    fcf_result = qf.compute_fcf(inp.cash_flow_statement.operating_cash_flow, inp.cash_flow_statement.capex)

    return {
        "roic_spread": qf.roic_spread(roic_result, hurdle_mid),
        "roe": qf.roe_dupont(
            inc.net_income, inc.revenue, bs.total_assets, bs.book_equity,
            roe_soft_floor_pct_of_assets=params["roe_soft_floor_pct_of_assets"],
        ),
        "roa": qf.roa(inc.net_income, bs.total_assets),
        "gross_margin": qf.gross_margin(gross_profit, inc.revenue),
        "operating_margin": qf.operating_margin(operating_income, inc.revenue),
        "fcf_margin": qf.fcf_margin(fcf_result.value if fcf_result.is_ok else None, inc.revenue),
        "ebitda_margin": qf.ebitda_margin(ebitda.value if ebitda.is_ok else None, inc.revenue),
        "margin_stability": qf.margin_stability(inp.trailing_margins),
        "roiic": qf.roiic(delta_nopat, delta_invested_capital),
    }, roic_result, invested_capital, invested_capital_ex_goodwill, nopat_approx


def _growth_sub_metrics(inp: WealthEngineInput) -> dict[str, MetricResult]:
    inc, prior_inc = inp.income_statement, inp.prior_income_statement
    cf, prior_cf = inp.cash_flow_statement, inp.prior_cash_flow_statement

    prior_revenue = prior_inc.revenue if prior_inc else None
    prior_net_income = prior_inc.net_income if prior_inc else None

    fcf_result = qf.compute_fcf(cf.operating_cash_flow, cf.capex)
    prior_fcf_result = qf.compute_fcf(prior_cf.operating_cash_flow, prior_cf.capex) if prior_cf else MetricResult.na("no prior period")

    ebitda_result = qf.gaap_ebitda(inc.revenue, inc.cogs, inc.operating_expenses, cf.depreciation_amortization)
    prior_ebitda_result = (
        qf.gaap_ebitda(prior_inc.revenue, prior_inc.cogs, prior_inc.operating_expenses, prior_cf.depreciation_amortization)
        if prior_inc and prior_cf
        else MetricResult.na("no prior period")
    )

    eps_result = qf.gaap_eps(inc.net_income, inc.diluted_shares_outstanding)
    prior_eps_result = (
        qf.gaap_eps(prior_inc.net_income, prior_inc.diluted_shares_outstanding) if prior_inc else MetricResult.na("no prior period")
    )

    return {
        "revenue_growth": qf.yoy_growth(inc.revenue, prior_revenue, name="Revenue growth"),
        "eps_growth": qf.yoy_growth(
            eps_result.value if eps_result.is_ok else None,
            prior_eps_result.value if prior_eps_result.is_ok else None,
            name="EPS growth",
        ),
        "fcf_growth": qf.yoy_growth(
            fcf_result.value if fcf_result.is_ok else None,
            prior_fcf_result.value if prior_fcf_result.is_ok else None,
            name="FCF growth",
        ),
        "ebitda_growth": qf.yoy_growth(
            ebitda_result.value if ebitda_result.is_ok else None,
            prior_ebitda_result.value if prior_ebitda_result.is_ok else None,
            name="EBITDA growth",
        ),
        "forward_growth": MetricResult.na("Forward Growth — AnalystEstimate not wired into this MVP pipeline"),
        "growth_consistency": qf.growth_consistency(inp.trailing_yoy_growth_rates),
        "growth_acceleration": qf.growth_acceleration(inp.trailing_4q_growth, inp.prior_4q_growth),
    }, qf.yoy_growth(inc.net_income, prior_net_income, name="Net Income growth")


def _fcf_sub_metrics(inp: WealthEngineInput) -> tuple[dict[str, MetricResult], MetricResult]:
    inc = inp.income_statement
    cf, prior_cf = inp.cash_flow_statement, inp.prior_cash_flow_statement

    fcf_result = qf.compute_fcf(cf.operating_cash_flow, cf.capex)
    prior_fcf_result = qf.compute_fcf(prior_cf.operating_cash_flow, prior_cf.capex) if prior_cf else MetricResult.na("no prior period")

    current_margin = qf.fcf_margin(fcf_result.value if fcf_result.is_ok else None, inc.revenue)
    prior_margin = (
        qf.fcf_margin(prior_fcf_result.value if prior_fcf_result.is_ok else None, inp.prior_income_statement.revenue)
        if inp.prior_income_statement
        else MetricResult.na("no prior period")
    )

    growth_or_trajectory_name, growth_or_trajectory_result = qf.fcf_growth_or_trajectory(
        prior_fcf_result.value if prior_fcf_result.is_ok else None,
        fcf_result.value if fcf_result.is_ok else None,
        prior_margin.value if prior_margin.is_ok else None,
        current_margin.value if current_margin.is_ok else None,
    )

    sub_metrics = {
        "fcf_margin": current_margin,
        "fcf_growth_or_trajectory": growth_or_trajectory_result,
        "fcf_conversion": qf.fcf_conversion(fcf_result.value if fcf_result.is_ok else None, inc.net_income),
        "fcf_consistency": qf.fcf_consistency(inp.trailing_fcf),
    }
    return sub_metrics, fcf_result


def _valuation_sub_metrics(inp: WealthEngineInput, roic_ex_goodwill_result: MetricResult) -> dict[str, MetricResult]:
    """historical_percentile and sector_percentile correctly resolve N/A in this MVP — neither a
    historical window (methodology §11) nor a peer universe (§23's Universe v1 is itself still
    undefined) exists. metric_profile is the one sub-metric this MVP can populate, sector-gated
    per methodology §10's profile table."""
    eligibility_gate = valuation_score_eligibility(inp.sector)
    if not eligibility_gate.is_ok:
        return {
            "historical_percentile": eligibility_gate,
            "sector_percentile": eligibility_gate,
            "metric_profile": eligibility_gate,
        }

    inc = inp.income_statement
    bs = inp.balance_sheet
    if inp.sector in (SectorProfile.FINANCIALS_BANKS,):
        metric_profile = qf.price_to_book(inp.price, bs.book_equity, inc.diluted_shares_outstanding)
    else:
        eps_result = qf.gaap_eps(inc.net_income, inc.diluted_shares_outstanding)
        metric_profile = qf.pe_ratio(inp.price, eps_result)

    return {
        "historical_percentile": MetricResult.na("Historical Valuation window not available in this MVP (methodology §11)"),
        "sector_percentile": MetricResult.na("Universe v1 peer set not defined (methodology §23 is still OPEN)"),
        "metric_profile": metric_profile,
    }


def compute_wealth_snapshot(inp: WealthEngineInput, *, allow_provisional: bool | None = None) -> WealthEngineOutput:
    top_weights = load_weights("v1.0")  # frozen, unmodified
    params = load_open_parameters("v1.0", allow_provisional=allow_provisional).values
    quality_weights = load_component_weights("quality", "v1.0", allow_provisional=allow_provisional)
    growth_weights = load_component_weights("growth", "v1.0", allow_provisional=allow_provisional)
    fcf_weights = load_component_weights("fcf", "v1.0", allow_provisional=allow_provisional)
    valuation_weights = load_component_weights("valuation", "v1.0", allow_provisional=allow_provisional)

    min_coverage = params["min_group_coverage_pct"] / 100

    quality_subs, roic_result, invested_capital, invested_capital_ex_goodwill, nopat_approx = _quality_sub_metrics(inp, params)
    growth_subs, net_income_growth = _growth_sub_metrics(inp)
    fcf_subs, fcf_result = _fcf_sub_metrics(inp)
    roic_ex_goodwill_result = qf.roic_ex_goodwill(nopat_approx, invested_capital_ex_goodwill)
    valuation_subs = _valuation_sub_metrics(inp, roic_ex_goodwill_result)

    quality_gate = sector_gate_quality(inp.sector)
    fcf_gate = sector_gate_quality(inp.sector)

    if quality_gate.is_ok:
        quality_score = compose_score(quality_subs, quality_weights.weights, min_coverage_pct=min_coverage)
    else:
        quality_score = quality_gate

    growth_score = compose_score(growth_subs, growth_weights.weights, min_coverage_pct=min_coverage)

    if fcf_gate.is_ok:
        fcf_score_pre_flags = compose_score(fcf_subs, fcf_weights.weights, min_coverage_pct=min_coverage)
    else:
        fcf_score_pre_flags = fcf_gate

    valuation_gate = valuation_score_eligibility(inp.sector)
    if valuation_gate.is_ok:
        valuation_score = compose_score(valuation_subs, valuation_weights.weights, min_coverage_pct=min_coverage)
    else:
        # Propagate the sector-gate UNSUPPORTED directly — running already-blocked sub-metrics
        # through compose_score would report INSUFFICIENT_DATA (0% coverage) instead, losing the
        # actual reason (Insurance's undesigned valuation set, not merely "not enough data").
        valuation_score = valuation_gate

    # Red flags — FCF-specific detectors given the inputs this MVP has; deductions applied per
    # methodology §14's explicit FCF_SCORE formula.
    flags: list = []
    ni_growth_val = net_income_growth.value if net_income_growth.is_ok else None
    fcf_growth_sub = fcf_subs["fcf_growth_or_trajectory"]
    flag = red_flags.earnings_fcf_divergence(ni_growth_val, fcf_growth_sub.value if fcf_growth_sub.is_ok else None)
    if flag:
        flags.append(flag)
    eps_growth_val = growth_subs["eps_growth"].value if growth_subs["eps_growth"].is_ok else None
    flag = red_flags.dilution_outpacing_buyback(eps_growth_val, ni_growth_val)
    if flag:
        flags.append(flag)
    flag = red_flags.margin_deterioration_trend(inp.trailing_margins)
    if flag:
        flags.append(flag)
    flag = red_flags.declining_cash_conversion(inp.trailing_fcf_conversion)
    if flag:
        flags.append(flag)
    revenue_growth_val = growth_subs["revenue_growth"].value if growth_subs["revenue_growth"].is_ok else None
    ebitda_growth_val = growth_subs["ebitda_growth"].value if growth_subs["ebitda_growth"].is_ok else None
    current_ebitda_margin = quality_subs["ebitda_margin"].value if quality_subs["ebitda_margin"].is_ok else None
    prior_ebitda_margin = None
    if inp.prior_income_statement and inp.prior_cash_flow_statement:
        prior_ebitda = qf.gaap_ebitda(
            inp.prior_income_statement.revenue, inp.prior_income_statement.cogs,
            inp.prior_income_statement.operating_expenses, inp.prior_cash_flow_statement.depreciation_amortization,
        )
        if prior_ebitda.is_ok and inp.prior_income_statement.revenue:
            prior_ebitda_margin = prior_ebitda.value / inp.prior_income_statement.revenue
    flag = red_flags.revenue_decline_masked_by_margin_expansion(
        revenue_growth_val, current_ebitda_margin, prior_ebitda_margin, ebitda_growth_val,
        threshold_pp=params["h4_margin_expansion_threshold_pp"],
    )
    if flag:
        flags.append(flag)

    fcf_deduction = red_flags.applicable_fcf_red_flag_deductions(flags)
    if fcf_score_pre_flags.is_ok:
        fcf_score = MetricResult.ok(fcf_score_pre_flags.value - fcf_deduction)
    else:
        fcf_score = fcf_score_pre_flags

    # MOAT_SCORE — always UNSUPPORTED, no aggregation code exists (Phase 1B design decision 8).
    moat_score = MetricResult.unsupported(
        "MOAT_SCORE aggregation fully deferred pending an explicit evidence/provenance design "
        "for Moat — no aggregation code (weighted or unweighted) exists in Phase 1B"
    )

    component_scores = {
        "quality": quality_score, "growth": growth_score, "fcf": fcf_score,
        "moat": moat_score, "valuation": valuation_score,
    }
    wealth_raw = compute_wealth_score_raw(component_scores, top_weights.wealth)
    business_quality = bqc(component_scores, top_weights.wealth)
    wealth = eligibility.wealth_score(inp.sector)

    capital_allocation_score = MetricResult.unsupported(
        "CAPITAL_ALLOCATION_SCORE composition not wired into this MVP pipeline pass "
        "(buyback-dependent sub-metrics are UNSUPPORTED regardless — see implementation spec §2.3)"
    )
    balance_sheet_score = MetricResult.na("BALANCE_SHEET_SCORE banding not wired into this MVP pipeline pass")
    data_confidence = MetricResult.na("data_confidence roll-up not wired into this MVP pipeline pass")
    data_quality = MetricResult.na("DATA_QUALITY_SCORE not wired into this MVP pipeline pass")

    return WealthEngineOutput(
        ticker=inp.ticker,
        as_of=inp.as_of.isoformat(),
        sector=inp.sector.value,
        wealth_score=ScoredField.from_metric_result(wealth),
        wealth_score_raw=ScoredField.from_metric_result(wealth_raw),
        quality_score=ScoredField.from_metric_result(quality_score),
        growth_score=ScoredField.from_metric_result(growth_score),
        fcf_score=ScoredField.from_metric_result(fcf_score),
        valuation_score=ScoredField.from_metric_result(valuation_score),
        moat_score=ScoredField.from_metric_result(moat_score),
        capital_allocation_score=ScoredField.from_metric_result(capital_allocation_score),
        balance_sheet_score=ScoredField.from_metric_result(balance_sheet_score),
        business_quality_composite=ScoredField.from_metric_result(business_quality),
        roic=roic_result.value,
        roic_ex_goodwill=roic_ex_goodwill_result.value,
        data_confidence=ScoredField.from_metric_result(data_confidence),
        data_quality=ScoredField.from_metric_result(data_quality),
        red_flags=[
            RedFlagOut(
                code=f.code, description=f.description, severity=f.severity.value,
                evidence=f.evidence, affected_scores=f.affected_scores, mechanism=f.mechanism.value,
            )
            for f in flags
        ],
        weights_version=top_weights.version,
    )
