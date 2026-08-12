# Wealth Engine — Phase 1B Implementation Specification

> **STATUS: DESIGN ONLY — REQUIRES HUMAN APPROVAL BEFORE CODING.**
> Baseline: [`docs/wealth-engine-methodology.md`](./wealth-engine-methodology.md), Rev. 4,
> **approved as the Phase 1A methodology baseline**. This document is the bridge between that
> approved methodology and actual code — module boundaries, data contracts, and test/fixture
> strategy — but **contains no implementation**. No Python file, schema, weights file, or
> dependency has been touched to produce this document.

---

## 0. Scope, binding constraints, and how they're enforced in this design

Phase 1A approval carried twelve mandatory principles for Phase 1B. This section states each one
and how the design below enforces it, so the constraint isn't just a preamble — it's traceable to
a specific structural decision.

| # | Principle | Enforced by |
|---|---|---|
| 1 | No top-level weight changes | §5 — `WEALTH_SCORE_RAW` reads `config/weights/v1.0.yaml` verbatim via the existing `load_weights()`; no new top-level group is added |
| 2 | No invented OPEN parameters | §14 — every illustrative number is sourced from a named, versioned config constant carried over unchanged from §26's Category B ledger; none is assigned a "final" value here |
| 3 | No implementation of BLOCKED methodology | §15 — every Category C item is explicitly stubbed, `UNSUPPORTED`, or absent, never approximated |
| 4 | Banks/Insurance → `WEALTH_SCORE = N/A` | §8 — sector gate is enforced at the composition layer, not left to a caller to remember |
| 5 | Diagnostics may exist without a Wealth Score | §8 — `VALUATION_SCORE` is computable and returned independently of `WEALTH_SCORE`'s N/A state |
| 6 | H4 mechanism approved, `+2pp` threshold OPEN | §4, §14 — the flag's detection logic is implemented; its threshold is a Category B config constant |
| 7 | OPEN parameters stay configurable, never silently hardcoded | §14 — single named config surface, every entry tagged `status: OPEN` |
| 8 | Deterministic, reproducible | §1, §12 — `packages/quant_core` stays I/O-free and side-effect-free by construction; golden-snapshot + reproducibility tests enforce it |
| 9 | LLMs never calculate ratios or modify weights | §0.1, §15 — no agent is invoked anywhere in this spec's scope |
| 10 | Point-in-time correctness mandatory | §10 — reuses Phase 0's `ProvenanceFields`/`available_at` filter exclusively, no new primitive |
| 11 | No agents, no other engines, no later phases | §0.1 — explicit non-goals |
| 12 | Visual Intelligence stays a structured object, no dashboard | §11 — only the deterministic `what_changed` diff is in scope; narrative fields are deferred |

### 0.1 Non-goals for Phase 1B (explicit)

Per principle 11, the following are **not** designed or built in this phase, regardless of their
approval status in the methodology's decision log:

- **Any of the 6 agents** — including the Wealth Analyst's Moat/Management structured-rating
  pathway (§8/§9 of the methodology) and the Thesis Engine (§18). This is a scope boundary from
  this approval message, independent of §8's own "REQUIRES HUMAN APPROVAL" status for the
  LLM-aggregation exception — even if that exception were ratified separately, no agent is invoked
  in Phase 1B.
- Trading Engine, Risk Engine, Options Intelligence, Opportunity Engine, Macro Intelligence,
  Backtest Engine's own orchestration (only its **existing** point-in-time query helper is reused,
  not extended).
- The `/v1/thesis/{ticker}/changes` narrative fields (`why_it_matters`, `what_could_happen`) —
  these require the Wealth Analyst agent. The deterministic `what_changed` diff does not, and is
  in scope (§11).
- WhatsApp, the dashboard, any UI.

### 0.2 Critical path dependency — read this before §5

**The approved methodology has a structural gap that blocks computing any top-level component
score for a real ticker, and this spec does not resolve it.** `QUALITY_SCORE`, `GROWTH_SCORE`,
`FCF_SCORE`, and `VALUATION_SCORE` are each defined as a *weighted* combination of several
sub-metrics (§14 of the methodology, e.g. `QUALITY_SCORE = weighted(ROIC_spread, ROE, ROA,
GrossMargin, ...)`), but **no sub-metric weight config exists or is approved** — decision log
item #4 / Category C: *"New config surface for sub-metric weights within each group... Real
architectural fork... REQUIRES HUMAN APPROVAL."* This is separate from, and does not overlap with,
the five frozen **top-level** weights in `config/weights/v1.0.yaml` (Quality 25% / Growth 25% /
FCF 15% / Moat 15% / Valuation 20%), which *are* approved and unaffected.

Concretely: Phase 1B can compute and persist every normalized 0–100 **sub-metric** (ROIC spread,
gross margin percentile, revenue growth percentile, etc. — §3 of this doc) deterministically and
testably. It **cannot** compute `QUALITY_SCORE` itself as a single number for a real ticker,
because there is no approved way to weight ROIC vs. Gross Margin vs. Margin Stability against each
other inside that composite. The same blocks `GROWTH_SCORE`, `FCF_SCORE`, `VALUATION_SCORE`, and
therefore `WEALTH_SCORE_RAW`, `business_quality_composite`, and `valuation_quadrant` — all of which
depend on at least one blocked component score.

**Human decision, this round: the sub-metric weighting *architecture* is now APPROVED; the
*values* remain BLOCKED.** This narrows, but does not close, the blocker. Two previously-conflated
questions are now separated:

- **Architecture (config location/schema) — APPROVED.** Sub-metric weighting is approved as a
  mechanism that must be able to accept an **explicit, versioned weight set** without any
  production value embedded in code. Concretely, this mirrors the existing frozen top-level
  pattern (`packages/shared/weights.py::WeightsSet`/`load_weights()`) rather than inventing a new
  one: a parallel `ComponentWeightsSet`/`load_component_weights(group, version)` loader, reading
  from a per-group file under `config/weights/wealth_components/{group}_v{version}.yaml` (e.g.
  `quality_v1.0.yaml`), each holding `{sub_metric_name: weight}` pairs that must sum to 1.0,
  validated the same way `_validate_sums_to_one` already validates the top-level file. **No such
  YAML file is created by this document** — the loader's contract (raising, not defaulting, when
  the file for a requested version doesn't exist) is architecture, not implementation; it is
  documented here, not built.
- **Values — still BLOCKED, full stop.** No sub-metric weight number is invented, hardcoded as an
  illustrative default, or embedded anywhere in this spec or in `compose_score`. `compose_score
  (metrics, weights)` stays the generic, deterministic mechanism it already was; synthetic weights
  may be used **only in tests**, never in a code path reachable by a real ticker.

Stated plainly: **a real, production `WEALTH_SCORE` — and every score that depends on it
(`QUALITY_SCORE`, `GROWTH_SCORE`, `FCF_SCORE`, `VALUATION_SCORE`, `business_quality_composite`,
`valuation_quadrant`) — still cannot be fully materialized for any real ticker** until a real
`{group}_v1.0.yaml` file with real, calibrated values is authored and approved through this same
architecture. This is not a partial degradation; it is a hard block on the entire top-level output
for every ticker, Financials or not, until that file exists.

---

## 1. Module boundaries

Grounded in the existing scaffold (`packages/quant_core/{fundamentals,scoring,regime,backtest}/`,
`packages/engines/wealth_engine/`, `packages/shared/{weights,point_in_time,schemas}.py` — all
currently empty `__init__.py` stubs except `weights.py`/`point_in_time.py`/`schemas.py`, which
already exist per Phase 0).

