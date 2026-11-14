"""scripts/generate_sec_fundamentals.py — extraction rules on synthetic companyfacts payloads, and
the run's failure handling against a mocked data.sec.gov (no network)."""

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import generate_sec_fundamentals as gen  # noqa: E402


def _fy(end, val, filed, start=None, form="10-K", accn=None):
    """One annual duration fact. Default start = 364 days before end (a 52-week year)."""
    from datetime import date, timedelta

    start = start or (date.fromisoformat(end) - timedelta(days=364)).isoformat()
    return {"start": start, "end": end, "val": val, "filed": filed, "form": form,
            "accn": accn or f"0000000001-{filed[2:4]}-000001"}


def _inst(end, val, filed, form="10-K"):
    return {"end": end, "val": val, "filed": filed, "form": form, "accn": f"0000000001-{filed[2:4]}-000001"}


def _facts(**concepts):
    """concept=[entries] (USD), or concept=(unit, [entries])."""
    gaap = {}
    for name, spec in concepts.items():
        unit, entries = spec if isinstance(spec, tuple) else ("USD", spec)
        gaap[name] = {"units": {unit: entries}}
    return {"entityName": "Test Corp", "facts": {"us-gaap": gaap}}


def _metric(result, key):
    return next(m for m in result["metrics"] if m["key"] == key)


# -- extraction ------------------------------------------------------------------------------


def test_revenue_is_chosen_per_year_and_takes_the_total():
    facts = _facts(
        NetIncomeLoss=[_fy("2024-12-31", 10, "2025-02-01"), _fy("2025-12-31", 12, "2026-02-01")],
        # 2024 only has contract revenue; 2025 has both — the total (Revenues) must win there.
        Revenues=[_fy("2025-12-31", 300, "2026-02-01")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            _fy("2024-12-31", 180, "2025-02-01"), _fy("2025-12-31", 200, "2026-02-01"),
        ],
    )
    revenue = _metric(gen.extract_annual_fundamentals(facts), "revenue")
    assert revenue["values"] == [180, 300]
    assert revenue["concepts"] == ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]


def test_most_recently_filed_value_wins_and_first_filed_is_the_original():
    facts = _facts(NetIncomeLoss=[
        _fy("2024-12-31", 10, "2025-02-01"),
        _fy("2024-12-31", 11, "2026-02-01"),  # restated in the next year's 10-K
        _fy("2025-12-31", 12, "2026-02-01"),
    ])
    result = gen.extract_annual_fundamentals(facts)
    assert _metric(result, "net_income")["values"] == [11, 12]
    assert result["years"][0] == {"period_end": "2024-12-31", "label": "FY2024", "first_filed": "2025-02-01"}


def test_only_full_year_10k_durations_count():
    facts = _facts(NetIncomeLoss=[
        _fy("2025-09-27", 100, "2025-10-31", start="2024-09-29"),             # 363 days: kept
        _fy("2024-09-28", 90, "2024-11-01", start="2023-09-24"),              # 370 days (53 wk): kept
        _fy("2025-09-27", 30, "2025-10-31", start="2025-06-29"),              # Q4 inside a 10-K
        _fy("2025-06-28", 70, "2025-08-01", start="2024-06-30", form="10-Q"),  # TTM-ish in a 10-Q
        _fy("2023-12-31", 50, "2024-03-01", form="20-F"),
    ])
    result = gen.extract_annual_fundamentals(facts)
    assert [y["period_end"] for y in result["years"]] == ["2024-09-28", "2025-09-27"]
    assert _metric(result, "net_income")["values"] == [90, 100]


def test_keeps_only_the_last_n_years_labeled_by_end_year():
    facts = _facts(NetIncomeLoss=[_fy(f"{y}-01-31", y, f"{y}-03-15") for y in range(2018, 2027)])
    result = gen.extract_annual_fundamentals(facts, years=5)
    assert [y["label"] for y in result["years"]] == ["FY2022", "FY2023", "FY2024", "FY2025", "FY2026"]


