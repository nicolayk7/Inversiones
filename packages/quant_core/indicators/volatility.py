"""ATR / ADX / Bollinger Bands — stubbed, land with Trading Engine depth in
Phase 1."""

import pandas as pd


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    raise NotImplementedError("atr() lands with Trading Engine — Phase 1")


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    raise NotImplementedError("adx() lands with Trading Engine — Phase 1")


def bollinger_bands(
    series: pd.Series, window: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    raise NotImplementedError("bollinger_bands() lands with Trading Engine — Phase 1")
