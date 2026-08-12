"""Orchestrator boundary: API -> this module -> Storage -> Quant Core -> Wealth Engine. The API
router calls only `get_wealth_snapshot`, never storage or Quant Core directly (CLAUDE.md's API
boundary rule — routers call engines/agents, never the reverse, and never SEC EDGAR)."""

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from packages.engines.wealth_engine.data_ingestion import build_wealth_engine_input_from_storage
from packages.engines.wealth_engine.output_contract import WealthEngineOutput
from packages.engines.wealth_engine.pipeline import compute_wealth_snapshot
from packages.quant_core.regime import SectorProfile


async def get_wealth_snapshot(
    ticker: str,
    as_of: date,
    session: AsyncSession,
    *,
    sector: SectorProfile = SectorProfile.GENERIC_INDUSTRIAL,
    price: float | None = None,
    allow_provisional: bool | None = None,
) -> WealthEngineOutput:
    """Storage-backed read path only. Raises `ValueError` (mapped to HTTP 404 by the router) when
    no statements are in storage for `ticker` as of `as_of` — this never falls back to a live
    provider; populate storage first via `data_ingestion.ingest_fundamentals`."""
    inp = await build_wealth_engine_input_from_storage(ticker, sector, as_of, session, price=price)
    return compute_wealth_snapshot(inp, allow_provisional=allow_provisional)
