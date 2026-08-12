"""Wealth Engine HTTP boundary. `POST /v1/wealth/compute` takes `{ticker, as_of}` and reads
already-ingested, point-in-time fundamentals from storage — the API never talks to SEC EDGAR
directly (CLAUDE.md's API boundary rule; architecture v1.0 §04's Provider -> Normalization ->
Storage -> Quant Core -> Engines direction). Routers call the Wealth service/orchestrator only:
API -> `packages.engines.wealth_engine.service.get_wealth_snapshot` -> Storage -> Quant Core ->
Wealth Engine.

Ingestion (Provider -> Storage) is a separate concern, not exposed over HTTP in this pass — see
`packages.engines.wealth_engine.data_ingestion.ingest_fundamentals`. A refresh/scheduling policy
for when to (re-)ingest is undecided and out of scope here."""

import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from packages.engines.wealth_engine.output_contract import WealthEngineOutput
from packages.engines.wealth_engine.service import get_wealth_snapshot
from packages.quant_core.regime import SectorProfile
from packages.shared.component_weights import ProvisionalWeightsRejectedError
from packages.shared.open_parameters import ProvisionalOpenParametersRejectedError
from packages.storage.db import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/wealth", tags=["wealth"])


class WealthComputeRequest(BaseModel):
    ticker: str
    as_of: date
    # No Equity Universe / ticker->sector mapping exists yet (methodology §23 is still open,
    # CLAUDE.md's Equity Universe vs. Market Context split) — the caller supplies it explicitly.
    # Defaults to the no-special-treatment profile already used by every test in this vertical.
    sector: SectorProfile = SectorProfile.GENERIC_INDUSTRIAL


@router.post("/compute", response_model=WealthEngineOutput)
async def compute(payload: WealthComputeRequest) -> WealthEngineOutput:
    try:
        async with SessionLocal() as session:
            return await get_wealth_snapshot(payload.ticker, payload.as_of, session, sector=payload.sector)
    except (ProvisionalWeightsRejectedError, ProvisionalOpenParametersRejectedError) as exc:
        # Production configuration correctly rejecting PROVISIONAL config (rule 6) — a client
        # error (config state), not a server error.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        # build_wealth_engine_input_from_storage: nothing in storage for ticker/as_of yet.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
