"""Revenue/EPS/FCF growth, margins, ROIC, ROE, debt ratios, valuation, capital allocation —
deterministic raw-metric calculations for Wealth Engine (Phase 1B). Pure functions, no I/O, no
LLM (architecture v1.0 rule 16). Organized into submodules by methodology section; re-exported
here as the package's public surface."""

from packages.quant_core.fundamentals.balance_sheet import (
    debt_to_ebitda,
    gaap_ebitda,
    interest_coverage,
    leverage_band,
    net_debt,
    net_debt_to_fcf,
)
from packages.quant_core.fundamentals.capital_allocation import (
    debt_funded_buyback_flag,
    net_buyback_yield,
    share_count_cagr,
)
from packages.quant_core.fundamentals.fcf import (
    compute_fcf,
    fcf_consistency,
    fcf_conversion,
    fcf_growth_or_trajectory,
)
from packages.quant_core.fundamentals.growth import (
    cagr,
    eps_growth_quality_adjustment,
    growth_acceleration,
    growth_consistency,
    yoy_growth,
)
from packages.quant_core.fundamentals.quality import (
    ebitda_margin,
    fcf_margin,
    gross_margin,
    margin_stability,
    operating_margin,
    roa,
    roe_dupont,
    roic,
    roic_ex_goodwill,
    roic_spread,
    roiic,
)
from packages.quant_core.fundamentals.valuation import (
    enterprise_value,
    fcf_yield,
    gaap_eps,
    market_cap,
    pe_ratio,
    price_to_book,
)

# Backward-compatible aliases for the two Phase 0 stub names — same underlying implementation.
revenue_growth_yoy = yoy_growth

__all__ = [
    "revenue_growth_yoy",
    "yoy_growth",
    "cagr",
    "eps_growth_quality_adjustment",
    "growth_consistency",
    "growth_acceleration",
    "roic",
    "roic_ex_goodwill",
    "roiic",
    "roic_spread",
    "roe_dupont",
    "roa",
    "gross_margin",
    "operating_margin",
    "fcf_margin",
    "ebitda_margin",
    "margin_stability",
    "compute_fcf",
    "fcf_conversion",
    "fcf_growth_or_trajectory",
    "fcf_consistency",
    "net_debt",
    "gaap_ebitda",
    "debt_to_ebitda",
    "interest_coverage",
    "net_debt_to_fcf",
    "leverage_band",
    "gaap_eps",
    "enterprise_value",
    "market_cap",
    "pe_ratio",
    "fcf_yield",
    "price_to_book",
    "net_buyback_yield",
    "share_count_cagr",
    "debt_funded_buyback_flag",
]
