"""§10.1's mixed-cadence `available_at <= as_of` invariant, applied via
`packages.quant_core.backtest.latest_eligible` — the no-look-ahead guarantee for combining
different-cadence inputs (e.g. market_cap = price x diluted shares)."""

from datetime import datetime

import pytest

from packages.quant_core.backtest import latest_eligible


class _Record:
    def __init__(self, value, available_at):
        self.value = value
        self.available_at = available_at


def test_latest_eligible_picks_latest_available_at_not_exceeding_as_of():
    records = [
        _Record(1, datetime(2025, 1, 1)),
        _Record(2, datetime(2025, 3, 1)),
        _Record(3, datetime(2025, 6, 1)),  # not yet knowable as of the as_of below
    ]
    result = latest_eligible(records, as_of=datetime(2025, 4, 1), key=lambda r: r.available_at)
    assert result.value == 2  # NOT 3 — no look-ahead


def test_latest_eligible_returns_none_when_nothing_eligible():
    records = [_Record(1, datetime(2025, 6, 1))]
    result = latest_eligible(records, as_of=datetime(2025, 1, 1), key=lambda r: r.available_at)
    assert result is None


def test_latest_eligible_does_not_use_globally_latest_value():
    """The exact bug this invariant exists to prevent: never substitute 'latest database value'
    when an earlier one was the only thing actually knowable as_of the query date."""
    records = [_Record("old", datetime(2024, 1, 1)), _Record("newest", datetime(2026, 1, 1))]
    result = latest_eligible(records, as_of=datetime(2025, 1, 1), key=lambda r: r.available_at)
    assert result.value == "old"


def test_as_of_filter_remains_a_documented_phase1_stub():
    from packages.quant_core.backtest import as_of_filter

    with pytest.raises(NotImplementedError):
        as_of_filter("available_at", datetime(2025, 1, 1))
