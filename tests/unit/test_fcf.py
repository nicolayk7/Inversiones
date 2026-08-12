"""FCF Trajectory/Growth switch (M2, Rev. 4's corrected two-condition disjunction) and FCF
Conversion's hard N/A rule (C2) — the two most heavily-audited rules in the methodology closure.
All four sign combinations are asserted explicitly; a test that only covered "prior <= 0" would
have hidden the exact bug Rev. 4 fixed."""

import pytest

from packages.quant_core.fundamentals.fcf import compute_fcf, fcf_conversion, fcf_growth_or_trajectory


def test_fcf_is_ocf_minus_capex():
    result = compute_fcf(operating_cash_flow=100.0, capex=30.0)
    assert result.is_ok
    assert result.value == 70.0


# --- M2: all four sign combinations ---

def test_m2_plus_plus_uses_growth_pct():
    name, result = fcf_growth_or_trajectory(prior_fcf=100.0, current_fcf=150.0, prior_fcf_margin=0.1, current_fcf_margin=0.15)
    assert name == "fcf_growth_pct"
    assert result.value == pytest.approx(0.5)


def test_m2_plus_to_minus_uses_trajectory_not_growth():
    """The exact case a same-sign-only-on-the-prior-side check would get wrong: prior > 0,
    current < 0 (falling INTO negative FCF)."""
    name, result = fcf_growth_or_trajectory(prior_fcf=100.0, current_fcf=-20.0, prior_fcf_margin=0.1, current_fcf_margin=-0.02)
    assert name == "fcf_trajectory_pp"
    assert result.value == pytest.approx(-0.12)


def test_m2_minus_to_plus_uses_trajectory():
    name, result = fcf_growth_or_trajectory(prior_fcf=-100.0, current_fcf=50.0, prior_fcf_margin=-0.2, current_fcf_margin=0.08)
    assert name == "fcf_trajectory_pp"
    assert result.value == pytest.approx(0.28)


def test_m2_minus_minus_uses_trajectory_not_naive_pct():
    """The bug Rev. 4 closed: naive % growth from -100 to -50 computes -50% (reads as decline);
    Trajectory correctly reads the margin improvement."""
    name, result = fcf_growth_or_trajectory(prior_fcf=-100.0, current_fcf=-50.0, prior_fcf_margin=-0.20, current_fcf_margin=-0.12)
    assert name == "fcf_trajectory_pp"
    assert result.value == pytest.approx(0.08)  # positive — improvement, not "-50%"


def test_m2_prior_exactly_zero_uses_trajectory():
    name, result = fcf_growth_or_trajectory(prior_fcf=0.0, current_fcf=10.0, prior_fcf_margin=0.0, current_fcf_margin=0.05)
    assert name == "fcf_trajectory_pp"


# --- C2: FCF Conversion hard N/A ---

def test_fcf_conversion_na_when_ni_negative_even_if_fcf_also_negative():
    """The sign-flip bug C2 closes: both FCF and NI negative would otherwise compute a
    plausible-looking positive ratio."""
    result = fcf_conversion(fcf=-50.0, net_income=-100.0)
    assert result.status.value == "N/A"
    assert result.value is None


def test_fcf_conversion_na_when_ni_exactly_zero():
    result = fcf_conversion(fcf=10.0, net_income=0.0)
    assert result.status.value == "N/A"


def test_fcf_conversion_ok_when_ni_positive():
    result = fcf_conversion(fcf=80.0, net_income=100.0)
    assert result.is_ok
    assert result.value == pytest.approx(0.8)
