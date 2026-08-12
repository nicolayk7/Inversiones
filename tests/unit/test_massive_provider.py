"""Massive `MarketDataProvider` adapter — no live network access for the unit tests (httpx
MockTransport builds real httpx.Response objects from canned bodies, so response.json()/
raise_for_status() behave exactly as they would against the real API). One opt-in live test at
the bottom exercises the real endpoint if MASSIVE_API_KEY is set in the environment; it is
skipped otherwise, never required."""

import os
from datetime import date, datetime, timezone

import httpx
import pytest

from packages.providers.market.massive import (
    MassiveAuthError,
    MassiveMarketDataProvider,
    MassiveProviderError,
    MassiveRateLimitError,
    MassiveResponseError,
)

# The exact sample from massive.com's own custom-bars documentation — t is documented to
# represent the start of the 2020-01-02 (ET) trading day's aggregate window.
DOCS_SAMPLE_BAR = {
    "o": 74.06, "h": 75.15, "l": 73.7975, "c": 75.0875, "v": 135647456, "vw": 74.6099,
    "t": 1577941200000, "n": 1,
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _ok_body(results: list[dict]) -> dict:
    return {
        "adjusted": True, "ticker": "AAPL", "queryCount": len(results),
        "resultsCount": len(results), "status": "OK", "request_id": "test", "results": results,
    }


def _provider(handler) -> MassiveMarketDataProvider:
    return MassiveMarketDataProvider(client=_client(handler), api_key="test-key")


# -- Test 1 — valid response maps to OHLCVBar --------------------------------------------------


def test_valid_response_maps_to_ohlcv_bar():
    def handler(request):
        return httpx.Response(200, json=_ok_body([DOCS_SAMPLE_BAR]))

    bars = _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))

    assert len(bars) == 1
    bar = bars[0]
    assert bar.ticker == "AAPL"
    assert bar.ts == date(2020, 1, 2)
    assert bar.open == 74.06
    assert bar.high == 75.15
    assert bar.low == 73.7975
    assert bar.close == 75.0875
    assert bar.volume == 135647456
    assert bar.available_at == datetime(2020, 1, 2, 23, 59, 59, tzinfo=timezone.utc)
    assert bar.source == "massive"


# -- Test 2 — multiple bars ----------------------------------------------------------------


def test_multiple_bars_range_maps_all_entries_in_order():
    entries = [
        {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "t": 1577941200000},  # 2020-01-02
        {"o": 2, "h": 3, "l": 1.5, "c": 2.5, "v": 200, "t": 1578027600000},  # 2020-01-03
        {"o": 3, "h": 4, "l": 2.5, "c": 3.5, "v": 300, "t": 1578114000000},  # 2020-01-04 (Sat)
    ]

    def handler(request):
        return httpx.Response(200, json=_ok_body(entries))

    bars = _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))

    assert len(bars) == 3
    assert [b.close for b in bars] == [1.5, 2.5, 3.5]
    assert [b.ts.isoformat() for b in bars] == ["2020-01-02", "2020-01-03", "2020-01-04"]


# -- Test 3 — empty results is not an error --------------------------------------------------


def test_empty_results_returns_empty_list_not_error():
    def handler(request):
        return httpx.Response(200, json=_ok_body([]))

    bars = _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))
    assert bars == []


# -- Test 4 — HTTP error ---------------------------------------------------------------------


def test_generic_http_error_raises_massive_provider_error():
    def handler(request):
        return httpx.Response(500, json={"status": "ERROR", "error": "internal error"})

    with pytest.raises(MassiveProviderError):
        _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))


# -- Test 5 — authentication error ------------------------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403])
def test_authentication_error_raises_massive_auth_error(status_code):
    def handler(request):
        return httpx.Response(status_code, json={"status": "ERROR"})

    with pytest.raises(MassiveAuthError):
        _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))


def test_missing_api_key_raises_auth_error_before_any_request():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=_ok_body([]))

    with pytest.raises(MassiveAuthError):
        MassiveMarketDataProvider(client=_client(handler), api_key=None)
    assert calls == []  # never even attempted a request


# -- Rate limiting (§7 — "si la API lo expone claramente"; Massive confirms 429) ---------------


