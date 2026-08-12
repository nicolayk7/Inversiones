"""Capital Allocation raw metrics (methodology §7). Pure functions, no I/O, no LLM.
`CAPITAL_ALLOCATION_SCORE` stays informational-only (H3) and is never blocked from being defined
by this module — but its buyback-dependent metrics are structurally UNSUPPORTED until the
`CorporateAction` provider gains a buyback representation (Phase 1B implementation
authorization: "isolate buyback/M&A-dependent logic behind explicit unsupported/
insufficient-data states"; design comparison not yet resolved, see
docs/wealth-engine-phase1b-implementation-spec.md §2.3)."""

from packages.quant_core.results import MetricResult

_BUYBACK_UNSUPPORTED_REASON = (
    "Buyback data unavailable — CorporateAction has no buyback representation yet "
    "(action_type is currently split|dividend|spinoff only); see implementation spec §2.3"
)


def net_buyback_yield(net_buyback_amount: float | None, beginning_market_cap: float | None) -> MetricResult:
    if net_buyback_amount is None:
        return MetricResult.unsupported(_BUYBACK_UNSUPPORTED_REASON)
    if beginning_market_cap is None or beginning_market_cap == 0:
        return MetricResult.na("Net Buyback Yield — missing or zero beginning market cap")
    return MetricResult.ok(net_buyback_amount / beginning_market_cap)


def share_count_cagr(begin_shares: float | None, end_shares: float | None, years: float) -> MetricResult:
    """Independent of the buyback-$ gap — diluted share count itself is a Fundamentals field,
    not a CorporateAction, so this stays computable even while buyback $ amounts are
    UNSUPPORTED."""
    if begin_shares is None or end_shares is None:
        return MetricResult.na("Share Count CAGR — missing begin or end share count")
    if begin_shares <= 0 or years <= 0:
        return MetricResult.na("Share Count CAGR — begin share count must be positive")
    return MetricResult.ok((end_shares / begin_shares) ** (1 / years) - 1)


def debt_funded_buyback_flag(net_buyback_amount: float | None, net_debt_change: float | None) -> MetricResult:
    """DEBT_FUNDED_BUYBACKS-style check — UNSUPPORTED for the same reason as
    `net_buyback_yield`: needs the same missing buyback $ input."""
    if net_buyback_amount is None:
        return MetricResult.unsupported(_BUYBACK_UNSUPPORTED_REASON)
    if net_debt_change is None:
        return MetricResult.na("Debt-funded buyback check — missing net debt change")
    return MetricResult.ok(1.0 if (net_buyback_amount > 0 and net_debt_change > 0) else 0.0)
