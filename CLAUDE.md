# CLAUDE.md

Architectural rules for working in this repo. Architecture is **frozen at v1.0** (approved
2026-08-10). These rules are not stylistic preferences — they encode decisions that were made
deliberately and reviewed section by section. Do not deviate from them without the user
explicitly reopening the decision.

## What this system is

Investment Intelligence is a decision-support platform for wealth and trading analysis — **not a
chatbot**. Every number shown to the user was computed by deterministic code. The LLM is used
only for reasoning, synthesis, interpretation, qualitative analysis, and hypothesis generation
over numbers that code already produced. An agent that "helpfully" estimates a score or rounds a
number instead of reading it from Quant Core has broken the architecture, even if the estimate is
correct.

## The one rule everything else follows from

```
DATA → CALCULATION → ANALYSIS → SIGNAL → OPPORTUNITY → RISK → DECISION SUPPORT
```

Each arrow is a real module boundary, not a naming convention:

- **Wealth Engine** answers "what should I own?" — long-horizon quality/growth/moat/valuation.
- **Trading Engine** answers "what tactical opportunity exists?" — technicals/momentum/catalysts.
- **Options Intelligence** is its own box, not a Trading Engine submodule. v1 scope is Long Call /
  Long Put / Debit Spread only — do not add more strategies without the user approving that scope
  change first.
- **Opportunity Engine** ranks candidates by combining Wealth + Trading + Options scores and
  regime multipliers. It is **pure code — no LLM**, and it never decides in isolation: every
  ranked row carries the Risk Engine's verdict before it reaches the user.
- **Risk Engine** is independent of the other three. It can block or resize any candidate from
  any engine. **Risk is a gate, not a weighted input** — it is deliberately absent from
  `config/weights/*.yaml`'s `opportunity` section. Never add it there.
- **Macro Intelligence** (Macro/Market Regime + Economic Calendar) is a shared layer consumed by
  Wealth and Trading — not a fourth competing engine.
- **Backtest Engine** reuses Quant Core exactly, offline, filtered by `available_at`. It is the
  only caller allowed to query historical data with a point-in-time cutoff.
- **Visual Intelligence** is a Decision Support output, not an afterthought — see the dedicated
  section below. It ships in the MVP as a structured object, before any UI exists.

Wealth, Trading, and Risk stay **strictly separated** — none depends on another's internals, only
on its published scores.

## Weights are frozen config, not agent output

`config/weights/v1.0.yaml` holds the wealth/trading/options/opportunity weights approved in the
freeze. Load them via `packages.shared.weights.load_weights()` — never hardcode a weight inline,
never let an agent generate or adjust one at runtime. To change a weight: add a new version file
(`v1.1.yaml`) and bump `WEIGHTS_VERSION`; never edit a frozen version file in place. Every
persisted score should record which `weights_version` produced it.

Current frozen weights (v1.0):

| Wealth | | Trading | | Options | | Opportunity | |
|---|---|---|---|---|---|---|---|
| Quality | 25% | Trend | 25% | IV / IV Rank | 20% | Wealth | 30% |
| Growth | 25% | Momentum | 20% | Expected Move | 15% | Trading | 30% |
| FCF | 15% | Technical | 20% | Liquidity | 20% | Options | 15% |
| Moat | 15% | Catalyst | 15% | Greeks | 15% | Macro | 10% |
| Valuation | 20% | Relative Strength | 10% | Risk/Reward | 20% | Regime | 15% |
| | | Market Regime | 10% | Term Structure | 10% | | |

## Data providers

Nine interfaces in `packages/providers/base.py`: `MarketDataProvider`, `FundamentalsProvider`,
`OptionsProvider`, `MacroProvider`, `NewsProvider`, `CorporateActionsProvider`,
`EconomicCalendarProvider`, `FilingsProvider`, `AnalystEstimatesProvider`. **Engines and agents
call these interfaces, never a concrete SDK directly.** Swapping the options data tier from
EOD-only (MVP) to delayed/real-time (Phase 2 candidate) must not require touching Options
Intelligence.

Options data is **EOD-only for the MVP, $0 cost** — deliberately more conservative than the
original "delayed" recommendation. Do not silently upgrade this to real-time; it's a scoped
Phase 2 decision.

## Point-in-time correctness (non-negotiable)

Any data with a temporal dimension distinguishes three things, never two:

- `period_end` — what period the value describes.
- `reported_at` — when the source published it.
- `available_at` — when *this system* could have known it. This is the **only** field the
  Backtest Engine is allowed to filter on.

General provenance (`packages/shared/point_in_time.py::ProvenanceFields`) additionally tracks
`source`, `observed_at`, `effective_at`, `ingested_at`, and `raw_payload` where relevant.

Backtesting must prevent, by construction, not by discipline: **look-ahead bias**, **survivorship
bias**, **data leakage**, and **use of fundamentals before their real-world publication date**.
The MVP universe (`universe_definition`, versioned) exists specifically to avoid survivorship
bias — never substitute "current index membership" as a shortcut.

