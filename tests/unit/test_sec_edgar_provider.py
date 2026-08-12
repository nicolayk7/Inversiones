"""Provider -> DTO mapping tests for `SecEdgarFundamentalsProvider`. Hermetic — no live network
call; the `us-gaap` facts payload is a small synthetic fixture shaped exactly like SEC EDGAR's
real `companyfacts` response (verified against the live AAPL response during development, see
the implementation report), injected directly into the provider's cache rather than fetched."""

from datetime import date

from packages.providers.fundamentals.sec_edgar import SecEdgarFundamentalsProvider

_FIXTURE_FACTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {
        "units": {"USD": [
            {"start": "2024-09-29", "end": "2025-09-27", "val": 1000, "form": "10-K", "filed": "2025-10-31", "fy": 2025, "fp": "FY"},
            {"start": "2023-10-01", "end": "2024-09-28", "val": 900, "form": "10-K", "filed": "2025-10-31", "fy": 2025, "fp": "FY"},
            {"start": "2024-12-29", "end": "2025-03-29", "val": 250, "form": "10-Q", "filed": "2025-05-01", "fy": 2025, "fp": "Q2"},
        ]}
    },
    "NetIncomeLoss": {
        "units": {"USD": [
            {"start": "2024-09-29", "end": "2025-09-27", "val": 200, "form": "10-K", "filed": "2025-10-31"},
            {"start": "2023-10-01", "end": "2024-09-28", "val": 180, "form": "10-K", "filed": "2025-10-31"},
        ]}
    },
    # Share-denominated, not dollar-denominated — tagged under units.shares in real SEC XBRL
    # facts (verified against AAPL's live companyfacts response), not units.USD. This is the
    # concept the units-bucket bug affected.
    "WeightedAverageNumberOfDilutedSharesOutstanding": {
        "units": {"shares": [
            {"start": "2024-09-29", "end": "2025-09-27", "val": 50, "form": "10-K", "filed": "2025-10-31"},
            {"start": "2023-10-01", "end": "2024-09-28", "val": 48, "form": "10-K", "filed": "2025-10-31"},
        ]}
    },
    "Assets": {
        "units": {"USD": [
            {"end": "2025-09-27", "val": 3000, "form": "10-K", "filed": "2025-10-31"},
            {"end": "2024-09-28", "val": 2800, "form": "10-K", "filed": "2025-10-31"},
        ]}
    },
    "StockholdersEquity": {
        "units": {"USD": [
            {"end": "2025-09-27", "val": 700, "form": "10-K", "filed": "2025-10-31"},
            {"end": "2024-09-28", "val": 650, "form": "10-K", "filed": "2025-10-31"},
        ]}
    },
    "NetCashProvidedByUsedInOperatingActivities": {
        "units": {"USD": [
            {"start": "2024-09-29", "end": "2025-09-27", "val": 250, "form": "10-K", "filed": "2025-10-31"},
            {"start": "2023-10-01", "end": "2024-09-28", "val": 220, "form": "10-K", "filed": "2025-10-31"},
        ]}
    },
    "PaymentsToAcquirePropertyPlantAndEquipment": {
        "units": {"USD": [
            {"start": "2024-09-29", "end": "2025-09-27", "val": 30, "form": "10-K", "filed": "2025-10-31"},
            {"start": "2023-10-01", "end": "2024-09-28", "val": 28, "form": "10-K", "filed": "2025-10-31"},
        ]}
    },
    # MinorityInterest and PreferredStockValue deliberately absent — proves the "not known to
    # exist" (M4) path rather than "known but unsourced".
}


def _provider_with_fixture() -> SecEdgarFundamentalsProvider:
    provider = SecEdgarFundamentalsProvider()
    provider._facts_cache["FIX"] = _FIXTURE_FACTS
    return provider


def test_income_statements_selects_two_most_recent_full_fiscal_years():
    provider = _provider_with_fixture()
    statements = provider.get_income_statements("FIX")
    assert [s.period_end.isoformat() for s in statements] == ["2025-09-27", "2024-09-28"]
    assert statements[0].revenue == 1000.0
    assert statements[1].revenue == 900.0
    assert statements[0].net_income == 200.0