def test_instant_equity_aligns_to_fiscal_year_ends_and_fcf_is_ocf_minus_capex():
    facts = _facts(
        NetIncomeLoss=[_fy("2024-12-31", 10, "2025-02-01"), _fy("2025-12-31", 12, "2026-02-01")],
        NetCashProvidedByUsedInOperatingActivities=[
            _fy("2024-12-31", 50, "2025-02-01"), _fy("2025-12-31", 60, "2026-02-01"),
        ],
        PaymentsToAcquirePropertyPlantAndEquipment=[_fy("2025-12-31", 15, "2026-02-01")],
        StockholdersEquity=[
            _inst("2024-12-31", 400, "2025-02-01"), _inst("2025-12-31", 450, "2026-02-01"),
            _inst("2025-06-30", 999, "2025-08-01", form="10-Q"),
        ],
    )
    result = gen.extract_annual_fundamentals(facts)
    assert _metric(result, "equity")["values"] == [400, 450]
    assert _metric(result, "free_cash_flow")["values"] == [None, 45]  # no capex in 2024 -> no FCF
    keys = [m["key"] for m in result["metrics"]]
    assert keys.index("free_cash_flow") == keys.index("capex") + 1


def test_missing_concepts_stay_null_never_approximated():
    facts = _facts(NetIncomeLoss=[_fy("2025-12-31", 12, "2026-02-01")])
    result = gen.extract_annual_fundamentals(facts)
    assert _metric(result, "operating_income")["values"] == [None]
    assert _metric(result, "eps_diluted")["values"] == [None]


def test_eps_reads_the_per_share_unit():
    facts = _facts(
        NetIncomeLoss=[_fy("2025-12-31", 12, "2026-02-01")],
        EarningsPerShareDiluted=("USD/shares", [_fy("2025-12-31", 1.23, "2026-02-01")]),
    )
    assert _metric(gen.extract_annual_fundamentals(facts), "eps_diluted")["values"] == [1.23]


def test_falls_back_to_revenue_periods_when_net_income_is_absent():
    facts = _facts(Revenues=[_fy("2025-12-31", 300, "2026-02-01")])
    result = gen.extract_annual_fundamentals(facts)
    assert result["status"] == "ok"
    assert [y["period_end"] for y in result["years"]] == ["2025-12-31"]


def test_foreign_filer_without_10k_is_no_10k():
    facts = _facts(NetIncomeLoss=("EUR", [_fy("2025-12-31", 12, "2026-02-01", form="20-F")]))
    assert gen.extract_annual_fundamentals(facts) == {"status": "no_10k"}
    assert gen.extract_annual_fundamentals({"facts": {"ifrs-full": {}}}) == {"status": "no_10k"}


def test_latest_10k_is_the_newest_filing():
    facts = _facts(NetIncomeLoss=[
        _fy("2024-12-31", 10, "2025-02-01", accn="A-1"),
        _fy("2024-12-31", 10, "2026-02-01", accn="A-2"),
        _fy("2025-12-31", 12, "2026-02-01", accn="A-2"),
    ])
    assert gen.extract_annual_fundamentals(facts)["latest_10k"] == {
        "accession": "A-2", "filed": "2026-02-01", "form": "10-K",
    }


def test_bank_revenue_is_net_interest_plus_noninterest_income_not_fees_alone():
    end, filed = "2025-12-31", "2026-02-15"
    facts = _facts(
        NetIncomeLoss=[_fy(end, 2211, filed)],
        RevenueFromContractWithCustomerExcludingAssessedTax=[_fy(end, 1562, filed)],  # fees only
        InterestIncomeExpenseNet=[_fy(end, 5991, filed)],
        NoninterestIncome=[_fy(end, 2175, filed)],
    )
    revenue = _metric(gen.extract_annual_fundamentals(facts), "revenue")
    assert revenue["values"] == [8166]
    assert revenue["concepts"] == [gen._BANK_REVENUE_NOTE]


def test_reit_revenue_takes_lease_income_over_tiny_contract_revenue():
    end, filed = "2025-12-31", "2026-02-15"
    facts = _facts(
        NetIncomeLoss=[_fy(end, 384, filed)],
        RevenueFromContractWithCustomerExcludingAssessedTax=[_fy(end, 13, filed)],
        OperatingLeaseLeaseIncome=[_fy(end, 1560, filed)],
    )
    assert _metric(gen.extract_annual_fundamentals(facts), "revenue")["values"] == [1560]