def test_rate_limit_error_raises_massive_rate_limit_error():
    def handler(request):
        return httpx.Response(429, json={"status": "ERROR"})

    with pytest.raises(MassiveRateLimitError):
        _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))


# -- Test 6 — malformed response never silently becomes an empty/fabricated result ------------


def test_missing_results_key_raises_not_silently_empty():
    def handler(request):
        return httpx.Response(200, json={"status": "OK"})  # no "results" key at all

    with pytest.raises(MassiveResponseError):
        _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))


def test_non_ok_status_raises_with_message_surfaced():
    def handler(request):
        return httpx.Response(200, json={"status": "ERROR", "error": "unknown ticker"})

    with pytest.raises(MassiveResponseError, match="unknown ticker"):
        _provider(handler).get_daily_bars("NOTATICKER", date(2020, 1, 1), date(2020, 1, 2))


def test_result_entry_missing_required_field_raises_not_fabricated():
    incomplete = dict(DOCS_SAMPLE_BAR)
    del incomplete["c"]  # missing close

    def handler(request):
        return httpx.Response(200, json=_ok_body([incomplete]))

    with pytest.raises(MassiveResponseError, match="c"):
        _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))


def test_non_json_response_raises_massive_response_error():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(MassiveResponseError):
        _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 2))


# -- Test 7 — timestamp/timezone transformation, against the documented sample ----------------


def test_timestamp_maps_to_documented_trading_day():
    """t=1577941200000 is the exact value shown in Massive's own custom-bars.md sample,
    documented there as describing the 2020-01-02 (ET) trading day."""

    def handler(request):
        return httpx.Response(200, json=_ok_body([DOCS_SAMPLE_BAR]))

    bar = _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))[0]
    assert bar.ts == date(2020, 1, 2)


# -- Test 8 (obligatory) — available_at policy is deterministic, explicit, and != ts ----------


def test_available_at_convention_is_deterministic_explicit_and_not_equal_to_ts():
    def handler(request):
        return httpx.Response(200, json=_ok_body([DOCS_SAMPLE_BAR]))

    bar = _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))[0]

    assert bar.ts == date(2020, 1, 2)
    assert bar.available_at == datetime(2020, 1, 2, 23, 59, 59, tzinfo=timezone.utc)
    assert bar.available_at.date() == bar.ts  # same calendar day...
    assert bar.available_at != bar.ts  # ...but never the same value/type — no ts==available_at collapse

    # Determinism: identical input always yields the identical available_at, not a wall-clock-
    # dependent value (e.g. not "now").
    bar2 = _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))[0]
    assert bar2.available_at == bar.available_at


# -- Query parameters sent match the documented contract ---------------------------------------


def test_request_uses_documented_query_parameters():
    captured = {}

    def handler(request):
        captured["params"] = dict(request.url.params)
        captured["path"] = request.url.path
        return httpx.Response(200, json=_ok_body([]))

    _provider(handler).get_daily_bars("AAPL", date(2020, 1, 1), date(2020, 1, 10))

    assert captured["path"] == "/v2/aggs/ticker/AAPL/range/1/day/2020-01-01/2020-01-10"
    assert captured["params"]["adjusted"] == "true"
    assert captured["params"]["sort"] == "asc"
    assert captured["params"]["apiKey"] == "test-key"


# -- Live smoke test (opt-in only) -------------------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("MASSIVE_API_KEY"),
    reason="Live provider test: SKIPPED — credentials unavailable",
)
def test_live_massive_fetches_aapl_bars():
    """Real network call against the real Massive API — only runs if MASSIVE_API_KEY is set.
    Adapter -> OHLCVBar only: no Storage, no Wealth Engine, nothing persisted."""
    with MassiveMarketDataProvider() as provider:
        bars = provider.get_daily_bars("AAPL", date(2024, 1, 2), date(2024, 1, 5))

    assert isinstance(bars, list)
    assert len(bars) > 0
    for bar in bars:
        assert bar.ticker == "AAPL"
        assert bar.source == "massive"
        assert bar.available_at > datetime.combine(bar.ts, datetime.min.time(), tzinfo=timezone.utc)