def test_diluted_shares_outstanding_reads_from_shares_unit_not_usd():
    """Regression test for the units-bucket bug: WeightedAverageNumberOfDilutedSharesOutstanding
    is tagged under units.shares in SEC's XBRL facts, not units.USD. Before the fix, `_flow`
    hardcoded the USD bucket for every concept, so this always silently returned None even though
    the fixture (and real AAPL data) has a value."""
    provider = _provider_with_fixture()
    statements = provider.get_income_statements("FIX")
    assert statements[0].diluted_shares_outstanding == 50.0
    assert statements[1].diluted_shares_outstanding == 48.0

    # Existing USD-denominated flow concepts must be unaffected by the unit parameter's default.
    assert statements[0].net_income == 200.0
    assert statements[0].revenue == 1000.0


def test_income_statement_excludes_10q_quarterly_entries():
    """The 250-value Q2 10-Q entry must never be mistaken for a full fiscal year."""
    provider = _provider_with_fixture()
    statements = provider.get_income_statements("FIX")
    assert 250 not in [s.revenue for s in statements]


def test_balance_sheet_carries_correct_pit_fields():
    provider = _provider_with_fixture()
    statements = provider.get_balance_sheets("FIX")
    assert statements[0].total_assets == 3000.0
    assert statements[0].book_equity == 700.0
    assert statements[0].reported_at.isoformat() == "2025-10-31"
    assert statements[0].available_at.isoformat().startswith("2025-10-31")


def test_absent_concept_maps_to_not_known_not_zero_by_fabrication():
    """MinorityInterest/PreferredStockValue are absent from the fixture entirely — must map to
    known=False (M4's "genuinely doesn't have it" case), not a fabricated known=True/value=0."""
    provider = _provider_with_fixture()
    statements = provider.get_balance_sheets("FIX")
    assert statements[0].minority_interest_known is False
    assert statements[0].minority_interest is None
    assert statements[0].preferred_equity_known is False


def test_cash_flow_statement_maps_ocf_and_capex():
    provider = _provider_with_fixture()
    statements = provider.get_cash_flow_statements("FIX")
    assert statements[0].operating_cash_flow == 250.0
    assert statements[0].capex == 30.0
    assert statements[0].delta_working_capital is None  # not tagged — never derived/fabricated


def test_unknown_ticker_raises_not_a_silent_empty_result():
    import pytest
    from packages.providers.fundamentals.sec_edgar import SecEdgarError

    provider = SecEdgarFundamentalsProvider()
    with pytest.raises(SecEdgarError):
        provider._cik_for("NOTATICKER")


# ==============================================================================================
# Phase 7A — PIT hardening of _full_fiscal_years(): a period_end mentioned in more than one 10-K
# (its own original filing, plus later stale comparatives) must be dated by when it was first
# knowable, not by whichever mention happens to have the latest `filed` — unless the value
# genuinely changed (a real restatement), in which case the corrected value's OWN filing date is
# correct. Verified empirically against real AAPL data (see the audit) that every historical
# period's value is identical across every mention — no real restatement exists there — so these
# fixtures construct both cases synthetically, explicitly labeled.
# ==============================================================================================

# Case: 2023's value (1000) reappears identically in two later 10-Ks — no restatement. The
# ORIGINAL filing (2024-02-01) is the true first-availability date.
_PIT_HARDENING_FACTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {
        "units": {"USD": [
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1200, "form": "10-K", "filed": "2025-02-01"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "form": "10-K", "filed": "2024-02-01"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "form": "10-K", "filed": "2025-02-01"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 1000, "form": "10-K", "filed": "2026-02-01"},
        ]}
    },
}

