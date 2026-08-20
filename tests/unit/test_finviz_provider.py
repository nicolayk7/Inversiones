"""Finviz `FundamentalsProvider` (partial) mapping tests — no live network access (httpx
MockTransport builds real httpx.Response objects from a canned HTML fixture shaped exactly like
finviz.com/quote.ashx's real markup, confirmed live during development — see finviz.py's module
docstring). One opt-in live test at the bottom hits the real page; skipped unless
RUN_FINVIZ_LIVE_TEST=1 is set, per this provider's own ToS-caution disclosure (no bulk/CI-default
live hits against a source with no explicit scraping allowance)."""

import os
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from packages.providers.fundamentals.finviz import (
    _ROW_PATTERN,
    FinvizError,
    FinvizFundamentalsProvider,
    FinvizNotFoundError,
    FinvizResponseError,
    _parse_categories,
    _parse_number,
)


def _cell(tooltip: str, label: str, value: str) -> str:
    return (
        f'<td class="snapshot-td2" data-boxover-html="{tooltip}">'
        f'<div class="snapshot-td-label">{label}</div></td>'
        f'<td class="snapshot-td2"><div class="snapshot-td-content"><b>{value}</b></div></td>'
    )


# Shaped like the real six-table, 14-row grid, condensed to the fields this adapter reads (plus
# the genuine "EPS next Y" duplicate-label case) — enough to exercise the tooltip-keyed lookup
# without reproducing all 84 real cells.
_AAPL_QUOTE_HTML = f"""
<html><body>
<table class="js-snapshot-table snapshot-table2"><tbody>
<tr class="table-dark-row">
{_cell("Revenue (ttm)", "Sales", "466.82B")}
{_cell("Diluted EPS (ttm)", "EPS (ttm)", "8.72")}
{_cell("Gross Margin (ttm)", "Gross Margin", "48.65%")}
{_cell("Operating Margin (ttm)", "Oper. Margin", "33.17%")}
{_cell("Return on Invested Capital (ttm)", "ROIC", "72.08%")}
{_cell("Return on Equity (ttm)", "ROE", "148.75%")}
{_cell("Current stock price", "Price", "314.81")}
{_cell("Shares outstanding", "Shs Outstand", "14.61B")}
{_cell("Price to Free Cash Flow (ttm)", "P/FCF", "33.61")}
{_cell("Volume", "Volume", "17,509,621")}
{_cell("EPS estimate for next year", "EPS next Y", "9.54")}
{_cell("EPS growth next year", "EPS next Y", "7.98%")}
{_cell("Debt/Eq ratio placeholder", "Some N/A Field", "-")}
</tr>
</tbody></table>
</body></html>
"""

_NOT_FOUND_HTML = "<html><body><h1>Ticker not found</h1></body></html>"

# Condensed but real-shaped chart data block — same 3-series-in-fixed-order layout confirmed live
# against AAPL and MSFT (see finviz.py's _parse_charts docstring).
_CHART_JSON = (
    '{"annual":{"values":['
    '[{"name":"2024","value":6.08},{"name":"TTM","value":8.72,"isOutlined":true}],'
    '[{"name":"2024","value":391035},{"name":"TTM","value":466823,"isOutlined":true}],'
    '[{"name":"2024","value":15116.8},{"name":"MRQ","value":14608.9,"isOutlined":true}]'
    ']},"quarterly":{"values":['
    '[{"name":"Q3 \'26","value":2.02}],[{"name":"Q3 \'26","value":109417}],'
    '[{"name":"Q3 \'26","value":14608.9}]'
    ']}}'
)
_AAPL_QUOTE_HTML_WITH_CHARTS = _AAPL_QUOTE_HTML.replace(
    "</body></html>",
    f'<script id="fa-init-data-0" type="application/json">{_CHART_JSON}</script></body></html>',
)