```
packages/quant_core/fundamentals/     Raw metric calculators — pure functions, no I/O, no LLM.
  ├─ quality.py        ROIC (with/ex goodwill), ROE (DuPont), ROA, margins, margin stability, ROIIC
  ├─ growth.py          Revenue/EPS/NI/FCF/EBITDA growth, consistency, acceleration/deceleration
  ├─ fcf.py             FCF bridge, FCF Conversion (C2 N/A rule), FCF Growth ↔ Trajectory (M2)
  ├─ balance_sheet.py    Net debt, Debt/EBITDA, interest coverage, GAAP EBITDA (H6)
  ├─ capital_allocation.py  Net buyback yield, share count CAGR, valuation-context cross-check
  └─ valuation.py        P/E, EV/EBITDA, EV/FCF, EV/Sales, P/B, EV formula (M4), GAAP EPS (H6)

packages/quant_core/scoring/          Normalization + composition — pure functions.
  ├─ normalization.py    §13's 5 methods, winsorization/clipping, group-coverage rule
  └─ composition.py      Generic weighted-aggregation utility (see §0.2 — not wired to real
                           sub-weights yet); WEALTH_SCORE_RAW blend (real top-level weights, OK)

packages/quant_core/regime/           Sector/cycle classification — pure functions.
  ├─ sector_profile.py   Sector → applicable metric set + gate (Cyclicals/Energy, Utilities,
                           Financials-Banks, Financials-Insurance, REIT, generic industrial)
  └─ cycle_window.py     Shared 5–7yr cycle-normalization window helper (H2/H9)

packages/quant_core/backtest/         REUSED, not extended: existing `available_at <= as_of`
                                        point-in-time query helper (§22 — no new primitive)

packages/engines/wealth_engine/       Orchestration — the only layer that touches providers/storage.
  ├─ pipeline.py         DATA → CALCULATION → NORMALIZATION → SCORING → DECISION SUPPORT driver
  ├─ na_propagation.py   MetricResult / status machine (§6)
  ├─ red_flags.py         §21 registry — 16 deterministic detectors
  ├─ data_quality.py      DATA_QUALITY_SCORE (§16) + data_confidence roll-up (§15)
  ├─ scenario_engine.py   BEAR/BASE/BULL deterministic assumption anchoring (§17) — numbers only,
                           no narration (narration is the deferred Wealth Analyst agent)
  ├─ eligibility.py       Sector gate → WEALTH_SCORE N/A decision (§4/C4, principle 4)
  └─ output_contract.py   Assembles §24's object, MINUS agent-derived fields (§11)

packages/shared/weights.py            UNCHANGED in Phase 1B. Architecture for a sibling
                                        `load_component_weights(group, version)` is APPROVED
                                        (§0.2) — mirrors `load_weights()`'s pattern exactly — but
                                        is not implemented here, and no `config/weights/
                                        wealth_components/*.yaml` file is created. The function
                                        must raise (never default) when the requested version's
                                        file is absent, so it cannot silently invent values.

packages/storage/                      New models PROPOSED, not created (§10): `wealth_scores`,
                                        `wealth_score_components`, `red_flag_events`.

apps/api/routers/wealth.py            PROPOSED, not created: `GET /v1/wealth/{ticker}` per §24.
```

**Layering rule carried over from CLAUDE.md:** `quant_core` never imports from `engines` or
`providers`; `engines/wealth_engine` imports `quant_core` and the 9 provider Protocols, never a
concrete SDK; `apps/api` imports `engines`, never the reverse.

---

## 2. Inputs

### 2.1 Provider interfaces used (of the 9 in `packages/providers/base.py`)

| Interface | Used for | Not used for |
|---|---|---|
| `FundamentalsProvider` | Almost everything in §3–§7, §10 | — |
| `MarketDataProvider` | Price for P/E, EV, market cap, historical valuation windows (§11) | — |
| `MacroProvider` | Real 10Y yield → cost-of-capital discount channel only (§20, the one macro number allowed to touch a score) | Everything else macro (CPI, PCE, DXY, oil, ...) is thesis-only, out of scope without an agent |
| `CorporateActionsProvider` | Buybacks/dividends (§7), M&A structural-break detection (§17) | — |
| `AnalystEstimatesProvider` | Forward Growth (§3), PEG numerator confidence (§10) | — |
| `OptionsProvider`, `NewsProvider`, `EconomicCalendarProvider`, `FilingsProvider` | Not used by Wealth Engine's deterministic layer in Phase 1B. `EconomicCalendarProvider`'s earnings date feeds Visual Intelligence's `what_could_happen`, which is narrative/deferred (§0.1). `FilingsProvider` is explicitly Phase 2+ per §9 of the methodology (guidance-vs-actual, insider data). | — |

### 2.2 Blocking schema gap — `FundamentalsRecord` is not sufficient as-is (conceptual model approved, Python schema still an implementation task)

The current Phase 0 `FundamentalsRecord` (`packages/shared/schemas.py`) stores **pre-computed**
`roic`, `roe`, `fcf` as bare floats with no supporting line items. Rev. 4's methodology requires
computing these from raw components (DuPont decomposition, goodwill-in/ex ROIC split, GAAP-only
EBITDA, the explicit EV formula, the FCF bridge, both ROE floors) — none of which is possible from
the current DTO. **The requirement is narrow and non-negotiable: Quant Core must receive enough raw
inputs to perform these calculations deterministically itself, rather than trusting an opaque
pre-computed ratio from a provider.**

**Human decision, this round: APPROVED CONCEPTUALLY — normalized financial-statement concepts,
not a large flat `FundamentalsRecord` extension.** The conceptual model is three statement
concepts: **`IncomeStatement`**, **`BalanceSheet`**, **`CashFlowStatement`**, each carrying its own
point-in-time provenance, rather than one flat DTO grown to ~15+ optional fields. This mirrors how
a real filing is actually structured and scales better as more line items accumulate (e.g. Phase
2's Financials-sector metrics). **This is a conceptual/architectural approval only — the exact
Python schema (field names, exact `PeriodicRecordFields` wiring, whether these are three separate
top-level DTOs or nested under a container, how `FundamentalsProvider` methods change to return
them) is an implementation task that happens after this design is approved, not decided here.** No
file under `packages/shared/schemas.py` is touched to produce this document.

**Cross-statement consistency — explicit requirement, not an assumption.** Do **not** assume that
`IncomeStatement`, `BalanceSheet`, and `CashFlowStatement` records sharing the same `period_end`
must carry identical `reported_at`/`source` metadata. A company can amend or restate one statement
(e.g. a balance-sheet-only correction in a later filing) without the other two being restated in
lockstep — each statement's provenance must be tracked and filterable independently, and any
calculation spanning statements (the FCF bridge draws from all three; the DuPont decomposition
draws from two) must resolve each statement's own `available_at ≤ as_of` cutoff separately rather
than assuming one shared cutoff for the whole period. This is a live possibility the eventual
schema must accommodate, not an edge case to special-case away later.

The concrete list of raw fields needed — independent of exact container shape, and unaffected by
this decision — is unchanged from the prior draft:

| Raw input needed | Feeds | Why the pre-computed value isn't enough |
|---|---|---|
| `net_income` | FCF bridge, ROE numerator, FCF Conversion, EPS | Currently absent — only derived `eps`/`fcf` exist |
| `diluted_shares_outstanding` | GAAP EPS (H6), EV, per-share metrics | Absent |
| `depreciation_amortization`, `capex`, `delta_working_capital`, `operating_cash_flow` | FCF bridge cascade (§5) — must be inspectable step by step, not just a final `fcf` number | The bridge is explicitly mandatory (§5: "the bridge is mandatory, not a nice-to-have") |
| `goodwill` | ROIC-with-goodwill vs. `ROIC_ex_goodwill` split (H5) | Absent — H5 cannot be implemented without it |
| `total_debt`, `cash_and_equivalents`, `minority_interest`, `preferred_equity` | EV formula (M4) | Only `net_debt` exists, not the components M4 requires individually (and M4's unavailable-component treatment needs to distinguish "known $0" from "unknown") |
| `total_assets`, `book_equity` (total shareholders' equity) | ROE hard/soft floor (C3) | Absent |
| `revenue`, `cogs`, `operating_expenses` | GAAP-computed EBITDA (H6: `Revenue − COGS − Opex + D&A`, never "Adjusted EBITDA") | `revenue` exists; `cogs`/`opex` don't, and `debt_ebitda` is currently pre-computed (same problem as `roic`/`roe`) |
| `interest_expense`, `ebit` | Interest coverage (§6) | Absent |
| `inventory`, `receivables` | Red flags `RECEIVABLES_GROWTH_OUTPACING_REVENUE`, `INVENTORY_GROWTH_OUTPACING_REVENUE` (§21) | Absent |
| `stock_based_compensation` | SBC distortion tracking (§5), `HIGH_SBC_RELATIVE_TO_FCF` flag | Absent |

Also required, but not a `FundamentalsRecord`-shaped gap at all: `market_cap` is needed by the EV
formula, P/E, and P/B, but is never stored as a raw field anywhere — it is a **derived Quant Core
input**, computed from `close` price (`MarketDataProvider.OHLCVBar`) × `diluted_shares_outstanding`
(the Fundamentals side, under whichever container shape is eventually chosen). Combining a daily
price with a quarterly share count is exactly the mixed-cadence case §10.1's `available_at ≤ as_of`
invariant governs — see §10.1 for the reconciliation rule, decided this round.

**Conceptual model approved; exact schema remains an implementation task, open question #2 in §16.**
No file under `packages/shared/schemas.py` is touched to produce this document.

### 2.3 Additional schema gap — `CorporateAction` does not cover buybacks or M&A

Separate from §2.2's `FundamentalsRecord` gap, and separate from it structurally:
`CorporateAction.action_type` (`packages/shared/schemas.py`) is currently `"split" | "dividend" |
"spinoff"` — **it has no `"buyback"` value and no `"M&A"`/`"acquisition"` value.** Two methodology
requirements depend on exactly these two missing categories:

- **§7 Capital Allocation** needs gross/net buyback $ as a corporate action to compute Net Buyback
  Yield and the Share Count CAGR cross-check — not derivable from `split`/`dividend`/`spinoff`.
- **§17 Scenario Engine structural-break detection (M6)** needs an M&A/acquisition event with a
  deal-size-vs-pre-event-market-cap ratio — same gap, same root cause.

This is **provider-layer data**, not a `FundamentalsRecord` concern — it belongs in
`CorporateActionsProvider`'s contract (`packages/providers/base.py`) and/or the `CorporateAction`
DTO's `action_type` enum. **No enum value or API shape is proposed here; `packages/providers/base.py`
is not modified by this document.**

**Design comparison (this round) — evaluated, not chosen.** Two approaches, compared on the seven
criteria requested; the architecture decision stays OPEN pending this comparison's review:

| Criterion | Widen `CorporateAction.action_type` enum | Dedicated `BuybackEvent`/`MnAEvent` DTOs |
|---|---|---|
| Required fields | Reuses existing `ratio`/`amount`/`effective_at`/`source` — but buybacks need $ amount + shares retired + counterparty context, and M&A needs deal size + target + payment mix (cash/stock), which don't map cleanly onto the same two generic numeric fields every other action type uses | Each event type carries exactly the fields it needs (e.g. `BuybackEvent.dollar_amount`, `shares_retired`; `MnAEvent.deal_value`, `pre_event_market_cap`, `payment_mix`) — no generic-field overloading |
| Queryability | One table/query path for all corporate actions — simpler `get_actions()` call, but callers must branch on `action_type` and know which generic fields apply to which type | Callers query the specific event type they need directly; `CorporateActionsProvider` would need new methods (or a union return type) rather than one flat list |
| Provenance | Inherits `CorporateAction`'s existing provenance fields uniformly, no new work | Each DTO needs its own provenance wiring — more surface area, but no risk of one type's fields being misread as another's |
| Point-in-time behavior | Same `effective_at`/`available_at` pattern as splits/dividends — already proven | Same primitives reused, no new PIT mechanism either way — this criterion doesn't differentiate the two options |
| Extensibility | Adding a third new action type later (e.g. a future "tender offer" category) means widening the enum again and re-auditing every existing `action_type` switch statement for accidental fallthrough | Adding a new type means adding a new DTO — no risk of breaking existing `action_type` handling, but the type surface grows |
| Interaction with Capital Allocation (§7) | Net Buyback Yield/Share Count CAGR would filter `CorporateAction` by `action_type == "buyback"` and read generic `amount`/`ratio` — works, but "ratio" means something different for a buyback (shares retired) than for a split (share multiplier), a latent misuse risk | `BuybackEvent.shares_retired` is unambiguous by construction — no field-meaning collision across types |
| Interaction with M6 structural-break detection (§17) | Filtering `CorporateAction` for `action_type == "acquisition"` and reading `amount`/`ratio` as deal size works the same way, with the same latent ambiguity as above | `MnAEvent.deal_value` / `pre_event_market_cap` are purpose-built for exactly this ratio — most direct fit for M6's specific trigger condition |

**No option is selected.** The dedicated-DTO approach avoids the field-meaning-collision risk that
recurs in three of the seven rows above; the enum-widening approach is a smaller diff and reuses
more existing plumbing. This is presented for your review, not resolved by this document — the
provider/schema itself is not implemented.

### 2.4 Provenance requirement on every input

Every DTO consumed already carries (Phase 0, unchanged) either `ProvenanceFields.available_at` or
`PeriodicRecordFields.available_at`. No Wealth Engine calculation reads a field that lacks this —
enforced structurally by only accepting these DTO types as function inputs (§10).

---

## 3. Normalized raw metrics

The full raw-metric inventory, mapped 1:1 to methodology sections. "Sector gate" references §8.

| Metric | Formula (§ ref) | N/A condition | Sector gate |
|---|---|---|---|
| `ROIC` | NOPAT / Invested Capital, **with goodwill** (§4, H5) | Missing NOPAT or Invested Capital components | Excluded for Financials |
| `ROIC_ex_goodwill` | Same, Invested Capital excl. goodwill (§4, H5) — diagnostic only | Same | Excluded for Financials |
| `ROIIC` | ΔNOPAT / ΔInvested Capital, trailing window (§4) | Needs 2 consecutive periods | Excluded for Financials |
| `ROE_dupont` | Net Margin × Asset Turnover × Financial Leverage (§4) | **Hard N/A** if book equity ≤ $0 (C3); **soft/low-reliability** if 0 < equity < `<OPEN:roe_soft_floor_pct_of_assets>` (§14 Category B) | For Banks, leverage term is *expected*, not penalized (§4 Banks table) — different interpretation, not different formula |
| `ROA` | Net Income / Total Assets (§4) | Only scored "when relevant" (asset-heavy models, financials) — a sector-applicability flag, not a numeric gate | Applies to Financials (unlike ROIC) |
| Gross/Operating/FCF/EBITDA Margin | Standard, GAAP-based (§4, §6) | Missing components | Cyclicals/Energy cycle-normalized (§4 H2) |
| Margin Stability | Trailing stddev of margins (§4) | Needs ≥ 2 periods | — |
| Revenue/EPS/FCF/EBITDA Growth (the four `GROWTH_SCORE` composition inputs) | YoY + CAGR (§3) | Needs prior period; FCF uses M2's Trajectory fallback (§4 of this doc, §7) | Cyclicals/Energy cycle-normalized (H2) |
| Net Income Growth — **diagnostic only, NOT a `GROWTH_SCORE` composition input** | YoY + CAGR (§3) | Same as above | Used exclusively to quality-adjust EPS Growth's weight/reliability when EPS growth materially outpaces it (§3: "EPS vs Net Income growth split is mandatory"); `GROWTH_SCORE = weighted(RevenueGrowth, EPSGrowth[quality-adjusted vs NI growth], FCFGrowth, EBITDAGrowth, ForwardGrowth, Consistency, Acceleration)` per §14 of the methodology has no separate NI-Growth term — an implementer must not add an eighth composition input for it |
| Forward Growth | Consensus 1–2yr (§3) | No analyst coverage | — |
| Growth Consistency | Trailing 5yr quarterly stddev of YoY growth (§3) | < 5yr history | — |
| Growth Acceleration/Deceleration | Trailing 4Q vs. prior 4Q (§3) | < 8 quarters | — |
| FCF Margin, FCF Conversion, FCF Consistency | §5 | FCF Conversion is **hard N/A** when NI ≤ 0 (C2) | Excluded for Financials (FCF = OCF − CapEx not meaningful) |
| Net Debt, Debt/EBITDA, Interest Coverage, Net Debt/FCF | §6 | Missing components; EBITDA itself N/A if GAAP components unavailable, **never backfilled from "Adjusted EBITDA"** (H6) | Generic bands don't apply to Utilities (H8) or Financials (CET1, blocked) |
| Net Buyback Yield, Share Count CAGR, valuation-context cross-check | §7 | Missing buyback/dividend data | — |
| P/E, PEG, EV/EBITDA, EV/FCF, P/FCF, FCF Yield, P/S, EV/Sales, P/B, P/TBV, Div Yield | §10 | Per §10's applicability table (e.g. P/E needs positive GAAP EPS) | Sector-profile-gated per §10's table; Banks limited to P/B, P/TBV, ROE-justified P/B (computable). **Insurance: `UNSUPPORTED` — "P/B, P/TBV where meaningful" is not a deterministic rule; needs its own sector-specific approval before implementation (human decision, this round, §8)** |
| Historical valuation percentile | §11 | < `<OPEN:min_history_years>` years | Cyclicals/Energy compares against cycle-normalized trend (H9) |
| Sector valuation percentile | §12 | Peer set too small (LOW confidence, not N/A — §12) | Gross-margin-band peer matching (M3) |

---

## 4. Deterministic transformations

Reproduced faithfully from the approved methodology — this section is intentionally close to a
direct transcription, since the methodology's pseudocode is already implementation-grade for these
specific rules (they're Category A: "exact rule, nothing left open").

**FCF Trajectory ↔ Growth switch (M2, §5/§14 of the methodology):**

```python
def fcf_growth_metric(prior_fcf: float, current_fcf: float) -> tuple[str, float]:
    uses_trajectory = (prior_fcf <= 0) or (_sign(current_fcf) != _sign(prior_fcf))
    if uses_trajectory:
        return "fcf_trajectory_pp", current_fcf_margin - prior_fcf_margin
    return "fcf_growth_pct", (current_fcf - prior_fcf) / abs(prior_fcf)
```

Unit tests must cover all four sign combinations explicitly (+/+, +/−, −/+, −/−) — see §12/§13.

**FCF Conversion (C2):** `N/A` whenever `net_income <= 0`, evaluated *before* any other N/A logic
in §13's general handling, regardless of FCF's own sign.

**ROE floor (C3):** `book_equity <= 0` → `ROE = N/A`, `QUALITY_SCORE` composition drops ROE from
its inputs entirely (falls back to ROIC/ROIIC/margins — not zero-filled, not imputed).
`0 < book_equity < config.roe_soft_floor_pct * total_assets` → ROE computed but flagged
`LOW_RELIABILITY`, down-weighted (not excluded) in composition once the sub-weight surface exists.

**EV formula (M4):**

```python
def enterprise_value(market_cap, total_debt, minority_interest, preferred_equity, cash,
                      known_to_have_minority_interest: bool, known_to_have_preferred: bool) -> MetricResult:
    mi = minority_interest if minority_interest is not None else (0.0 if not known_to_have_minority_interest else None)
    pe = preferred_equity if preferred_equity is not None else (0.0 if not known_to_have_preferred else None)
    if mi is None or pe is None:
        return MetricResult(value=None, status="N/A", reason="known minority interest/preferred equity, figure unsourced")
    return MetricResult(value=market_cap + total_debt + mi + pe - cash, status="OK")
```

**GAAP EBITDA / EPS (H6):** computed only from `revenue − cogs − opex + d&a` and
`net_income / diluted_shares`. If any GAAP component is missing, status is `N/A` — there is no
fallback branch to a provider's "Adjusted" figure; this is a hard rule, not a coding convenience
that could accidentally regress into one.

**Red flag registry (§21) — 16 deterministic detectors**, each a pure function over already-computed
metrics, returning zero or one `RedFlag` record:

`EARNINGS_FCF_DIVERGENCE · RECEIVABLES_GROWTH_OUTPACING_REVENUE ·
INVENTORY_GROWTH_OUTPACING_REVENUE · MARGIN_DETERIORATION_TREND · AGGRESSIVE_CAPITALIZATION ·
HIGH_SBC_RELATIVE_TO_FCF · DILUTION_OUTPACING_BUYBACK · ACQUISITION_DRIVEN_GROWTH ·
DEBT_FUNDED_BUYBACKS · UNUSUAL_TAX_EFFECTS · ONE_TIME_GAINS_INFLATING_EARNINGS ·
DECLINING_CASH_CONVERSION · WORKING_CAPITAL_DRIVEN_FCF · RESTATEMENT_DETECTED ·
GUIDANCE_MISS_PATTERN · REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION`

`REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION` (H4, mechanism approved) is implementable now; its
firing rule reads `config.h4_margin_expansion_threshold_pp` rather than a hardcoded `2` (principle
6/7). All 16 are deterministic per §21 — none has an LLM in its detection path (principle 9).
`DEBT_FUNDED_BUYBACKS` applies a capped deduction to `CAPITAL_ALLOCATION_SCORE` only (its ceiling
is a Category B config constant, §14); the rest, including H4's flag, are informational-only —
enforced by a `mechanism: "informational" | "capped_deduction"` field on every `RedFlag`, defaulting
to `"informational"` so a new detector can't silently start deducting from a score.

---

## 5. Score formulas (composition layer)

**Implementable now (Category A, no blocker):**

```python
WEALTH_SCORE_RAW = (weights.wealth["quality"] * QUALITY_SCORE
                     + weights.wealth["growth"] * GROWTH_SCORE
                     + weights.wealth["fcf"] * FCF_SCORE
                     + weights.wealth["moat"] * MOAT_SCORE
                     + weights.wealth["valuation"] * VALUATION_SCORE)
# weights loaded via existing packages.shared.weights.load_weights("v1.0") — untouched (principle 1)
```

`business_quality_composite = (weights.wealth["quality"]*QUALITY_SCORE + weights.wealth["growth"]*GROWTH_SCORE
                                + weights.wealth["fcf"]*FCF_SCORE + weights.wealth["moat"]*MOAT_SCORE) / 0.80`
— same frozen ratios, rescaled, per C5.

**Blocked by §0.2 (component scores themselves):**

**Human decision (this round): coverage and weighting are two separate concerns, resolved
separately.** *Coverage* — whether **enough** sub-metrics are present to compute a group score at
all — is **COUNT-based** and unblocked: `coverage = number_of_present_submetrics /
total_number_of_group_submetrics`, compared against the existing OPEN `min_group_coverage_pct`
(60%, §14 — the value itself stays OPEN, only the counting *method* is now decided).
*Weighting* — how much each present sub-metric counts once coverage clears the bar — is a fully
separate question and is exactly what §0.2's sub-metric-weight blocker gates. The two must never be
conflated: a coverage check must not silently double as a weighting decision, and vice versa.

```python
def compose_score(sub_metrics: dict[str, MetricResult], weight_set: dict[str, float]) -> MetricResult:
    """Generic, deterministic weighted-aggregation utility.

    Deliberately takes `weight_set` as a caller-supplied argument rather than reading a
    production config file — the config *architecture* for that file is approved (§0.2,
    `load_component_weights`), but no `config/weights/wealth_components/*.yaml` file with real
    values exists yet. Tests exercise this with synthetic weight fixtures to prove the math (§13);
    it is not wired to real ticker data until that file is authored and approved.

    Coverage is COUNT-based (human decision) and independent of `weight_set` entirely — a
    sub-metric counts toward coverage whether its eventual weight is large or small.
    """
    present = {k: v for k, v in sub_metrics.items() if v.status == "OK"}
    coverage = len(present) / len(sub_metrics)                # COUNT-based, not weight-weighted
    if coverage < config.min_group_coverage_pct:                # §13, Category B — OPEN, see §14
        return MetricResult(value=None, status="INSUFFICIENT_DATA")
    # Weighting stage — BLOCKED for production use (§0.2). `weight_set` here is a test-only
    # synthetic fixture; no production caller passes a real one in Phase 1B.
    normalized_weight = {k: weight_set[k] / sum(weight_set[k2] for k2 in present) for k in present}
    return MetricResult(value=sum(v.value * normalized_weight[k] for k, v in present.items()), status="OK")
```

`QUALITY_SCORE`, `GROWTH_SCORE`, `FCF_SCORE`, `VALUATION_SCORE` all call `compose_score`, but no
production caller passes a real `weight_set` in Phase 1B — see §0.2, §16 Q1. Coverage checking
itself is not blocked and may be implemented and tested now; only the weighted-average stage is.

**`MOAT_SCORE` — DEFERRED/BLOCKED in full, not just its LLM input pathway (human decision, this
round, supersedes the prior "implementable as a pure function against fixtures" framing).** The
prior draft treated the *aggregation* (`weighted_average` of per-category `STRENGTH`) as Category A
and implementable now, deferring only the *inputs* (the agent that would supply `STRENGTH`/
`EVIDENCE`/`CONFIDENCE`) per §0.1. **That aggregation-is-implementable framing is not approved.**
The specific objection: this spec's prior working assumption — an unweighted mean across
*applicable* categories, justified only by §26's ledger having no logged parameter for it — is
itself an invented default with no methodology basis, not a neutral placeholder. Silence in the
decision log is not the same as approval of "equal weight" specifically; a different aggregation
(category-specific weights, a non-linear combination, something else) is equally consistent with
that silence.

**Disposition for Phase 1B: no `MOAT_SCORE` aggregation code — weighted, unweighted, or otherwise
— is written, tested, or fixture-exercised**, until an explicit evidence/provenance design for Moat
exists and is separately approved. This is a stricter, later gate than "no agent" (§0.1) — even the
purely deterministic, agent-free part of `MOAT_SCORE` is out of scope for now. No `moat.py` module,
no `MOAT_SCORE` fixture, and no `MOAT_SCORE` golden test exist in this design.

**`FCF_SCORE`'s red-flag deduction term — explicitly reconnected (human decision, this round).** The
methodology's own formula is `FCF_SCORE = weighted(FCFMargin, FCFTrajectory-or-FCFGrowth,
FCFConversion, FCFConsistency) − red_flag_deductions(§21, FCF-specific)` (§14 of the methodology) —
a subtraction term, not just a composition. The spec states this explicitly rather than leaving it
implicit in the general `RedFlag.mechanism` field:

```
FCF_SCORE = compose_score({fcf_margin, fcf_growth_or_trajectory, fcf_conversion, fcf_consistency},
                            weight_set)                                    # BLOCKED, §0.2
            − applicable_fcf_red_flag_deductions(red_flags)                # NOT blocked — §21
```

`applicable_fcf_red_flag_deductions` sums only the `capped_deduction`-mechanism red flags whose
`affected_scores` includes `FCF_SCORE`, per the fixed lookup table already defined in §21 of the
methodology (e.g. the pattern `DEBT_FUNDED_BUYBACKS` uses for `CAPITAL_ALLOCATION_SCORE`, §21). **No
new deduction is invented here and no existing red-flag definition is changed** — this only makes
explicit that the subtraction term exists and must be wired in, which the composition-layer
description previously omitted. The subtraction term is independent of the `compose_score` blocker
above: it can be computed and tested against fixture `FCF_SCORE` inputs even while the composition
weights remain blocked.

**`CAPITAL_ALLOCATION_SCORE`, `BALANCE_SHEET_SCORE`, and the `BalanceSheetMultiplier` — BLOCKED,
not a default (human decision, reaffirmed and sharpened this round).** `CAPITAL_ALLOCATION_SCORE`
and `BALANCE_SHEET_SCORE` are both implementable behind Category B config constants (leverage
bands, etc.); Capital Allocation stays informational-only (H3, does not feed `WEALTH_SCORE`).
`BalanceSheetMultiplier` — the mechanism *and* its curve — is Category C **BLOCKED**, not merely
"not yet tuned": it has not been approved at all, and Phase 1B must not invent it, not even as an
implicit identity (`× 1.0`).

**Semantic rule (human decision, this round — supersedes the prior "carry a reason string" fix):**

- **`wealth_score` = `null` until the approved `BalanceSheetMultiplier` exists.** The prior
  approach — returning `WEALTH_SCORE_RAW`'s value under the `wealth_score` field with a cautionary
  `reason` string attached — is withdrawn. It still let a `wealth_score` number reach a consumer
  who reads the value and ignores the reason, which is exactly the risk this rule closes.
- **The unadjusted composite is exposed separately, under the methodology's own existing name for
  it — `WEALTH_SCORE_RAW` (§14 of the methodology already names this quantity; this spec does not
  invent a new term for it) — never under the name `wealth_score`.** Whether it appears in the
  output contract as a sibling field, and under exactly what JSON key, is an API-shape detail not
  finalized here (§11.1) — the semantic requirement (a different name, not `wealth_score`) is what's
  decided.
- **`LOW_RELIABILITY` is not reused for this.** That status means "computed, but thin/unstable
  data" (e.g. the ROE soft floor) — a data-quality signal. A missing methodology component
  (the multiplier) is a different kind of gap entirely and must use `wealth_score`'s `null`/
  `UNSUPPORTED`-family status, never overload `LOW_RELIABILITY` to mean both things.
- **`balance_sheet_score` (and any `RedFlag`s referencing leverage) remain independently visible**
  in the output contract regardless of `wealth_score`'s `null` state — per §6 of the methodology,
  "leverage is a risk flag, not a component to be averaged away," which is exactly as true when the
  multiplier is *absent* as when it would be wrong.

No multiplier, no curve, and no penalty value of any kind is invented anywhere in this document.

**`valuation_quadrant`:** structure (six cells) is Category A and implementable; both axes'
thresholds (`quality_tier` cutoff, historical-valuation bands) are Category B config constants.
Inherits the same blocker as `business_quality_composite` (needs `QUALITY_SCORE`/`GROWTH_SCORE`/
`FCF_SCORE`/`MOAT_SCORE`).

---

## 6. N/A propagation

Every metric is represented as a `MetricResult`, never a bare `float | None` — so "why is this
missing" survives to the output contract instead of collapsing into an ambiguous `null`:

```python
class MetricResult(BaseModel):
    value: float | None
    status: Literal["OK", "N/A", "LOW_RELIABILITY", "INSUFFICIENT_DATA", "UNSUPPORTED"]
    reason: str | None = None
```

| Status | Meaning | Example trigger |
|---|---|---|
| `OK` | Computed normally | — |
| `N/A` | Hard rule says this metric doesn't apply / can't be computed | ROE with equity ≤ $0 (C3); FCF Conversion with NI ≤ 0 (C2); EV with unsourced known minority interest (M4) |
| `LOW_RELIABILITY` | Computed, but flagged as thin/unstable | ROE soft floor (C3) |
| `INSUFFICIENT_DATA` | Group coverage below the §13 threshold | < `<OPEN:min_group_coverage_pct>` of a group's sub-metrics present |
| `UNSUPPORTED` | Sector gate blocks this metric entirely | `ROIC` for a Bank; `QUALITY_SCORE`/`FCF_SCORE`/`BALANCE_SHEET_SCORE`/`WEALTH_SCORE` for Banks/Insurance (§8) |

Propagation rule: a composite's status is never better than its worst required input's status
where that input isn't excluded by design (e.g., `QUALITY_SCORE` excludes ROE entirely on hard-N/A
rather than propagating `N/A` upward — per C3's explicit fallback, §7). `UNSUPPORTED` propagates
unconditionally — nothing downstream of an `UNSUPPORTED` sector-gated component can read `OK`.

---

## 7. Fallbacks

| Situation | Fallback | Source |
|---|---|---|
| FCF sign crosses or prior ≤ 0 | Use FCF Trajectory (Δ margin, pp) instead of % Growth | M2 |
| ROE hard N/A (equity ≤ $0) | `QUALITY_SCORE` composition drops ROE, uses ROIC/ROIIC/margins only | C3 |
| GAAP EBITDA/EPS components missing | `N/A` — **no fallback** to "Adjusted" figures (explicitly forbidden, not just undesirable) | H6 |
| Historical valuation window < `<OPEN:min_history_years>` | Same as thin-history Scenario Engine case below — flagged, not silently computed from a thin window | §11, §13 |
| Scenario Engine: trailing window < 12 quarters | Anchor Bear/Base/Bull to sector-median percentiles instead of own-history; lower `data_confidence` | M6 |
| Scenario Engine: structural break detected (M&A > `<OPEN:break_mcap_pct>` or \|YoY revenue\| > `<OPEN:break_revenue_pct>`) | Truncate trailing window to after the break; if resulting window < 12q, fall through to thin-history case above | M6 |
| Known minority interest/preferred equity, figure unsourced | EV → `N/A`, **not** defaulted to $0 (only a *genuinely absent* line item defaults to $0) | M4 |
| Group coverage < `<OPEN:min_group_coverage_pct>` | Composite marked `INSUFFICIENT_DATA`, not computed from the thin subset | §13 |

No fallback in this table silently substitutes a value for the thing it replaces — each produces
either a clearly different, well-defined computation (Trajectory instead of Growth) or an explicit
status change (`N/A`/`INSUFFICIENT_DATA`), never a best-guess number.

---

## 8. Sector gates

```python
class SectorProfile(str, Enum):
    GENERIC_INDUSTRIAL = "generic_industrial"
    CYCLICALS_ENERGY = "cyclicals_energy"
    UTILITIES = "utilities"
    FINANCIALS_BANKS = "financials_banks"
    FINANCIALS_INSURANCE = "financials_insurance"
    CONSUMER_STAPLES_RETAIL = "consumer_staples_retail"
    REIT = "reit"  # likely excluded from Universe v1 anyway, §23
```

| Gate | Applies to | Effect |
|---|---|---|
| Cycle-normalization (H2/H9) | Cyclicals/Energy | Growth/Quality/Historical-Valuation cross-check use the 5–7yr window instead of single-year (§4/§0.2's window constant) |
| Leverage bands (H8) | Utilities | Different `Net Debt/EBITDA` bands (Category B, both sets OPEN) |
| **Financials scoring gate (C4, principle 4/5)** | Banks, Insurance | `ROIC`/`ROIIC` → `UNSUPPORTED`. `QUALITY_SCORE`, `FCF_SCORE`, `BALANCE_SHEET_SCORE` → `UNSUPPORTED` (no formula exists, none is invented here). Generic `GROWTH_SCORE` applies unchanged (no sector-specific formula invented either way). **`WEALTH_SCORE`, `business_quality_composite`, `valuation_quadrant` → `UNSUPPORTED` unconditionally** for both, regardless of `VALUATION_SCORE`'s own status. Enforced in `eligibility.py` as a single gate function, not scattered per-field checks, so principle 4 can't be silently violated by a future call site. |
| **`VALUATION_SCORE` — Banks vs. Insurance, NOT the same status (human decision, this round)** | Banks: **computable**, Insurance: **BLOCKED/OPEN, not confirmed** | **Banks:** the sector-appropriate diagnostic set (P/B, P/TBV, ROE-justified P/B, §10) is settled methodology and computable as `OK`. **Insurance: `VALUATION_SCORE` → `UNSUPPORTED`, same as Banks' Quality/FCF/Balance-Sheet.** Methodology §10's own words for Insurance's set — "P/B, P/TBV **where meaningful** — not otherwise designed" — are not a deterministic rule an implementer can code against; "where meaningful" requires a judgment call the methodology never specifies. Do not treat this as sufficient for implementation. Insurance requires the same explicit, dedicated sector-specific approval Banks' valuation set already received before `VALUATION_SCORE` can resolve to `OK` for an Insurance ticker. |
| Insurance generic-treatment confirmation | Insurance | Growth/Moat/Management/Capital Allocation generic applicability remains an open confirmation item (methodology §4) — **not resolved by this spec**, per principle 3. (Valuation is no longer bundled into this "likely generic" row — see above, it's now explicitly blocked rather than merely unconfirmed.) |

```python
def wealth_score_eligibility(sector: SectorProfile) -> MetricResult:
    if sector in (SectorProfile.FINANCIALS_BANKS, SectorProfile.FINANCIALS_INSURANCE):
        return MetricResult(value=None, status="UNSUPPORTED",
                             reason="C4 sector-specific Quality/FCF/Balance-Sheet methodology not yet approved")
    return MetricResult(value=None, status="OK")  # eligible; still subject to §0.2's blocker


def valuation_score_eligibility(sector: SectorProfile) -> MetricResult:
    """Separate gate from wealth_score_eligibility — Banks and Insurance are NOT the same case
    for VALUATION_SCORE specifically (human decision, this round)."""
    if sector == SectorProfile.FINANCIALS_INSURANCE:
        return MetricResult(value=None, status="UNSUPPORTED",
                             reason="Insurance valuation set ('P/B, P/TBV where meaningful') is not "
                                    "a deterministic rule — requires explicit sector-specific approval")
    return MetricResult(value=None, status="OK")  # Banks and everyone else: computable
```

---

## 9. Confidence / data-quality handling

**`DATA_QUALITY_SCORE`** (§16) — six detection categories, each a pure function over the input
snapshot: missing-field %, staleness (`as_of − available_at` vs. `<OPEN:staleness_threshold_qtrs>`),
provider disagreement (Phase 2+ no-op until a second provider per domain exists), unusual values
(domain-plausibility bounds, flagged not silently clipped — clipping is a *scoring* concern per
§13, flagging is a *data quality* concern, kept distinct), restatement detection (same
`(instrument_id, period_end, source)` re-ingestion-with-later-`available_at` signal the schema
already supports structurally), insufficient history.

**`data_confidence`** (§15) — deterministic roll-up, never LLM-asserted (principle 9):

```python
history_confidence = min(1.0, years_available / config.min_history_years)   # §26 row 13
quant_confidence = f(data_quality_score, history_confidence)                 # Quality/Growth/FCF/Valuation
qual_confidence = f(data_quality_score, agent_confidence_rollup)             # Moat/Management — deferred, no agent in Phase 1B
forward_growth_confidence = f(estimate_dispersion, num_analysts)             # AnalystEstimate DTO fields, already present
```

Since Moat/Management are out of scope (§0.1), `data_confidence` in Phase 1B output is computed
from the quantitative-only sub-roll-up; the qualitative branch is left as an explicit `None`/
not-yet-available component rather than defaulted to a number, to avoid silently overstating
confidence once the qualitative branch does start contributing.

---

## 10. Point-in-time requirements

No new primitive — reuses `packages/shared/point_in_time.py::ProvenanceFields`/
`PeriodicRecordFields` and the existing `packages/quant_core/backtest` `available_at <= as_of`
filter helper exclusively (§22, principle 10). Three concrete requirements carried into the design:

1. Every persisted `wealth_scores` row records `as_of` plus, in an `inputs` jsonb column, the exact
   `available_at` cutoff used per input record — so `as_of='2025-03-15'` is mechanically
   re-runnable.
2. Trailing-window calculations (Historical Valuation §11, Growth Consistency §3, Scenario Engine
   §17 fallback) must filter *each point in the window* by its own `available_at`, not just the
   overall query — a naive "pull 5 years" query without a per-point filter leaks restated figures
   into a supposedly historical band. `packages/quant_core/backtest`'s existing helper is the only
   permitted mechanism for this filtering (no bespoke point-in-time logic inside Wealth Engine,
   decision log row #20).
3. Moat/Management assessment versioning (§22's third bullet) is **not relevant to Phase 1B** since
   no agent runs — noted here only so it isn't forgotten when that work is eventually scoped.

### 10.1 Mixed-cadence reconciliation invariant (human decision, this round)

**APPROVED as a standing PIT invariant:** any derived metric combining inputs from different
reporting cadences must obey `available_at <= as_of` **independently for each input**, never
substitute "latest database value" for one side while correctly filtering the other. Concretely,
for `market_cap = close_price × diluted_shares_outstanding`: at a given price date, use the price
whose own `available_at ≤ as_of`, combined with the **latest eligible** `diluted_shares_outstanding`
whose **own** `available_at ≤ as_of` — not the globally-latest share count in the database,
regardless of whether that count would have been knowable on the price date.

This invariant is not new machinery — it's the same `available_at ≤ as_of` filter already required
everywhere else (§22 of the methodology, §10 above), stated explicitly here because mixed-cadence
combination is where it's easiest to get silently wrong (each side looks individually correct in
isolation; the bug is in how they're joined). It governs, without exception:

- `market_cap` (daily price × quarterly shares)
- `EV` (market cap × quarterly balance-sheet components)
- `P/E`, `P/B` (daily price × quarterly fundamentals)
- Structural-break detection (§17, M6) — a corporate-action event's deal size against the
  market cap *as of that event's own date*, not today's
- Backtest Engine's point-in-time queries generally (§22) — this is the same rule that engine
  already enforces, restated here so Wealth Engine's own derived metrics don't reinvent a laxer
  version of it
- Any future mixed-cadence derived metric not yet designed

No exact code location is prescribed here (that's an implementation detail); the invariant itself
is the approved, binding part.

---

## 11. Output schema

Reproduces §24 of the approved methodology; **Phase 1B-computable** vs. **deferred** columns added.
Nullability/typing for Banks/Insurance and raw ROIC already reflects the corrections applied to the
baseline document.

| Field | Phase 1B? | Note |
|---|---|---|
| `wealth_score` | **`null` in Phase 1B unconditionally** — not just for Banks/Insurance, and not once §0.2 is resolved either: even with sub-metric weights approved, `wealth_score` stays `null` until `BalanceSheetMultiplier` (Category C, separately blocked) is approved. The unadjusted composite is exposed under the methodology's own `WEALTH_SCORE_RAW` name instead (§5), never under `wealth_score` | `0-100 \| null` (effectively always `null` in Phase 1B), plus status/reason per §11.1 |
| `WEALTH_SCORE_RAW` (name per methodology §14, exact field placement not finalized) | Populated only once §0.2's sub-metric-weight blocker is resolved | Raw composite, not the same field as `wealth_score` — see §5 |
| `quality_score`, `growth_score`, `fcf_score` | Blocked by §0.2 | — |
| `moat_score` | **Not implemented at all** (human decision, this round — stricter than "fixture-only") | Deferred pending an explicit evidence/provenance design for Moat, separate from and stricter than the no-agent boundary alone; no aggregation code, weighted or unweighted, exists in Phase 1B |
| `capital_allocation_score` | ✅ Computable | Informational-only (H3) |
| `balance_sheet_score` | ✅ Computable | Risk flag; multiplier not applied (Category C) |
| `valuation_score` | ✅ Computable for Banks (blocked by §0.2 the same way as other composites — needs sub-weights too). **❌ `UNSUPPORTED` for Insurance** — its diagnostic set is not confirmed sufficient (§8, human decision this round) | Diagnostic-only field, independent of `wealth_score`'s `null` state, for whichever sectors it resolves to `OK` |
| `business_quality_composite`, `valuation_quadrant` | Blocked by §0.2 | `UNSUPPORTED` for Banks/Insurance regardless |
| `roic`, `roic_ex_goodwill` | ✅ Computable | Raw metric, `number`, not `0-100` |
| `data_confidence`, `data_quality` | ✅ Computable (quant-only branch) | — |
| `regime` | Partial | `market_regime` needs Trading/Macro Intelligence (out of scope); may stay `null` |
| `thesis`, `why_it_matters`, `what_could_happen` | ❌ Deferred | Requires Wealth Analyst / Narrative Synthesizer agents |
| `scenarios` (bear/base/bull numbers) | ✅ Computable | Numbers only, per §17's deterministic anchoring — no narration |
| `red_flags` | ✅ Computable | All 16 detectors, §4 of this doc |
| `key_risks`, `catalysts` | ❌ Deferred | Narrative, agent-derived |
| `what_changed` | ✅ Computable | Pure diff between snapshots, no LLM (§19) |
| `invalidation_conditions` | ❌ Deferred | Authored by the Thesis Engine (§18) |
| `weights_version`, `inputs` | ✅ Computable | — |

Given how much of the contract is blocked or deferred, `apps/api/routers/wealth.py` (also not
built in Phase 1B) would need to return a **partial** object with explicit `null`/`UNSUPPORTED`
fields rather than a 404 or an error — consistent with "N/A is a first-class state, not an
exception" throughout this design.

### 11.1 How `MetricResult` reaches the output contract (human decision, this round)

§24 of the methodology types most fields as a bare `0-100 | null`, but §6 of this spec's internal
`MetricResult` carries five distinct statuses (`OK`/`N/A`/`LOW_RELIABILITY`/`INSUFFICIENT_DATA`/
`UNSUPPORTED`) plus a `reason` string — and the methodology itself requires the distinction to
survive to a human-readable note, not collapse into a single `null` (§4: *"ROE excluded — book
equity ≤ 0"* is a different sentence from *"ROE reliability reduced — thin equity base"*, both
required to be distinguishable). This spec did not previously say how the two reconcile. Resolved
now: **every scored/metric field in the output contract is accompanied by its `MetricResult.status`
and `MetricResult.reason`**, not just a bare numeric-or-null value.

**Human decision, this round: the nested shape is APPROVED conceptually.** Every scored/derived
metric that requires status and reason is represented as a nested object, not sibling fields:

```jsonc
"wealth_score": { "value": 0-100 | null, "status": "OK" | "N/A" | "LOW_RELIABILITY" |
                   "INSUFFICIENT_DATA" | "UNSUPPORTED", "reason": "..." | null }
```

rather than the previously-sketched `"wealth_score": ..., "wealth_score_status": ...,
"wealth_score_reason": ...` sibling-field pattern. **This is a semantic/shape approval, not an API
implementation** — the exact Pydantic model, field ordering, and whether every single field (even
ones that are effectively always `OK`, like `weights_version`) gets wrapped or only the ones that
can meaningfully vary, are implementation-phase decisions, not decided here. `data_quality`'s notes
(§16 of the methodology) remain the natural place these reasons also surface in the Data Quality
narrative, but the raw `reason` string must reach the output regardless of whether a Data Quality
note additionally paraphrases it. No non-`OK` status is ever collapsed into a bare `null` with no
accompanying reason.

---

## 12. Test strategy

Directly extends §25 of the approved methodology; nothing here relaxes purity, reproducibility, or
weights-version pinning.

- **Purity/reproducibility.** Every `quant_core` function is `f(inputs, as_of) → MetricResult`(s);
  no wall-clock time, no randomness. Same inputs run twice → byte-identical output — enforced by a
  property-style test that calls the same function twice per fixture and asserts equality.
- **Golden-snapshot tests.** Fixed fixture snapshot → asserted exact `MetricResult` set for every
  sub-metric in §3. A future change to any output is a deliberate, reviewed test diff.
- **Weights-version pinning.** Every test that touches `WEALTH_SCORE_RAW` pins `weights_version="v1.0"`
  explicitly, never "latest."
- **M2 sign-combination tests.** All four `(prior_sign, current_sign)` combinations, asserting the
  Trajectory/Growth switch matches the disjunction exactly (this is the bug the Rev. 4 fix closed —
  a test that only covers "prior ≤ 0" would have hidden the original bug and must not recur).
- **C2/C3 guard tests.** NI ≤ 0 → FCF Conversion `N/A`. Book equity ≤ 0 → ROE `N/A` and
  `QUALITY_SCORE` composition drops ROE (once composition is unblocked).
- **H10 mandatory golden test.** Rising leverage + flat/declining margin/turnover → `QUALITY_SCORE`
  (or its DuPont sub-components, while composition is blocked) must not increase.
- **Quadrant golden test (C5).** Blocked by *two* independent gates, not one: §0.2's sub-metric
  weight blocker **and** `MOAT_SCORE`'s full deferral (§5, this round) — `business_quality_composite`
  needs `MOAT_SCORE` as an input regardless of whether §0.2 resolves. Once both clear: fixture per
  quadrant cell (all 6), plus one exercising the `quality_tier` boundary exactly.
- **Composition-layer tests (new, this spec).** `compose_score()` tested against **synthetic**
  weight fixtures (e.g. `{"roic_spread": 0.5, "gross_margin": 0.5}`) to prove coverage-threshold
  behavior, N/A-exclusion-and-renormalization, and `INSUFFICIENT_DATA` triggering — explicitly
  documented in the test file as *not* representing approved production weights (principle 2).
- **Red flag detection tests.** One fixture per detector in the §21 registry, asserting it fires
  with expected severity and does *not* fire on adjacent non-triggering fixtures (false-positive
  guard).
- **Sector gate tests.** Bank/Insurance fixture → `ROIC`/`QUALITY_SCORE`/`FCF_SCORE`/
  `BALANCE_SHEET_SCORE`/`WEALTH_SCORE`/`business_quality_composite`/`valuation_quadrant` all
  `UNSUPPORTED`. `valuation_score`: **Bank** → `OK` (or blocked only by §0.2, never by the sector
  gate); **Insurance** → `UNSUPPORTED` via `valuation_score_eligibility` specifically, not §0.2 —
  these two fixtures must assert *different* `valuation_score` outcomes, which is itself the
  regression test for this round's Banks-vs-Insurance distinction, in addition to principles 4/5.
- **Point-in-time tests.** A restated-fundamentals fixture must not leak the restated value into a
  historical window built with an earlier `as_of`.
- **Normalization edge-case tests.** Missing values, negative/undefined ratios, winsorization
  boundaries (§13), group-coverage threshold crossing.

---

## 13. Fixture strategy

Proposed layout: `tests/fixtures/wealth_engine/*.json` (or Python fixture factories in
`tests/conftest.py`-style modules), one fixture per scenario, each carrying a fixed `as_of` and
full `ProvenanceFields`/`PeriodicRecordFields` so point-in-time tests can reuse them directly.

| Fixture | Exercises |
|---|---|
| `golden_company` | Full, clean data — the baseline golden-snapshot test |
| `negative_equity_company` | ROE hard N/A (C3) |
| `thin_equity_company` | ROE soft floor / `LOW_RELIABILITY` (C3) |
| `pre_fcf_positive_company` | FCF Trajectory case, prior ≤ 0 |
| `fcf_sign_crossing_up`, `fcf_sign_crossing_down` | The two sign-change cases M2's fix specifically targets |
| `financials_bank` | Sector gate — `WEALTH_SCORE` `UNSUPPORTED`, `valuation_score` `OK` |
| `financials_insurance` | Sector gate — `WEALTH_SCORE` `UNSUPPORTED` **and** `valuation_score` `UNSUPPORTED` (not the same as the Bank fixture — Insurance's valuation set is blocked too, human decision this round, §8) |
| `cyclicals_energy_company` | Cycle-normalization window applied to Growth/Quality/Historical-Valuation |
| `utilities_company` | Utilities leverage bands (still OPEN, but mechanism testable) |
| `thin_history_company` | Scenario Engine sector-median fallback (< 12 quarters) |
| `structural_break_company` | M&A > threshold and/or \|YoY revenue\| > threshold → window truncation |
| `quadrant_cell_{1..6}` | One fixture per `valuation_quadrant` cell, once §0.2 (sub-metric weights) **and** `MOAT_SCORE`'s full deferral (§5) both clear |
| `insufficient_coverage_company` | Group coverage below the §13 threshold → `INSUFFICIENT_DATA` |
| `restated_fundamentals_company` | Same `(instrument_id, period_end, source)` re-ingested with a later `available_at` and a different value |
| `melting_ice_cube_company` | H4's exact firing condition (declining revenue, expanding margin, positive EBITDA growth) |
| `melting_ice_cube_near_miss` | Same shape but just under the (OPEN) `+2pp` threshold — false-positive guard |

Every fixture is versioned alongside the test that consumes it; none is treated as "real" ticker
data (all synthetic, matching the golden-snapshot discipline in §25 of the methodology).

---

## 14. Treatment of OPEN parameters

Single named config surface, structure only (no file created in this design-only phase). Every
value transcribed below is the **same illustrative value already logged as OPEN** in §26's
Category B ledger — nothing new is introduced, and nothing here becomes approved by appearing in
this table (principle 2/7):

```yaml
# PROPOSED shape — packages/shared/open_parameters.py would load this; not built in Phase 1B
# config/wealth_engine/open_parameters_v1.0.yaml  (illustrative filename — not created)
roe_soft_floor_pct_of_assets: {value: 0.05, status: OPEN, source: "methodology §4, C3"}
quality_tier_cutoff: {value: 70, status: OPEN, source: "methodology §14, C5"}
historical_valuation_bands_pct: {value: [10, 30, 70, 90], status: OPEN, source: "methodology §11"}
cost_of_capital_hurdle_pct: {value: [8, 10], status: OPEN, source: "methodology §4"}
leverage_bands_generic: {value: [1.5, 3.0, 4.5], status: OPEN, source: "methodology §6"}
leverage_bands_utilities: {value: [3.5, 5.0, 6.0], status: OPEN, source: "methodology §6, H8"}
winsorization_bounds_pct: {value: [1, 99], status: OPEN, source: "methodology §13"}
peg_applicable_growth_range_pct: {value: [5, 40], status: OPEN, source: "methodology §10, H7"}
gross_margin_peer_band_width_pp: {value: 15, status: OPEN, source: "methodology §12, M3"}
data_quality_staleness_qtrs: {value: 1.5, status: OPEN, source: "methodology §16"}
cycle_normalization_window_yrs: {value: [5, 7], status: OPEN, source: "methodology §3/§4/§10/§11, H2/H9"}
min_history_years: {value: 3, status: OPEN, source: "methodology §11/§17"}
structural_break_mcap_pct: {value: 30, status: OPEN, source: "methodology §17, M6"}
structural_break_revenue_yoy_pct: {value: 50, status: OPEN, source: "methodology §17, M6"}
working_capital_fcf_flag_threshold_pct: {value: 30, status: OPEN, source: "methodology §5/§21"}
debt_funded_buyback_score_ceiling: {value: 40, status: OPEN, source: "methodology §21"}
h4_margin_expansion_threshold_pp: {value: 2, status: OPEN, source: "methodology §21, H4"}
min_group_coverage_pct: {value: 60, status: OPEN, source: "methodology §13"}
universe_market_cap_floor_usd: {value: 10_000_000_000, status: OPEN, source: "methodology §23"}
universe_liquidity_floor_usd_per_day: {value: 50_000_000, status: OPEN, source: "methodology §23"}
universe_min_listed_history_yrs: {value: 5, status: OPEN, source: "methodology §23"}
```

**Design rule:** no `quant_core` or `wealth_engine` function is allowed to hardcode a bare numeric
literal for anything in this list — every reference goes through this named surface, so a future
calibration pass touches exactly one file and every changed value is a reviewable diff, not a
scattered find-and-replace. A lint/test (`test_no_bare_thresholds.py`-style) is proposed to grep
`quant_core`/`wealth_engine` source for suspicious bare float literals near keywords like
`threshold`/`floor`/`band` as a cheap regression guard once code exists.

---

## 15. Treatment of BLOCKED features

Every Category C item from the methodology's §26 ledger, with its explicit Phase 1B disposition —
"not implemented" is enforced structurally (absent module, `UNSUPPORTED` status, or a stub that
raises `NotImplementedError` with a message pointing at the blocking decision), never approximated:

| Blocked item | Phase 1B disposition |
|---|---|
| C4 — Banks: Quality/FCF/Balance Sheet formulas | `UNSUPPORTED` via the sector gate (§8) — no formula written, not even a placeholder |
| C4 — Insurance: Quality/FCF/Balance Sheet, generic-treatment confirmation | Same; the open confirmation question is left open, not assumed either way |
| `BalanceSheetMultiplier` (mechanism + curve) | **BLOCKED, not defaulted.** Neither the mechanism nor any curve/penalty value is invented. `wealth_score` is `null` in Phase 1B, full stop (§5, §11) — the unadjusted composite is exposed separately under the methodology's own `WEALTH_SCORE_RAW` name, never as `wealth_score` with a caveat attached; `balance_sheet_score` and leverage-related red flags remain independently visible in the output regardless |
| New sub-metric weight config surface | Not built (§0.2) — this is the master blocker; `compose_score()` exists as generic code but is never invoked with production weights |
| `MOAT_SCORE` LLM-aggregation exception | **Fully deferred, not partially.** Neither the agent (§0.1) nor the deterministic aggregation function itself (human decision, this round — the prior "unweighted mean" assumption is explicitly not approved) exists in Phase 1B. No `moat.py`, no fixtures, no golden tests. Awaits an explicit evidence/provenance design, separately approved. |
| Management Quality placement | Not designed; no `management_score` field exists anywhere in the output contract for Phase 1B |

No Category C item is "worked around" with a plausible-looking default — each resolves to an
explicit absence, matching the discipline the methodology itself insisted on for OPEN numbers.

---

## 16. Open questions requiring a follow-up human decision

These are forks, not recommendations — presented so you can pick, not so the spec can quietly pick
for you.

1. **Sub-metric weight VALUES (§0.2) — architecture now approved this round; values remain the
   open fork.** The config surface (`load_component_weights`, per-group
   `config/weights/wealth_components/{group}_v1.0.yaml` files) is now decided as the *shape*.
   What's still open: who authors and calibrates the actual numbers, and when — before any real
   `QUALITY_SCORE`/`GROWTH_SCORE`/`FCF_SCORE`/`VALUATION_SCORE`/`WEALTH_SCORE` can materialize for
   a real ticker, someone has to produce and approve real weight files through this architecture.
2. **`FundamentalsRecord` vs. normalized sub-DTOs (§2.2) — conceptual model now approved this
   round (`IncomeStatement`/`BalanceSheet`/`CashFlowStatement`); exact Python schema remains an
   implementation-phase task.** Field names, exact provenance wiring, and whether
   `FundamentalsProvider`'s method signatures change are not decided here.
3. **`MOAT_SCORE`'s aggregation approach — no longer a confirmable default, fully deferred this
   round.** Not "confirm whether unweighted mean is correct" — the unweighted-mean assumption is
   explicitly withdrawn, and *no* aggregation approach (weighted or unweighted) is approved. This
   waits on an explicit evidence/provenance design for Moat, not a quick confirmation.
4. **Output contract API implementation.** The nested `{value, status, reason}` *shape* is now
   approved conceptually (§11.1, this round). Still open: the exact Pydantic model, whether every
   field gets wrapped or only ones that can meaningfully vary, and whether `GET /v1/wealth/{ticker}`
   should expose a partial object at all in Phase 1B given how much of §24's contract remains
   blocked or deferred.
5. **`CorporateAction` provider-layer shape for buybacks/M&A (§2.3).** The design comparison
   (widened enum vs. dedicated `BuybackEvent`/`MnAEvent` DTOs, §2.3) is done this round across the
   requested criteria; the architecture choice itself remains OPEN pending your review of that
   comparison — not designed further here, and `packages/providers/base.py` is not touched.
6. **Insurance's diagnostic valuation set (§8) — new this round.** "P/B, P/TBV where meaningful" is
   explicitly not treated as sufficient for implementation. Needs the same kind of dedicated,
   explicit sector-specific approval Banks' valuation set already received before `VALUATION_SCORE`
   can resolve to `OK` for an Insurance ticker.

---

*End of Phase 1B implementation specification. No Python file, schema, weights file, or dependency
was created or modified to produce this document. Nothing here authorizes coding — per your
instruction, implementation waits for your review and approval of this specification, item by item
if you'd like to gate approval at that granularity.*
