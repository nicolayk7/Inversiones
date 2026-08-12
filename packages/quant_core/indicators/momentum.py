"""RSI / MACD — signatures reserved now, implemented with Trading Engine
depth in Phase 1. Stubbed rather than omitted so callers can be written
against a stable API before the math lands."""

import pandas as pd


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    raise NotImplementedError("rsi() lands with Trading Engine — Phase 1")


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    raise NotImplementedError("macd() lands with Trading Engine — Phase 1")