Macro series use first-publication vintage only in the MVP (`available_at` = first release date).
Full ALFRED revision history is Phase 3 scope — do not add it earlier without approval.

## Visual Intelligence v1 (MVP component — not Phase 2/3)

Every piece of Decision Support output the system produces answers four questions, not just "what
is the score":

```
WHAT CHANGED?
WHY IT MATTERS?
WHAT COULD HAPPEN?
WHAT INVALIDATES THE THESIS?
```

This ships in the MVP as a **structured object returned by the API** (e.g.
`GET /v1/thesis/{ticker}/changes`) — not as a dashboard or any visual UI. A chart-based/visual
dashboard consuming this same structured output is Phase 2+ (read-only) and Phase 3 (full); the
underlying four-question object is not deferred and must not be treated as a "nice to have" cut
from the MVP.

## Equity Universe vs. Market Context

Two lists exist and they never merge:

- **Equity Universe** — ~30 equities, curated and versioned as `universe v1`. This is what Wealth
  Engine ranks and what Opportunity Engine surfaces as candidates.
- **Market Context** — SPY, QQQ, IWM, DIA, VIX, 2Y, 10Y, DXY, WTI/Oil, Gold, and similar
  macro/breadth instruments. These feed Macro Intelligence, Market Regime, Trading Engine, and
  Risk Engine as **context inputs** — they are never scored, ranked, or shown as equity candidates
  inside the Wealth ranking.

Concretely: SPY does not get a Wealth Score. It gets used to classify the current Market Regime,
which then multiplies other instruments' scores. Mixing the two lists — e.g. letting a
Market Context instrument compete for a slot in `opportunity_rankings` as if it were a normal
equity — is a bug, not a feature, however tempting it looks when wiring up Wealth Engine.

## Agents (6, and only these 6)

`Intent Router`, `Wealth Analyst`, `Trading Analyst`, `Options Strategist`, `Macro Analyst`,
`Narrative Synthesizer`. Agents are thin wrappers over already-computed results — if a task can be
solved with deterministic code, it belongs in `packages/quant_core`, not in a new agent. Do not
add a 7th agent without the user approving the scope change; prefer extending one of the six.

## Stack (do not add to this without justifying it first — rule 23 of the freeze)

Python 3.13, FastAPI, Pydantic v2, PostgreSQL, TimescaleDB, pgvector, Redis, Quant Core (pandas /
numpy), Anthropic SDK, Docker Compose. Monolito modular — **no microservices**. Router propio for
agent orchestration — **no LangGraph** unless the user reopens that decision.

## Project structure

```
apps/api/            FastAPI — the only HTTP boundary; routers call engines/agents, never reverse
packages/quant_core/  deterministic calculation — no I/O, no LLM, ever
packages/providers/   the 9 interfaces (base.py) + per-domain implementations
packages/engines/     Wealth / Trading / Risk / Options Intelligence / Opportunity / Macro / Backtest
packages/agents/      the 6 LLM agents
packages/storage/     SQLAlchemy engine/session/Base — models land per-engine, not speculatively
packages/shared/      config, logging, point-in-time/provenance, weights loader
config/weights/       frozen, versioned weight files
infra/                docker-compose.yml + Postgres init SQL
tests/unit/           fast, no external services (pytest default)
tests/integration/    requires `docker compose -f infra/docker-compose.yml up` (pytest -m integration)
```

Local dev ports are **5433** (Postgres) and **6380** (Redis), not the 5432/6379 defaults — this
machine already runs an unrelated Postgres/Redis stack on the standard ports. Don't "fix" this
back to the defaults.

## Local dev credentials

`infra/docker-compose.yml` (`POSTGRES_PASSWORD: ii`) and `packages/shared/config.py`'s defaults
(`ii:ii`, `API_KEY=dev-local-key`) are **local/dev-only conveniences, not production secrets**:

- Not acceptable for any shared, staging, or production environment.
- Production secrets must come from a secrets manager or the deployment platform's secure
  environment config — never a default value baked into source.
- Never let a real credential enter this repository, including in `.env` (already gitignored) or
  in commit messages/PR descriptions.

Do not "fix" these defaults away in Phase 0/1 — they're intentionally weak because nothing today
is internet-facing or holds real data. Revisit when Phase 3 introduces cloud hosting.

## Phase gating

Work proceeds in small, explicitly approved phases. **Phase 0 (foundation) is complete.** Do not
start implementing Wealth Engine, Trading Engine, Risk Engine, Options Intelligence, Opportunity
Engine, Backtest Engine, Visual Intelligence, any of the 6 agents, WhatsApp, or the dashboard
without the user explicitly approving that phase first — this repo's history is a sequence of
small, verifiable steps by design, not a single large build.

Explicitly out of scope until later phases: real portfolio tracking (Phase 2 paper, Phase 3 real),
multi-user support (Phase 3), WhatsApp (Phase 3, and always `WhatsApp → webhook → API →
Intelligence Engine` — **never** WhatsApp directly to an agent), the visual dashboard (Phase 2+
read-only, Phase 3 full).
