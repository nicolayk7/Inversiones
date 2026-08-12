"""ROE floor rule (C3, hard + soft) and ROIC with/ex goodwill split (H5)."""

import pytest

from packages.quant_core.fundamentals.quality import roe_dupont, roic, roic_ex_goodwill


def test_roe_hard_na_when_equity_zero():
    result = roe_dupont(net_income=10.0, revenue=100.0, total_assets=200.0, book_equity=0.0, roe_soft_floor_pct_of_assets=0.05)
    assert result.status.value == "N/A"
    assert "book equity <= 0" in result.reason


def test_roe_hard_na_when_equity_negative():
    result = roe_dupont(net_income=10.0, revenue=100.0, total_assets=200.0, book_equity=-5.0, roe_soft_floor_pct_of_assets=0.05)
    assert result.status.value == "N/A"


def test_roe_soft_floor_low_reliability_not_excluded():
    """book_equity=5 is < 5% of total_assets=200 (=10) -> LOW_RELIABILITY, still computed."""
    result = roe_dupont(net_income=1.0, revenue=50.0, total_assets=200.0, book_equity=5.0, roe_soft_floor_pct_of_assets=0.05)
    assert result.status.value == "LOW_RELIABILITY"
    assert result.value is not None
    assert "thin equity base" in result.reason


def test_roe_ok_above_soft_floor():
    result = roe_dupont(net_income=10.0, revenue=100.0, total_assets=200.0, book_equity=100.0, roe_soft_floor_pct_of_assets=0.05)
    assert result.is_ok


def test_roe_hard_floor_takes_precedence_over_soft_floor_check():
    """equity <= 0 must never fall through to the soft-floor comparison."""
    result = roe_dupont(net_income=10.0, revenue=100.0, total_assets=200.0, book_equity=0.0, roe_soft_floor_pct_of_assets=0.05)
    assert result.status.value == "N/A"


def test_roic_with_goodwill_and_ex_goodwill_are_independent_and_both_computable():
    """H5: ROIC (feeds QUALITY_SCORE) is WITH goodwill; ROIC_ex_goodwill is diagnostic-only —
    both computable from the same NOPAT, different Invested Capital denominators."""
    with_goodwill = roic(nopat=20.0, invested_capital=200.0)  # includes $50 goodwill
    ex_goodwill = roic_ex_goodwill(nopat=20.0, invested_capital_ex_goodwill=150.0)
    assert with_goodwill.value == pytest.approx(0.10)
    assert ex_goodwill.value == pytest.approx(0.1333, abs=1e-3)
    assert with_goodwill.value != ex_goodwill.value  # overpriced M&A correctly lowers the with-goodwill figure


def test_roic_na_when_invested_capital_zero():
    result = roic(nopat=10.0, invested_capital=0.0)
    assert result.status.value == "N/A"
