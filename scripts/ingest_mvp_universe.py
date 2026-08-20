"""Operator-facing MVP ingestion script (MVP-0). Not a general orchestration framework — a plain
sequential script, same ingestion functions `tests/integration/test_wealth_engine_live_aapl.py`
already exercises, just runnable from a terminal instead of pytest.

Sequence per ticker: fundamentals -> quarterly revenue -> price. Price is best-effort: if
MASSIVE_API_KEY isn't configured, that step is skipped with a warning (not a failure) and
Valuation stays N/A for that ticker downstream, exactly like every other missing-data case in
this codebase.

MVP_TICKERS is an explicit, small, hand-picked set for this MVP — deliberately NOT the frozen,
still-undefined "Universe v1" (methodology §23, CLAUDE.md's Equity Universe vs. Market Context
split). Do not rename this to "universe" anywhere.

Usage:
    python scripts/ingest_mvp_universe.py                  # ingest all of MVP_TICKERS
    python scripts/ingest_mvp_universe.py AAPL MSFT         # ingest a subset
"""

import asyncio
import logging
import sys
from datetime import date, timedelta

from packages.engines.wealth_engine import data_ingestion
from packages.providers.market.massive import MassiveAuthError
from packages.storage.db import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ingest_mvp_universe")

# Verified live against SEC EDGAR (CIK + anchor revenue concept + fiscal/quarterly span coverage)
# before being added to packages/providers/fundamentals/sec_edgar.py::TICKER_TO_CIK.
MVP_TICKERS = ["AAPL", "MSFT", "AMZN", "GOOGL"]

# Price ingestion window: wide enough to survive weekends/holidays and land at least one real
# trading day, narrow enough to stay a cheap, fast call. Not a PIT decision — get_price_as_of's
# own available_at <= as_of filtering is what actually enforces point-in-time correctness at read
# time; this window only decides how far back to fetch bars from.
_PRICE_LOOKBACK_DAYS = 14


async def _ingest_one(ticker: str) -> None:
    logger.info("[%s] ingesting fundamentals (annual)...", ticker)
    async with SessionLocal() as session:
        await data_ingestion.ingest_fundamentals(ticker, session)
    logger.info("[%s] fundamentals ingested.", ticker)

    logger.info("[%s] ingesting quarterly revenue...", ticker)
    async with SessionLocal() as session:
        await data_ingestion.ingest_quarterly_revenue(ticker, session)
    logger.info("[%s] quarterly revenue ingested.", ticker)

    end = date.today()
    start = end - timedelta(days=_PRICE_LOOKBACK_DAYS)
    try:
        logger.info("[%s] ingesting price [%s, %s]...", ticker, start, end)
        async with SessionLocal() as session:
            await data_ingestion.ingest_price(ticker, start, end, session)
        logger.info("[%s] price ingested.", ticker)
    except MassiveAuthError:
        logger.warning(
            "[%s] MASSIVE_API_KEY not configured — skipping price ingestion. "
            "Valuation will be N/A for this ticker until a price is available.",
            ticker,
        )


async def main(tickers: list[str]) -> None:
    logger.info("Ingesting %d ticker(s): %s", len(tickers), tickers)
    results: dict[str, str] = {}
    for ticker in tickers:
        try:
            await _ingest_one(ticker)
            results[ticker] = "ok"
        except Exception as exc:  # noqa: BLE001 — one ticker's failure must not abort the batch
            logger.exception("[%s] ingestion failed", ticker)
            results[ticker] = f"failed: {exc}"

    logger.info("Summary:")
    for ticker, status in results.items():
        logger.info("  %s: %s", ticker, status)


if __name__ == "__main__":
    requested = sys.argv[1:] or MVP_TICKERS
    unknown = [t for t in requested if t.upper() not in MVP_TICKERS]
    if unknown:
        logger.error("Not in MVP_TICKERS (extend TICKER_TO_CIK first): %s", unknown)
        sys.exit(1)
    asyncio.run(main([t.upper() for t in requested]))