def test_revenue_including_excise_tax_only_as_last_resort():
    end, filed = "2026-04-30", "2026-06-12"
    both = _facts(
        NetIncomeLoss=[_fy(end, 715, filed)],
        RevenueFromContractWithCustomerExcludingAssessedTax=[_fy(end, 3928, filed)],
        RevenueFromContractWithCustomerIncludingAssessedTax=[_fy(end, 5082, filed)],
    )
    assert _metric(gen.extract_annual_fundamentals(both), "revenue")["values"] == [3928]
    only_gross = _facts(
        NetIncomeLoss=[_fy(end, 715, filed)],
        RevenueFromContractWithCustomerIncludingAssessedTax=[_fy(end, 5082, filed)],
    )
    assert _metric(gen.extract_annual_fundamentals(only_gross), "revenue")["values"] == [5082]


def test_revenue_ignores_a_small_lease_line_when_contract_revenue_incl_tax_is_the_only_total():
    end, filed = "2026-07-31", "2026-09-20"
    facts = _facts(  # Copart-style
        NetIncomeLoss=[_fy(end, 1500, filed)],
        OperatingLeaseLeaseIncome=[_fy(end, 17, filed)],
        RevenueFromContractWithCustomerIncludingAssessedTax=[_fy(end, 4666, filed)],
    )
    assert _metric(gen.extract_annual_fundamentals(facts), "revenue")["values"] == [4666]


def test_utility_revenue_and_a_partial_revenues_tag():
    end, filed = "2025-12-31", "2026-02-15"
    utility = _facts(
        NetIncomeLoss=[_fy(end, 1400, filed)],
        OperatingLeaseLeaseIncome=[_fy(end, 61, filed)],
        RegulatedAndUnregulatedOperatingRevenue=[_fy(end, 15814, filed)],
    )
    assert _metric(gen.extract_annual_fundamentals(utility), "revenue")["values"] == [15814]
    partial_revenues = _facts(
        NetIncomeLoss=[_fy(end, 100, filed)],
        Revenues=[_fy(end, 40, filed)],
        RevenueFromContractWithCustomerExcludingAssessedTax=[_fy(end, 900, filed)],
    )
    assert _metric(gen.extract_annual_fundamentals(partial_revenues), "revenue")["values"] == [900]


def test_net_income_falls_back_and_years_can_anchor_on_cash_flow():
    end, filed = "2025-12-31", "2026-02-15"
    facts = _facts(
        NetIncomeLossAvailableToCommonStockholdersBasic=[_fy(end, 4800, filed)],  # Truist-style
        NetCashProvidedByUsedInOperatingActivities=[_fy(end, 7000, filed)],
    )
    result = gen.extract_annual_fundamentals(facts)
    assert result["status"] == "ok"
    assert _metric(result, "net_income")["values"] == [4800]
    cash_only = _facts(NetCashProvidedByUsedInOperatingActivities=[_fy(end, 7000, filed)])
    assert [y["period_end"] for y in gen.extract_annual_fundamentals(cash_only)["years"]] == [end]


def test_parse_company_tickers_and_search_and_filing_url():
    payload = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
               "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "Berkshire"},
               "2": {"cik_str": 999, "ticker": "AAPL", "title": "dup"}}
    parsed = gen.parse_company_tickers(payload)
    assert parsed == {"AAPL": [(320193, "Apple Inc."), (999, "dup")], "BRK-B": [(1067983, "Berkshire")]}
    assert gen._pick_cik(parsed["AAPL"], "Apple Inc") == (320193, "Apple Inc.")
    assert gen._pick_cik([(1, "BofA Finance LLC"), (70858, "BANK OF AMERICA CORP /DE/")], "Bank Of America Corp")[0] == 70858
    assert gen._pick_cik([(5, "Unrelated")], "Apple Inc")[0] == 5  # no name match: first entry
    search = {"hits": {"hits": [
        {"_id": "818972", "_source": {"entity": "BNY MELLON MUNI FUND (LEO)", "tickers": "LEO"}},
        {"_id": "1390777", "_source": {"entity": "Bank of New York Mellon Corp (BNY, BNY-PK)", "tickers": "BNY, BNY-PK"}},
        {"_id": "2052410", "_source": {"entity": "SOMEONE"}},
    ]}}
    assert gen.cik_from_search(search, "BNY") == 1390777
    assert gen.cik_from_search(search, "XYZ") is None
    assert gen.filing_index_url(320193, "0000320193-26-000026") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000026/"
    )


