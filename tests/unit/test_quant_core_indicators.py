"""The only Quant Core math actually implemented in Phase 0 — SMA/EMA — proving the
pattern (deterministic, pure, no I/O) compiles and is correct."""

import pandas as pd
import pytest

from packages.quant_core.indicators import ema, macd, rsi, sma


def test_sma_basic():
    series = pd.Series([1, 2, 3, 4, 5])
    result = sma(series, window=3)
    assert result.iloc[-1] == pytest.approx(4.0)
    assert result.iloc[:2].isna().all()


def test_sma_rejects_invalid_window():
    with pytest.raises(ValueError):
        sma(pd.Series([1, 2, 3]), window=0)


def test_ema_basic():
    series = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = ema(series, span=3)
    assert result.iloc[0] == pytest.approx(1.0)
    assert result.is_monotonic_increasing


def test_rsi_is_stubbed_not_silently_wrong():
    with pytest.raises(NotImplementedError):
        rsi(pd.Series([1, 2, 3]))


def test_macd_is_stubbed_not_silently_wrong():
    with pytest.raises(NotImplementedError):
        macd(pd.Series([1, 2, 3]))
