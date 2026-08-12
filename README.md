# Investment Intelligence

A decision-support platform for wealth and trading analysis — not a chatbot. Deterministic
calculation lives in code (Quant Core); the LLM is used only for reasoning, synthesis, and
qualitative interpretation over numbers that code already computed.

Architecture is frozen at **v1.0** (approved 2026-08-10). See `CLAUDE.md` for the rules every
change in this repo must respect. This README covers running what exists today.

## Status: Phase 0 — Foundation

What's implemented: project scaffolding, config, logging, the frozen `v1.0` score weights,
provider interfaces (contracts only, no concrete providers), a Quant Core skeleton (SMA/EMA real,
everything else stubbed), Docker Compose for Postgres/TimescaleDB/pgvector + Redis, and a FastAPI
app with a single `/health` endpoint.

Not implemented yet: Wealth/Trading/Risk/Options/Opportunity/Backtest engines, the six LLM agents,
WhatsApp, and the dashboard. Those land in later phases, each requiring separate approval.

## Prerequisites

- Python 3.13+
- Docker Desktop (with Docker Compose)

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

copy .env.example .env          # adjust if needed — defaults work with infra/docker-compose.yml
```

## Run the infrastructure

```bash
docker compose -f infra/docker-compose.yml up -d
```

This starts Postgres/TimescaleDB (with `timescaledb` and `vector` extensions) on **host port
5433** and Redis on **host port 6380** — not the standard 5432/6379, because this machine already
runs an unrelated Postgres/Redis stack on those ports. See `infra/docker-compose.yml` for details.

## Run the API

```bash
uvicorn apps.api.main:app --reload
```

Then check `GET http://localhost:8000/health` — it reports the status of the database, Redis, and
the frozen weights file.

## Tests

```bash
pytest                 # unit tests only (default — no infra required)
pytest -m integration  # requires the docker compose stack to be up
```

## Project layout

```
apps/api/          FastAPI app — the only HTTP boundary
packages/quant_core/ deterministic calculation — no I/O, no LLM
packages/providers/  data provider interfaces (9) + implementations, per-domain
packages/engines/    Wealth / Trading / Risk / Options Intelligence / Opportunity / Macro / Backtest
packages/agents/     the 6 LLM agents (not implemented in Phase 0)
packages/storage/    SQLAlchemy engine/session, declarative Base
packages/shared/     config, logging, point-in-time/provenance primitives, weights loader
config/weights/      frozen, versioned score weights (v1.0 — see CLAUDE.md)
infra/               docker-compose.yml, Postgres init SQL
tests/unit/          fast, no external services
tests/integration/   requires docker compose up
```

## Weights

Score weights are static YAML, not agent output — `config/weights/v1.0.yaml`, loaded via
`packages.shared.weights.load_weights()`. Changing a weight means adding `v1.1.yaml` and bumping
`WEIGHTS_VERSION`, never editing a frozen version file in place.