# Case: 2023's value genuinely changes (900 -> 950) between its original filing and a later one —
# a real restatement, synthetic (no real AAPL example exists to draw from).
_RESTATEMENT_FACTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {
        "units": {"USD": [
            {"start": "2024-01-01", "end": "2024-12-31", "val": 1200, "form": "10-K", "filed": "2025-02-01"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 900, "form": "10-K", "filed": "2024-02-01"},
            {"start": "2023-01-01", "end": "2023-12-31", "val": 950, "form": "10-K", "filed": "2025-02-01"},
        ]}
    },
}


def _provider_with(facts: dict, ticker: str = "PIT") -> SecEdgarFundamentalsProvider:
    provider = SecEdgarFundamentalsProvider()
    provider._facts_cache[ticker] = facts
    return provider


def test_a_original_filing_defines_first_availability_not_a_later_comparative():
    """A: reported_at/available_at for the 2023 period must be its ORIGINAL filing (2024-02-01),
    not a later comparative mention."""
    statements = _provider_with(_PIT_HARDENING_FACTS).get_income_statements("PIT")
    prior = next(s for s in statements if s.period_end.isoformat() == "2023-12-31")
    assert prior.reported_at.isoformat() == "2024-02-01"


def test_b_data_is_available_and_correct_after_the_original_filing():
    """B: after its original filing, the period is available with the correct value."""
    statements = _provider_with(_PIT_HARDENING_FACTS).get_income_statements("PIT")
    prior = next(s for s in statements if s.period_end.isoformat() == "2023-12-31")
    assert prior.available_at.isoformat().startswith("2024-02-01")
    assert prior.revenue == 1000.0


def test_c_later_identical_comparative_does_not_move_first_availability():
    """C: two additional 10-Ks (2025-02-01, 2026-02-01) repeat the identical 2023 value — this
    must NOT push available_at later than the true original filing. This is the exact bug this
    phase fixes: before the fix, this resolved to 2026-02-01 (the latest mention), not 2024-02-01
    (the true original)."""
    statements = _provider_with(_PIT_HARDENING_FACTS).get_income_statements("PIT")
    prior = next(s for s in statements if s.period_end.isoformat() == "2023-12-31")
    assert prior.reported_at.isoformat() == "2024-02-01"
    assert prior.reported_at.isoformat() != "2026-02-01"


def test_d_genuine_restatement_keeps_latest_value_dated_to_its_own_filing():
    """D: when the value genuinely changes across filings (a real restatement), the corrected
    value is used — unchanged from before this fix, still the most authoritative figure — and is
    now correctly stamped with ITS OWN filing date (2025-02-01), not the original's (2024-02-01)."""
    statements = _provider_with(_RESTATEMENT_FACTS).get_income_statements("PIT")
    prior = next(s for s in statements if s.period_end.isoformat() == "2023-12-31")
    assert prior.revenue == 950.0  # the restated value, not the original 900
    assert prior.reported_at.isoformat() == "2025-02-01"  # the restatement's own filing date


def test_e_pit_adversarial_query_never_sees_unavailable_information():
    """E: available_at must never make the 2023 period look knowable before its true original
    filing, and must correctly mark it knowable immediately after — this is the entire point of
    getting available_at right, and is what any PIT query (available_at <= as_of) depends on."""
    statements = _provider_with(_PIT_HARDENING_FACTS).get_income_statements("PIT")
    prior = next(s for s in statements if s.period_end.isoformat() == "2023-12-31")

    as_of_before_original_filing = date(2024, 1, 1)
    as_of_right_after_original_filing = date(2024, 2, 2)

    assert prior.available_at.date() > as_of_before_original_filing  # correctly NOT yet knowable
    assert prior.available_at.date() <= as_of_right_after_original_filing  # correctly knowable


# ==============================================================================================
# Phase 7B — quarterly Revenue capability (get_quarterly_revenue). Fixture shaped exactly like
# real AAPL data (verified live during the audit): FY2024 has all four quarters directly tagged
# (Q2/Q3 each carry BOTH their own single-quarter fact and a YTD-cumulative fact in the same
# 10-Q); FY2025 deliberately omits Q2's direct single-quarter tag (only a YTD-through-Q2 fact
# exists) to exercise the YTD->single-quarter fallback, and omits the Q3-YTD fact entirely to
# exercise "cannot safely derive — omit, don't invent."
# ==============================================================================================

