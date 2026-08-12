"""The nine provider interfaces must exist as Protocols with the expected methods, and their
DTOs must carry point-in-time fields — this is what makes §04's "no engine calls a provider
directly, no backtest can look ahead" promise checkable in CI instead of just documented."""

import inspect

from packages.providers import base
from packages.shared.schemas import FundamentalsRecord, OHLCVBar

EXPECTED_PROVIDERS = {
    "MarketDataProvider": "get_daily_bars",
    "FundamentalsProvider": "get_quarterly_fundamentals",
    "OptionsProvider": "get_chain",
    "MacroProvider": "get_series",
    "NewsProvider": "get_news",
    "CorporateActionsProvider": "get_actions",
    "EconomicCalendarProvider": "get_upcoming_events",
    "FilingsProvider": "get_filings",
    "AnalystEstimatesProvider": "get_estimates",
}


def test_all_nine_interfaces_are_defined():
    for name in EXPECTED_PROVIDERS:
        assert hasattr(base, name), f"missing provider interface: {name}"


def test_each_interface_is_a_protocol_with_its_method():
    for name, method in EXPECTED_PROVIDERS.items():
        cls = getattr(base, name)
        assert getattr(cls, "_is_protocol", False), f"{name} must be a typing.Protocol"
        assert hasattr(cls, method), f"{name} must declare {method}()"


def test_point_in_time_sensitive_providers_accept_as_of():
    point_in_time_sensitive = [
        "FundamentalsProvider",
        "OptionsProvider",
        "MacroProvider",
        "FilingsProvider",
        "AnalystEstimatesProvider",
    ]
    for name in point_in_time_sensitive:
        cls = getattr(base, name)
        method = getattr(cls, EXPECTED_PROVIDERS[name])
        params = inspect.signature(method).parameters
        assert "as_of" in params, f"{name}.{EXPECTED_PROVIDERS[name]} must accept as_of for backtest safety"


def test_ohlcv_bar_constructs():
    bar = OHLCVBar(
        ticker="AAPL", ts="2026-01-05", open=1, high=2, low=0.5, close=1.5, volume=1000,
        available_at="2026-01-05T21:00:00Z", source="test",
    )
    assert bar.ticker == "AAPL"


def test_ohlcv_bar_available_at_is_not_assumed_equal_to_ts():
    """Market Data Foundation Phase 1 decision: ts (trading day) and available_at (publication
    vintage) are independent fields — a bar reported well after the trading day it describes must
    be representable, not silently collapsed to ts."""
    bar = OHLCVBar(
        ticker="AAPL", ts="2026-01-05", open=1, high=2, low=0.5, close=1.5, volume=1000,
        available_at="2026-01-07T21:00:00Z", source="test",
    )
    assert bar.ts.isoformat() == "2026-01-05"
    assert bar.available_at.date().isoformat() == "2026-01-07"


def test_fundamentals_record_carries_point_in_time_fields():
    record = FundamentalsRecord(
        ticker="AAPL",
        period_end="2025-06-30",
        reported_at="2025-08-01",
        available_at="2025-08-01T20:00:00Z",
        source="test",
    )
    assert record.period_end.isoformat() == "2025-06-30"
    assert record.reported_at.isoformat() == "2025-08-01"
