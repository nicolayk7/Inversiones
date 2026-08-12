"""Simple and exponential moving averages. Pure functions over pandas Series —
no I/O, no LLM (architecture v1.0, rule 16)."""

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    """Simple moving average over `window` periods."""
    if window < 1:
        raise ValueError("window must be >= 1")
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average with the given span."""
    if span < 1:
        raise ValueError("span must be >= 1")
    return series.ewm(span=span, adjust=False).mean()