@pytest.mark.parametrize("sec, site, expected", [
    ("Apple Inc.", "Apple Inc", True),
    ("The Bank of New York Mellon Corporation", "Bank Of New York Mellon Corp", True),
    ("GE HealthCare Technologies Inc.", "GE HealthCare Technologies Inc", True),
    ("Block, Inc.", "Block Inc", True),
    ("BNY MELLON STRATEGIC MUNICIPALS, INC.", "Bank Of New York Mellon Corp", True),  # lenient
    ("Huntington Ingalls Industries, Inc.", "Huntington Bancshares Inc", True),       # lenient
    ("Some Shell Co", "Apple Inc", False),
    ("Camden National Corp", "Camden Property Trust", True),
    ("ConocoPhillips", "Conoco Phillips", True),
    ("LOWES COMPANIES INC", "Lowe's Cos. Inc", True),
    ("MCDONALDS CORP", "McDonald's Corp", True),
    ("GENERAL ELECTRIC COMPANY", "GE Aerospace", True),
    ("BofA Finance LLC", "Bank Of America Corp", False),
    (None, "Apple Inc", True),
])
def test_names_match(sec, site, expected):
    assert gen.names_match(sec, site) is expected


# -- run / failure handling ------------------------------------------------------------------

_GOOD_FACTS = _facts(NetIncomeLoss=[_fy("2025-12-31", 12, "2026-02-01")])


