"""Finviz `FundamentalsProvider` (partial) mapping tests — no live network access (httpx
MockTransport builds real httpx.Response objects from a canned HTML fixture shaped exactly like
finviz.com/quote.ashx's real markup, confirmed live during development — see finviz.py's module
docstring). One opt-in live test at the bottom hits the real page; skipped unless
RUN_FINVIZ_LIVE_TEST=1 is set, per this provider's own ToS-caution disclosure (no bulk/CI-default
live hits against a source with no explicit scraping allowance)."""

import os
from datetime import date, timedelta

import httpx
import pytest

from packages.providers.fundamentals.finviz import (
    _ROW_PATTERN,
    FinvizError,
    FinvizFundamentalsProvider,
    FinvizNotFoundError,
    FinvizResponseError,
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
{_cell("EPS estimate for next year", "EPS next Y", "9.54")}
{_cell("EPS growth next year", "EPS next Y", "7.98%")}
{_cell("Debt/Eq ratio placeholder", "Some N/A Field", "-")}
</tr>
</tbody></table>
</body></html>
"""

_NOT_FOUND_HTML = "<html><body><h1>Ticker not found</h1></body></html>"


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
