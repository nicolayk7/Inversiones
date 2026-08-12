"""SQLAlchemy table for the canonical daily-bar DTO (`packages.shared.schemas.OHLCVBar`).

Same pattern as `packages.storage.models.fundamentals`, adapted to price's shape: there is no
`period_end`/`reported_at` pair here (no separate "period described" vs "publication date"
concept for a daily bar) — the analogous pair is `ts` (the trading day the bar describes) and
`available_at` (when this system could have known that day's bar). See `OHLCVBar`'s docstring:
the two are never assumed equal.

Uniqueness / point-in-time design mirrors fundamentals exactly:

- A surrogate `id` primary key, plus a `(ticker, ts, source, available_at)` unique constraint.
  `available_at` is part of the key deliberately, same reasoning as fundamentals' `reported_at`:
  a corrected/revised print of the same trading day's bar from the same source must land as a new
  row with its own (later) `available_at`, never silently overwrite the original — history stays
  append-only so `available_at <= as_of` retrieval can reconstruct what was knowable at any past
  moment.
- `(ticker, ts, available_at)` index — the point-in-time retrieval shape.
- `(ticker, available_at)` index — "everything knowable for this ticker as of X."
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from packages.storage.base import Base


class PriceBarModel(Base):
    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("ticker", "ts", "source", "available_at", name="uq_price_bar_vintage"),
        Index("ix_price_bars_ticker_ts_available", "ticker", "ts", "available_at"),
        Index("ix_price_bars_ticker_available", "ticker", "available_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False)
    ts: Mapped[date] = mapped_column(Date, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