@pytest.fixture
def site(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    (data / "index.json").write_text(json.dumps({
        "tickers": ["AAA", "BBB", "CCC", "SPY"],
        "names": {"AAA": "Test Corp", "BBB": "Test Corp", "CCC": "Test Corp", "SPY": "SPDR"},
    }))
    (data / "SPY.json").write_text(json.dumps({"is_etf": True}))
    monkeypatch.setattr(gen, "_DATA_DIR", data)
    monkeypatch.setattr(gen, "_OUTPUT_DIR", data / "sec")
    return data / "sec"


_TICKERS = {"AAA": 1, "BBB": 2, "CCC": 3, "SPY": 4}


def _client(responses, company_tickers_status=200, seen=None):
    """responses: CIK int -> status code or facts dict. company_tickers_status=403 forces the
    per-ticker EDGAR search fallback."""
    def handler(request):
        if seen is not None:
            seen.append(str(request.url))
        if request.url.path.endswith("company_tickers.json"):
            if company_tickers_status != 200:
                return httpx.Response(company_tickers_status)
            return httpx.Response(200, json={str(i): {"cik_str": c, "ticker": t, "title": t}
                                             for i, (t, c) in enumerate(_TICKERS.items())})
        if request.url.host == "efts.sec.gov":
            t = request.url.params["keysTyped"]
            return httpx.Response(200, json={"hits": {"hits": [
                {"_id": str(_TICKERS[t]), "_source": {"entity": f"Test ({t})", "tickers": t}}]}})
        cik = int(request.url.path.split("CIK")[1].split(".")[0])
        r = responses.get(cik, 404)
        return httpx.Response(r) if isinstance(r, int) else httpx.Response(200, json=r)
    return httpx.Client(transport=httpx.MockTransport(handler))


def _run(responses, tickers=None, **client_kw):
    gen.main(tickers, client=_client(responses, **client_kw), sleep=lambda s: None)


def _read(out, t):
    return json.loads((out / f"{t}.json").read_text(encoding="utf-8"))


def test_full_run_writes_equities_only_and_links_the_filing(site):
    _run({1: _GOOD_FACTS, 2: _GOOD_FACTS, 3: 404})
    assert sorted(p.stem for p in site.glob("*.json")) == ["AAA", "BBB", "CCC"]  # no ETF file
    aaa = _read(site, "AAA")
    assert aaa["status"] == "ok" and aaa["cik"] == 1 and aaa["entity_name"] == "Test Corp"
    assert aaa["latest_10k"]["url"].startswith("https://www.sec.gov/Archives/edgar/data/1/")
    assert _read(site, "CCC")["status"] == "no_10k"


def test_failing_ticker_keeps_its_previous_file(site):
    site.mkdir()
    (site / "BBB.json").write_text(json.dumps({"ticker": "BBB", "status": "ok", "old": True}))
    _run({1: _GOOD_FACTS, 2: 503, 3: _GOOD_FACTS})
    assert _read(site, "BBB")["old"] is True


def test_mass_failure_aborts_without_writing(site):
    with pytest.raises(RuntimeError, match="0/3 SEC fetches succeeded"):
        _run({1: 503, 2: 503, 3: 503})
    assert not site.exists()


def test_full_run_removes_orphans_but_partial_run_does_not(site):
    site.mkdir()
    (site / "OLD.json").write_text("{}")
    _run({1: _GOOD_FACTS}, tickers=["AAA"])
    assert (site / "OLD.json").exists()
    _run({1: _GOOD_FACTS, 2: _GOOD_FACTS, 3: _GOOD_FACTS})
    assert not (site / "OLD.json").exists()


def test_falls_back_to_edgar_search_when_company_tickers_is_refused(site):
    seen = []
    _run({1: _GOOD_FACTS, 2: _GOOD_FACTS, 3: _GOOD_FACTS}, company_tickers_status=403, seen=seen)
    assert _read(site, "BBB")["cik"] == 2
    assert sum("efts.sec.gov" in u for u in seen) == 3  # one lookup per equity, none for the ETF


def test_name_mismatch_is_not_published_and_removes_a_stale_file(site):
    site.mkdir()
    (site / "BBB.json").write_text(json.dumps({"ticker": "BBB", "status": "ok"}))
    other = {**_GOOD_FACTS, "entityName": "Completely Unrelated Holdings"}
    _run({1: _GOOD_FACTS, 2: other, 3: _GOOD_FACTS})
    assert not (site / "BBB.json").exists()
    assert (site / "AAA.json").exists()


def test_name_mismatch_retries_with_edgar_search(site, monkeypatch):
    # company_tickers points AAA at CIK 9 (wrong company); the search finds CIK 1 (right one).
    monkeypatch.setitem(_TICKERS, "AAA", 1)
    wrong = {**_GOOD_FACTS, "entityName": "Completely Unrelated Holdings"}

    def handler(request):
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 9, "ticker": "AAA", "title": "x"}})
        if request.url.host == "efts.sec.gov":
            return httpx.Response(200, json={"hits": {"hits": [{"_id": "1", "_source": {"tickers": "AAA"}}]}})
        cik = int(request.url.path.split("CIK")[1].split(".")[0])
        return httpx.Response(200, json=wrong if cik == 9 else _GOOD_FACTS)

    gen.main(["AAA"], client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert _read(site, "AAA")["cik"] == 1


def test_revenue_total_smaller_than_contract_revenue_is_still_the_total():
    end, filed = "2025-12-31", "2026-02-20"
    facts = _facts(  # Williams-style: derivative losses netted into Revenues
        NetIncomeLoss=[_fy(end, 2500, filed)],
        Revenues=[_fy(end, 11950, filed)],
        RevenueFromContractWithCustomerExcludingAssessedTax=[_fy(end, 14899, filed)],
    )
    revenue = _metric(gen.extract_annual_fundamentals(facts), "revenue")
    assert revenue["values"] == [11950] and revenue["concepts"] == ["Revenues"]


def test_entity_name_quirk_is_accepted_when_sec_ticker_title_matches(site):
    quirky = {**_GOOD_FACTS, "entityName": "BofA Finance LLC"}

    def handler(request):
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json={"0": {"cik_str": 1, "ticker": "AAA", "title": "TEST CORP /DE/"}})
        return httpx.Response(200, json=quirky)

    gen.main(["AAA"], client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert _read(site, "AAA")["cik"] == 1
    assert _read(site, "AAA")["entity_name"] == "TEST CORP"  # listed name, state suffix dropped


def test_cik_override_wins(site, monkeypatch):
    monkeypatch.setattr(gen, "_CIK_OVERRIDES", {"AAA": 3})
    _run({1: _GOOD_FACTS, 3: _GOOD_FACTS}, tickers=["AAA"])
    assert _read(site, "AAA")["cik"] == 3


def test_retries_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, text="ok")

    sleeps = []
    r = gen._get(httpx.Client(transport=httpx.MockTransport(handler)), "https://x", sleeps.append)
    assert r.text == "ok" and sleeps == [2.0, 6.0]


def test_blank_user_agent_falls_back(monkeypatch):
    monkeypatch.setattr(gen.settings, "sec_edgar_user_agent", "  ")
    assert gen._user_agent() == gen._DEFAULT_USER_AGENT