_QUARTERLY_FIXTURE_FACTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax": {
        "units": {"USD": [
            # FY2024 (2023-10-01 -> 2024-09-28): every quarter directly derivable.
            {"start": "2023-10-01", "end": "2023-12-30", "val": 1000, "form": "10-Q", "fp": "Q1", "filed": "2024-02-01"},
            {"start": "2023-12-31", "end": "2024-03-30", "val": 900, "form": "10-Q", "fp": "Q2", "filed": "2024-05-01"},
            {"start": "2023-10-01", "end": "2024-03-30", "val": 1900, "form": "10-Q", "fp": "Q2", "filed": "2024-05-01"},  # YTD — must NOT be picked as Q2
            {"start": "2024-03-31", "end": "2024-06-29", "val": 950, "form": "10-Q", "fp": "Q3", "filed": "2024-08-01"},
            {"start": "2023-10-01", "end": "2024-06-29", "val": 2850, "form": "10-Q", "fp": "Q3", "filed": "2024-08-01"},  # YTD — must NOT be picked as Q3
            {"start": "2023-10-01", "end": "2024-09-28", "val": 4000, "form": "10-K", "fp": "FY", "filed": "2024-11-01"},
            # Same Q1 re-mentioned identically in a later comparative — must not move its date.
            {"start": "2023-10-01", "end": "2023-12-30", "val": 1000, "form": "10-Q", "fp": "Q1", "filed": "2025-02-01"},

            # FY2025 (2024-09-29 -> 2025-09-27): Q2 has NO direct tag (only YTD) -> fallback case.
            # Q3 has neither a direct tag NOR a YTD-through-Q3 fact -> must be omitted, and Q4
            # (which needs that same YTD-through-Q3 fact) must also be omitted.
            {"start": "2024-09-29", "end": "2024-12-28", "val": 1100, "form": "10-Q", "fp": "Q1", "filed": "2025-02-01"},
            {"start": "2024-09-29", "end": "2025-03-29", "val": 2200, "form": "10-Q", "fp": "Q2", "filed": "2025-05-01"},
            {"start": "2024-09-29", "end": "2025-09-27", "val": 4700, "form": "10-K", "fp": "FY", "filed": "2025-10-31"},
        ]}
    },
}


def test_f_quarterly_a_q1_is_read_directly():
    """A: Q1 (YTD-through-Q1 == Q1, only one dimension exists) is read directly."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    assert quarters["2023-12-30"].revenue == 1000.0


def test_g_quarterly_b_q2_uses_single_quarter_not_ytd():
    """B: Q2's YTD fact (1900) exists alongside its single-quarter fact (900) — the single-quarter
    value must be used, never the YTD one."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    assert quarters["2024-03-30"].revenue == 900.0


def test_h_quarterly_c_q3_uses_single_quarter_not_ytd():
    """C: same as B for Q3 — 950 (single-quarter), never 2850 (YTD-through-Q3)."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    assert quarters["2024-06-29"].revenue == 950.0


def test_i_quarterly_d_ytd_to_single_quarter_fallback():
    """D: FY2025's Q2 has no direct single-quarter tag — only a YTD-through-Q2 fact (2200). Must
    correctly derive 2200 - Q1(1100) = 1100, not omit it and not use the raw YTD value."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    assert quarters["2025-03-29"].revenue == 1100.0