# Real-shaped header categories block — equity form (all 5 links) confirmed live against AAPL.
_AAPL_CATEGORIES_HTML = """
<div class="quote-header_categories">
<a href="screener?v=111&f=sec_technology" class="quote-header_category">Technology</a>
<a href="screener?v=111&f=ind_consumerelectronics" class="quote-header_category" title="Consumer Electronics"><span class="min-w-0 truncate">Consumer Electronics</span></a>
<a href="screener?v=111&f=geo_usa" class="quote-header_category">USA</a>
<a href="screener?v=111&f=cap_mega" class="quote-header_category">Mega</a>
<a href="screener?v=111&f=exch_nasd" class="quote-header_category">NASD</a>
</div>
"""
# ETF form — confirmed live against SPY: the cap_ link is entirely absent (not blank, MISSING).
_ETF_CATEGORIES_HTML = """
<div class="quote-header_categories">
<a href="screener?v=111&f=sec_financial" class="quote-header_category">Financial</a>
<a href="screener?v=111&f=ind_exchangetradedfund" class="quote-header_category" title="Exchange Traded Fund"><span class="min-w-0 truncate">Exchange Traded Fund</span></a>
<a href="screener?v=111&f=geo_usa" class="quote-header_category">USA</a>
<a href="screener?v=111&f=exch_nyse" class="quote-header_category">NYSE</a>
</div>
"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _provider(handler) -> FinvizFundamentalsProvider:
    return FinvizFundamentalsProvider(client=_client(handler))


# -- _parse_number ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("466.82B", 466.82e9),
        ("14.61B", 14.61e9),
        ("8.72", 8.72),
        ("48.65%", 0.4865),
        ("-", None),
        ("", None),
        ("166000", 166000.0),
        ("1.98M", 1.98e6),
        ("2.5K", 2.5e3),
        ("17,509,621", 17509621.0),
    ],
)
def test_parse_number(raw, expected):
    result = _parse_number(raw)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


# -- valid response maps to FundamentalsRecord ---------------------------------------------------


def test_valid_response_maps_to_fundamentals_record():
    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)

    records = _provider(handler).get_quarterly_fundamentals("AAPL")

    assert len(records) == 1
    record = records[0]
    assert record.ticker == "AAPL"
    assert record.source == "finviz"
    assert record.revenue == pytest.approx(466.82e9)
    assert record.eps == pytest.approx(8.72)
    assert record.gross_margin == pytest.approx(0.4865)
    assert record.operating_margin == pytest.approx(0.3317)
    assert record.roic == pytest.approx(0.7208)
    assert record.roe == pytest.approx(1.4875)
    # Not published directly on the free page — never fabricated.
    assert record.net_debt is None
    assert record.debt_ebitda is None


def test_ambiguous_short_label_disambiguated_by_tooltip():
    """'EPS next Y' is reused for two different values on the real page (dollar estimate vs.
    growth rate) — this adapter must key on the unique tooltip, not the short label, or it would
    silently pick whichever cell happens to match last."""

    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)

    provider = _provider(handler)
    response = provider._client.get("https://finviz.com/quote.ashx?t=AAPL")
    fields = {m.group("tooltip"): m.group("value") for m in _ROW_PATTERN.finditer(response.text)}
    assert "9.54" in fields["EPS estimate for next year"]
    assert "7.98%" in fields["EPS growth next year"]


# -- derived FCF ----------------------------------------------------------------------------------


def test_fcf_derived_from_price_shares_and_price_to_fcf_ratio():
    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)

    record = _provider(handler).get_quarterly_fundamentals("AAPL")[0]
    expected_fcf = 314.81 * 14.61e9 / 33.61
    assert record.fcf == pytest.approx(expected_fcf, rel=1e-6)


def test_fcf_is_none_when_any_input_missing():
    html = _AAPL_QUOTE_HTML.replace(_cell("Current stock price", "Price", "314.81"), "")

    def handler(request):
        return httpx.Response(200, text=html)

    record = _provider(handler).get_quarterly_fundamentals("AAPL")[0]
    assert record.fcf is None


# -- period_end / reported_at convention -----------------------------------------------------


def test_period_end_and_reported_at_are_the_scrape_date_not_a_fiscal_period():
    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)

    record = _provider(handler).get_quarterly_fundamentals("AAPL")[0]
    assert record.period_end == date.today()
    assert record.reported_at == date.today()
    assert record.available_at.date() == date.today()


def test_past_as_of_raises_not_silently_returns_todays_data():
    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)

    with pytest.raises(FinvizError):
        _provider(handler).get_quarterly_fundamentals("AAPL", as_of=date.today() - timedelta(days=30))


# -- get_snapshot -----------------------------------------------------------------------------


def test_get_snapshot_returns_fields_and_charts_from_one_fetch():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=_AAPL_QUOTE_HTML_WITH_CHARTS)

    snapshot = _provider(handler).get_snapshot("aapl")

    assert len(calls) == 1  # one page fetch, not two
    assert snapshot["ticker"] == "AAPL"
    assert snapshot["fields"]["Revenue (ttm)"] == "466.82B"
    assert snapshot["charts"]["eps"]["annual"][-1] == {
        "name": "TTM", "value": 8.72, "isOutlined": True,
    }
    assert snapshot["charts"]["sales"]["annual"][-1]["value"] == 466823
    assert snapshot["charts"]["shares_outstanding"]["annual"][-1]["value"] == 14608.9
    assert snapshot["charts"]["eps"]["quarterly"][0]["name"] == "Q3 '26"


# -- _parse_categories -------------------------------------------------------------------------


def test_parse_categories_equity_form_has_all_five():
    result = _parse_categories(_AAPL_CATEGORIES_HTML)
    assert result == {
        "sector": "Technology", "industry": "Consumer Electronics", "country": "USA",
        "cap_size": "Mega", "exchange": "NASD",
    }


def test_parse_categories_etf_form_omits_cap_size():
    """Confirmed live against SPY/QQQ/VT: ETF pages never carry a cap_ link at all — not blank,
    absent — so cap_size must be missing from the result, not present-with-empty-string."""
    result = _parse_categories(_ETF_CATEGORIES_HTML)
    assert result == {
        "sector": "Financial", "industry": "Exchange Traded Fund", "country": "USA",
        "exchange": "NYSE",
    }
    assert "cap_size" not in result


def test_parse_categories_returns_empty_dict_when_block_absent():
    assert _parse_categories("<html><body>no categories here</body></html>") == {}


def test_get_snapshot_includes_categories():
    html = _AAPL_QUOTE_HTML_WITH_CHARTS.replace(
        "</body></html>", _AAPL_CATEGORIES_HTML + "</body></html>"
    )

    def handler(request):
        return httpx.Response(200, text=html)

    snapshot = _provider(handler).get_snapshot("AAPL")
    assert snapshot["categories"]["sector"] == "Technology"
    assert snapshot["categories"]["industry"] == "Consumer Electronics"


def test_get_snapshot_charts_is_none_when_block_absent():
    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)  # no fa-init-data-0 block

    snapshot = _provider(handler).get_snapshot("AAPL")
    assert snapshot["charts"] is None
    assert snapshot["fields"]  # fields still present


def test_get_snapshot_charts_is_none_on_malformed_json_not_a_crash():
    html = _AAPL_QUOTE_HTML.replace(
        "</body></html>",
        '<script id="fa-init-data-0" type="application/json">{not valid json</script></body></html>',
    )

    def handler(request):
        return httpx.Response(200, text=html)

    snapshot = _provider(handler).get_snapshot("AAPL")
    assert snapshot["charts"] is None


# -- get_current_price ------------------------------------------------------------------------


def test_get_current_price_returns_price_volume_and_observed_at():
    def handler(request):
        return httpx.Response(200, text=_AAPL_QUOTE_HTML)

    before = datetime.now(timezone.utc)
    price, volume, observed_at = _provider(handler).get_current_price("AAPL")
    after = datetime.now(timezone.utc)

    assert price == pytest.approx(314.81)
    assert volume == 17509621
    assert before <= observed_at <= after  # this fetch's own timestamp, not a fixed convention


def test_get_current_price_volume_is_none_when_absent_not_zero():
    html = _AAPL_QUOTE_HTML.replace(_cell("Volume", "Volume", "17,509,621"), "")

    def handler(request):
        return httpx.Response(200, text=html)

    _, volume, _ = _provider(handler).get_current_price("AAPL")
    assert volume is None


def test_get_current_price_raises_when_price_cell_missing():
    html = _AAPL_QUOTE_HTML.replace(_cell("Current stock price", "Price", "314.81"), "")

    def handler(request):
        return httpx.Response(200, text=html)

    with pytest.raises(FinvizResponseError):
        _provider(handler).get_current_price("AAPL")


def test_get_current_price_unknown_ticker_raises_not_found():
    def handler(request):
        return httpx.Response(404, text=_NOT_FOUND_HTML)

    with pytest.raises(FinvizNotFoundError):
        _provider(handler).get_current_price("ZZZZINVALIDTICKER")


# -- errors ----------------------------------------------------------------------------------


def test_unknown_ticker_raises_not_found():
    def handler(request):
        return httpx.Response(404, text=_NOT_FOUND_HTML)

    with pytest.raises(FinvizNotFoundError):
        _provider(handler).get_quarterly_fundamentals("ZZZZINVALIDTICKER")


def test_missing_grid_raises_response_error_not_empty_result():
    def handler(request):
        return httpx.Response(200, text="<html><body>unexpected bot-check page</body></html>")

    with pytest.raises(FinvizResponseError):
        _provider(handler).get_quarterly_fundamentals("AAPL")


def test_http_error_propagates():
    def handler(request):
        return httpx.Response(500, text="internal error")

    with pytest.raises(httpx.HTTPStatusError):
        _provider(handler).get_quarterly_fundamentals("AAPL")


# -- get_price_history -------------------------------------------------------------------------

# Shaped exactly like the real finviz.com/api/quote response (confirmed live 2026-08-20),
# condensed to 3 bars.
_PRICE_API_JSON = {
    "date": [1771009200, 1771095600, 1771182000],
    "open": [100.0, 101.5, 99.0],
    "high": [102.0, 103.0, 101.0],
    "low": [99.5, 100.5, 98.0],
    "close": [101.0, 99.5, 100.5],
    "volume": [1000000, 1200000, 900000],
}


def test_get_price_history_returns_ohlcv_bars_oldest_first():
    def handler(request):
        assert request.url.path == "/api/quote"
        return httpx.Response(200, json=_PRICE_API_JSON)

    bars = _provider(handler).get_price_history("AAPL")

    assert len(bars) == 3
    assert bars[0]["open"] == 100.0
    assert bars[-1]["close"] == 100.5
    assert bars[0]["date"] < bars[-1]["date"]  # oldest first, ISO strings sort chronologically


def test_get_price_history_sends_expected_query_params():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json=_PRICE_API_JSON)

    _provider(handler).get_price_history("AAPL", days=30)

    assert captured["params"]["ticker"] == "AAPL"
    assert captured["params"]["timeframe"] == "d"
    assert captured["params"]["instrument"] == "stock"
    date_from = int(captured["params"]["dateFrom"])
    date_to = int(captured["params"]["dateTo"])
    assert date_to - date_from == pytest.approx(30 * 86400, abs=5)


def test_get_price_history_unknown_ticker_raises_not_found():
    def handler(request):
        return httpx.Response(404, json={"ticker": "ZZZZINVALIDTICKER", "timeframe": "d"})

    with pytest.raises(FinvizNotFoundError):
        _provider(handler).get_price_history("ZZZZINVALIDTICKER")


def test_get_price_history_missing_key_raises_response_error():
    incomplete = dict(_PRICE_API_JSON)
    del incomplete["volume"]

    def handler(request):
        return httpx.Response(200, json=incomplete)

    with pytest.raises(FinvizResponseError):
        _provider(handler).get_price_history("AAPL")


def test_get_price_history_mismatched_lengths_raises_response_error():
    mismatched = dict(_PRICE_API_JSON)
    mismatched["volume"] = mismatched["volume"][:2]

    def handler(request):
        return httpx.Response(200, json=mismatched)

    with pytest.raises(FinvizResponseError):
        _provider(handler).get_price_history("AAPL")


def test_get_price_history_non_json_response_raises_response_error():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(FinvizResponseError):
        _provider(handler).get_price_history("AAPL")


# -- live smoke test (opt-in only) -------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("RUN_FINVIZ_LIVE_TEST"),
    reason="Live scrape against the real finviz.com: SKIPPED by default (ToS caution) — set "
    "RUN_FINVIZ_LIVE_TEST=1 to opt in",
)
def test_live_finviz_fetches_aapl_snapshot():
    with FinvizFundamentalsProvider() as provider:
        records = provider.get_quarterly_fundamentals("AAPL")

    assert len(records) == 1
    record = records[0]
    assert record.ticker == "AAPL"
    assert record.source == "finviz"
    assert record.revenue is not None and record.revenue > 0


@pytest.mark.skipif(
    not os.environ.get("RUN_FINVIZ_LIVE_TEST"),
    reason="Live scrape against the real finviz.com: SKIPPED by default (ToS caution) — set "
    "RUN_FINVIZ_LIVE_TEST=1 to opt in",
)
def test_live_finviz_fetches_aapl_current_price():
    with FinvizFundamentalsProvider() as provider:
        price, volume, observed_at = provider.get_current_price("AAPL")

    assert price > 0
    assert volume is None or volume > 0
    assert observed_at.tzinfo is not None


@pytest.mark.skipif(
    not os.environ.get("RUN_FINVIZ_LIVE_TEST"),
    reason="Live scrape against the real finviz.com: SKIPPED by default (ToS caution) — set "
    "RUN_FINVIZ_LIVE_TEST=1 to opt in",
)
def test_live_finviz_fetches_aapl_price_history():
    with FinvizFundamentalsProvider() as provider:
        bars = provider.get_price_history("AAPL")

    assert len(bars) > 50  # ~190 calendar days should yield well over 50 trading days
    assert bars[0]["date"] < bars[-1]["date"]
    for bar in bars:
        assert bar["low"] <= bar["open"] <= bar["high"]
        assert bar["low"] <= bar["close"] <= bar["high"]
        assert bar["volume"] >= 0