def test_j_quarterly_e_q4_derived_from_fy_minus_q3_ytd():
    """E: FY2024's Q4 has no direct tag at all (no filer ever submits one) — must derive
    4000 - 2850 = 1150, dated by the later of the FY 10-K's and the Q3-YTD fact's filing dates."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    q4 = quarters["2024-09-28"]
    assert q4.revenue == 1150.0
    assert q4.reported_at.isoformat() == "2024-11-01"  # max(FY filed, Q3-YTD filed)

    # Sanity: all four FY2024 quarters sum back to the FY total (4000).
    total = quarters["2023-12-30"].revenue + quarters["2024-03-30"].revenue + quarters["2024-06-29"].revenue + q4.revenue
    assert total == 4000.0


def test_k_quarterly_f_unsafe_derivation_is_omitted_not_invented():
    """F: FY2025 has no way to establish Q3 (no direct tag, no YTD-through-Q3 fact to fall back
    on) or Q4 (needs that same missing YTD-through-Q3 fact) — both must be OMITTED from the
    result, never fabricated or approximated from an unrelated figure."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    # FY2025 Q1 and Q2 (fallback-derived) are present...
    assert "2024-12-28" in quarters
    assert "2025-03-29" in quarters
    # ...but no entry exists for FY2025's Q3 or Q4 (period_end 2025-09-27, the fiscal year end,
    # or any period_end between 2025-03-29 and 2025-09-27).
    fy2025_late_periods = [p for p in quarters if "2025-04-01" <= p <= "2025-09-27"]
    assert fy2025_late_periods == []


def test_l_quarterly_g_pit_before_and_after_filing():
    """G: a quarter is not available before its filing date, and is available immediately after —
    same PIT guarantee as the annual path, exercised through the quarterly one."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    q1 = quarters["2023-12-30"]
    assert q1.available_at.date() > date(2024, 1, 1)  # before filing (2024-02-01): not yet known
    assert q1.available_at.date() <= date(2024, 2, 2)  # right after filing: known


def test_m_quarterly_h_later_identical_comparative_does_not_move_first_availability():
    """H: Q1 FY2024 is re-mentioned identically in a later 10-Q (2025-02-01) as a stale
    comparative — its reported_at must remain the ORIGINAL filing date (2024-02-01), exercising
    the same vintage-resolution rule the quarterly path shares with the annual one."""
    quarters = {q.period_end.isoformat(): q for q in _provider_with(_QUARTERLY_FIXTURE_FACTS).get_quarterly_revenue("PIT")}
    assert quarters["2023-12-30"].reported_at.isoformat() == "2024-02-01"


def test_n_quarterly_i_only_reads_usd_bucket_not_shares():
    """I: a decoy entry shaped exactly like a valid single-quarter Q1 fact, but filed under
    units.shares instead of units.USD, must never be picked up as a revenue figure — confirms the
    quarterly path only ever reads the USD bucket, same as the existing annual path, and does not
    regress the Phase 6A units-bucket fix (which lives in `_flow`, untouched by this phase — this
    test targets the NEW `_entries_in_span` codepath specifically)."""
    facts_with_decoy = {
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "units": {
                "USD": [
                    {"start": "2023-10-01", "end": "2023-12-30", "val": 1000, "form": "10-Q", "fp": "Q1", "filed": "2024-02-01"},
                    {"start": "2023-10-01", "end": "2024-09-28", "val": 4000, "form": "10-K", "fp": "FY", "filed": "2024-11-01"},
                ],
                "shares": [{"start": "2023-10-01", "end": "2023-12-30", "val": 999999, "form": "10-Q", "fp": "Q1", "filed": "2024-02-01"}],
            }
        },
    }
    quarters = {q.period_end.isoformat(): q for q in _provider_with(facts_with_decoy).get_quarterly_revenue("PIT")}
    assert quarters["2023-12-30"].revenue == 1000.0  # the USD value, never the shares decoy


def test_o_quarterly_diluted_shares_regression_unaffected():
    """I (continued): confirm Phase 6A's diluted-shares-outstanding fix (a different codepath,
    `_flow`, exercised via `get_income_statements`) is untouched by this phase's changes."""
    statements = _provider_with(_QUARTERLY_FIXTURE_FACTS).get_income_statements("PIT")
    # No WeightedAverageNumberOfDilutedSharesOutstanding in this fixture — must stay None, not
    # silently pick up something from the wrong bucket.
    assert all(s.diluted_shares_outstanding is None for s in statements)
