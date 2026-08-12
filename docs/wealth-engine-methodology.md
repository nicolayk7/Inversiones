# Wealth Engine — Methodology Design

> **DRAFT — REQUIRES HUMAN APPROVAL (Rev. 4 — final methodological closure round pre-Phase 1B)**
> Phase 1A deliverable. Rev. 2 applied the Critical Review Committee's C1–C5, H2/H3/H6/H7/H8/H9/H10
> and M1–M7 corrections. Rev. 3 (a) defined deterministic fallback mechanisms previously left OPEN
> (M2, M6), (b) addressed H1 — **accepted as a known limitation, explicitly NOT resolved** — and H5
> — an explicit, human-approved goodwill-treatment rule — both previously carried over unaddressed,
> (c) refined C3's ROE floor and C4's Financials metric set, and (d) renamed `confidence` to
> `data_confidence` (M7). **This revision (Rev. 4) is a closure pass**: it fixes a real logic
> contradiction found in Rev. 3's M2 pseudocode, splits C4's Financials treatment into Banks vs.
> Insurance (neither implementable yet), relabels every illustrative number so none can be mistaken
> for an approved parameter, closes H4 with a new deterministic red flag proposal — mechanism and
> informational-only behavior **APPROVED**, `+2pp` threshold remains **OPEN** — and adds a
> three-category (A/B/C) implementation-readiness ledger in §26 covering the entire document. No
> code, weights file, or schema were changed to produce this revision.

---

## 1. Objective

The Wealth Engine answers exactly one question: **"What should I own for years, not what should I
trade this week?"** It identifies companies with an attractive combination of quality, growth,
cash generation, return on capital, competitive advantage, management competence, capital
discipline, and reasonable valuation — and it must never collapse those into a single blurred
judgment.

The methodology is built around one refusal: **QUALITY ≠ GROWTH ≠ MOAT ≠ VALUATION.** A company
can be excellent and too expensive to own today. A company can be cheap and mediocre. A company
can grow fast while destroying capital. Every section below exists to keep those distinctions
computable and visible, not smoothed away by a single blended number.

## 2. Fundamental principle — the Wealth Engine sub-pipeline

CLAUDE.md's top-level flow is `DATA → CALCULATION → ANALYSIS → SIGNAL → OPPORTUNITY → RISK →
DECISION SUPPORT`. This document zooms into the `ANALYSIS` step specifically for Wealth Engine and
expands it into a sub-pipeline — it does not compete with or replace the top-level rule:

```
DATA → CALCULATION → NORMALIZATION → SCORING → THESIS → DECISION SUPPORT
```

- **DATA** — provider-sourced records, point-in-time correct (§22).
- **CALCULATION** — deterministic ratios and derived metrics (§3–§7, §10–§12). Code only.
- **NORMALIZATION** — heterogeneous metrics converted to comparable 0–100 scales (§13). Code only.
- **SCORING** — component scores combined into `WEALTH_SCORE` via frozen, versioned weights
  (§14). Code only, **except** the narrow, explicitly-flagged Moat/Management input layer (§8–§9).
- **THESIS** — the Wealth Analyst agent (the only LLM in this pipeline) reads the already-computed
  scores, `data_confidence`, data quality, red flags, and scenario numbers, and produces the
  narrative (§18). It does not compute anything; it explains what was already computed.
- **DECISION SUPPORT** — the output contract (§24), which is what leaves Wealth Engine and enters
  Opportunity Engine / Visual Intelligence downstream.

The LLM never calculates a ratio. The one place this needs an explicit, scoped exception is
Moat/Management qualitative rating — flagged prominently in §8, §9, and the decision log, and
called out again in the final response to this phase.

---

## 3. Growth

| Metric | Window | Why it matters |
|---|---|---|
| Revenue Growth | YoY + 1/3/5-yr CAGR | Top-line proof of demand; hardest metric to fake for long |
| EPS Growth | YoY + CAGR | What accrues per share — but easy to inflate via buybacks (see below) |
| Net Income Growth | YoY + CAGR | Computed alongside EPS growth specifically to isolate the buyback effect |
| FCF Growth | YoY + CAGR | The "real" economic growth — what can actually be redeployed |
| EBITDA Growth | YoY + CAGR | Operating performance before capital-structure effects |
| Forward Growth | next 1–2 FY, consensus | Market-expectation input — inherently lower confidence, always labeled |
| Growth Consistency | trailing 5yr quarterly stddev of YoY growth | Predictable compounding deserves a premium over lumpy growth at equal CAGR |
| Growth Acceleration/Deceleration | trailing 4Q vs prior 4Q | Second-derivative signal — often the first sign of moat erosion, before it shows in margins |

**EPS vs Net Income growth split is mandatory, not optional.** If EPS growth materially outpaces
Net Income growth over a sustained window, that gap is buyback-driven share-count reduction, not
business growth — this is flagged (§21: `DILUTION_OUTPACING_BUYBACK`'s inverse case) and the
Growth Score's EPS-growth sub-metric is down-weighted relative to Revenue/FCF growth in that case,
never allowed to silently inflate the score.

Three separate lenses, never merged into one growth number without labels:

- **Historical Growth** — backward-looking, computed only from reported fundamentals. High
  confidence, since it's realized data.
- **Forward Growth** — consensus-estimate-based. Inherently lower confidence; confidence scales
  with analyst count and estimate dispersion (§15).
- **Growth Quality** — a modifier, not a separate score: was the growth organic (revenue-driven),
  inorganic (M&A-driven), or financially engineered (buyback-driven EPS growth without underlying
  revenue/FCF growth)? Feeds §21's red flag registry when the gap is large. A related, distinct
  pattern — declining revenue masked by cost-cutting-driven margin expansion, the "melting ice
  cube" — is covered by the dedicated `REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION` flag (§21,
  Critical Review H4), informational only, not a direct deduction to this score.

**Cycle-normalization for Cyclicals/Energy — APPROVED (Critical Review H2).** Single-year YoY
growth is misleading at cycle extremes for the Cyclicals/Energy sector profile (§10) — the same
company can show +80% "growth" coming out of a trough or a sharp decline off a peak, neither of
which says much about the business itself. For this sector profile, Growth's trend/consistency
sub-metrics use the same cycle-normalized window already established for valuation in §10 (5–7yr
average), not single-year figures. This reuses an existing, already-approved convention — no new
numeric parameter introduced.

**Separate normalization distributions for Forward vs. Historical Growth — APPROVED (Critical
Review M1).** A 1–2yr consensus forward-growth estimate and a 5yr historical CAGR have different
natural variance structures (forward estimates are noisier at the same nominal growth rate) and
must not be normalized (§13) against a shared distribution. Each is winsorized and scored against
its own distribution before being blended into `GROWTH_SCORE`.

---

## 4. Quality

| Metric | Notes |
|---|---|
| ROIC | NOPAT / Invested Capital. The central quality metric. |
| ROE | Must be DuPont-decomposed (Net Margin × Asset Turnover × Financial Leverage) before scoring — see below |
| ROA | Only scored when relevant (asset-heavy models, financials) |
| Gross / Operating / FCF / EBITDA Margin | Level + trend |
| Margin Stability | Trailing stddev of margins — stable-or-expanding beats volatile at the same average |
| ROIIC | ΔNOPAT / ΔInvested Capital, trailing window — is *new* capital earning above cost of capital, independent of legacy ROIC |

**ROIC vs cost of capital.** Quality Score rewards the *spread* between ROIC and a cost-of-capital
hurdle rate, not the absolute ROIC level. v1 proposes a single fixed hurdle rate (illustrative:
8–10%) applied across the universe rather than a full per-company WACC model — a deliberate
simplification, logged as OPEN in §26. Interpretation:

- ROIC > hurdle + meaningful spread → genuine value creation.
- ROIC ≈ hurdle → value-neutral, commodity-like economics.
- ROIC < hurdle → value destruction — **growing a value-destroying business makes things worse,
  not better.** Growth Score and Quality Score are never allowed to net out a high-growth,
  sub-hurdle-ROIC business into a "decent" blended score; this combination should read as a
  specific bear-case driver in the thesis (§18), not get diluted by averaging.

**ROE is never trusted at face value.** High ROE mechanically results from (a) genuine
profitability, (b) high asset turnover, or (c) leverage/buybacks shrinking the equity base — only
the first is a quality signal. The DuPont decomposition is mandatory input to the Quality Score;
an ROE increase driven mainly by the leverage term, with margin and turnover flat or declining, is
treated as neutral-to-negative, not positive, and is cross-checked against §6 (rising leverage)
and §7 (buyback activity shrinking the equity base).

**ROE floor rule — APPROVED and refined (Critical Review C3, Rev. 3).** Two thresholds, not one:

- **Hard floor — N/A.** ROE is marked **N/A whenever book equity ≤ $0.** Not a tunable parameter —
  dividing by zero or negative equity does not produce an economically meaningful ratio (a company
  with negative book equity from years of buybacks can otherwise show a sign-flipped or
  nonsensically extreme ROE that would be scored as if valid).
- **Soft floor — low-reliability flag.** Even *positive* book equity can be too thin relative to
  the balance sheet to produce a stable, meaningful ROE (a small denominator still produces
  extreme swings from ordinary earnings noise). ROE is flagged **low-reliability** (still computed,
  down-weighted in `QUALITY_SCORE`, not excluded) whenever book equity is positive but below a
  relative threshold — proposed illustratively as **5% of Total Assets**.

  **`5% of Total Assets` is an ILLUSTRATIVE / OPEN / NOT APPROVED FOR IMPLEMENTATION placeholder.**
  Only the *mechanism* (a relative floor, scaling with company size, rather than an absolute dollar
  figure) is approved. The number `5%` has not been validated against real data and must not be
  hardcoded or used in code until it is explicitly calibrated and approved — see the
  Implementation Readiness Classification in §26 (Category B). The **hard floor above (equity ≤
  $0 → N/A) is the only part of C3 approved for implementation as-is.**

When ROE is N/A (hard floor), `QUALITY_SCORE` falls back to ROIC, ROIIC, and the margin metrics
only — never imputes or estimates a substitute ROE — and the output carries an explicit Data
Quality note (§16) stating *"ROE excluded — book equity ≤ 0."* When ROE is merely low-reliability
(soft floor), it stays in the blend but the Data Quality note states *"ROE reliability reduced —
thin equity base."* Both are hard rules, not normalization conveniences; both are distinct from
the general missing-value handling in §13.

**ROIC and goodwill — APPROVED, explicit treatment (Critical Review H5, Rev. 3).** Invested
Capital's goodwill treatment was previously unspecified, structurally risking penalizing
disciplined acquirers vs. organic growers for reasons unrelated to underlying economics. Resolved
as follows:

- **`ROIC` (the metric that feeds `QUALITY_SCORE`) is computed WITH goodwill** — i.e. Invested
  Capital includes acquired goodwill as-reported. This is deliberate, not a default-by-omission:
  Quality Score is meant to answer "is this company creating value on *all* the capital
  shareholders have funded," including capital deployed via M&A — a company that persistently
  overpays for acquisitions *should* show a lower ROIC than one that grows organically or acquires
  at fair prices. Penalizing overpriced M&A is the metric working correctly, not a flaw.
- **`ROIC_ex_goodwill` is computed as a separate, diagnostic-only metric** (Invested Capital
  excluding acquired goodwill) — never fed into `QUALITY_SCORE`, surfaced alongside it in the
  output contract and available to the Thesis Engine.
- **The gap between the two is itself informative** and is the intended tool for distinguishing
  "weak ROIC because of a specific overpriced acquisition" (large, persistent gap between
  with-goodwill and ex-goodwill ROIC) from "weak ROIC because the underlying operating business is
  genuinely mediocre" (both readings are low and similar). A large, sustained gap is cross-
  referenced with §7's M&A discipline discussion in the thesis narrative — it is not itself a new
  red flag in v1, to avoid inventing an unsupported severity threshold without data.

**Mandatory golden test (Critical Review H10, see also §25).** Rising leverage combined with flat
or declining margin and asset-turnover terms must **not** increase `QUALITY_SCORE` — this is the
DuPont decomposition's entire reason for existing, and it is exactly the kind of subtle,
plausible-looking bug an incomplete implementation could introduce silently. A fixture-based
regression test asserting this is a **required** part of the Wealth Engine test suite before
`QUALITY_SCORE` is considered implementation-complete (§25).

**Cycle-normalization for Cyclicals/Energy — APPROVED (Critical Review H2).** ROIC and margins for
the Cyclicals/Energy sector profile are read against the same 5–7yr cycle-normalized window used
in §10 and §3, not single-year figures — a trough-year ROIC for an E&P company mostly reflects the
commodity price that year, not management skill, and scoring it at face value would misattribute a
macro effect to company-specific quality.

**Sector adaptation — Financials — BLOCKED.** ROIC (and, by extension, ROIIC) does not have a
meaningful definition for banks or insurers and is excluded for both. See the consolidated
Financials adaptation at the end of this section — **neither Banks nor Insurance has an approved
replacement yet; both are implementation-blocked.**

### Sector adaptation — Financials (applies to Quality, FCF, and Balance Sheet) — ARCHITECTURE APPROVED, NOT CLOSED — BLOCKS IMPLEMENTATION FOR THIS SECTOR (Critical Review C4)

> **C4 is not closed.** Generic industrial assumptions in §4–§6 do not transfer to Financials, and
> **"Financials" is not one sector for this purpose — Banks and Insurance are conceptually
> different businesses and must not share a metric set.** NIM and NPL ratio, in particular, are
> banking-specific and do not apply to an insurer. **Until this subsection is formally approved
> with real formulas and calibrated thresholds, any ticker classified as Banks or Insurance is
> `unsupported` / `not_scored` for `QUALITY_SCORE`, `FCF_SCORE`, `BALANCE_SHEET_SCORE`, and
> therefore for `WEALTH_SCORE` itself — never silently run through the generic industrial formulas,
> and never silently run through a half-specified Financials formula either.** Sector-specific
> **valuation diagnostics only** (§10) may still be computed and exposed — see the explicit
> eligibility rules at the end of this section. This is a hard implementation gate on `WEALTH_SCORE`
> for these sectors, not a soft recommendation.

Placement principle for whichever formulas are eventually approved: each replacement metric stays
inside the *same* top-level score it would otherwise belong to (`QUALITY_SCORE`, `FCF_SCORE`,
`BALANCE_SHEET_SCORE`) — no frozen weight slot is added, removed, or repurposed; only the
sector-conditional composition *within* each slot changes, exactly as §10 already does for
valuation metrics per sector. That placement principle is the only part of C4 considered settled.

**Banks**

| Domain | Excluded (not meaningful for banks) | Candidate replacement (NOT approved, NOT formulas — see status) | Status |
|---|---|---|---|
| Quality (§4) | ROIC, ROIIC — "Invested Capital" has no standard meaning when debt is the raw material, not a financing choice | ROE (DuPont-decomposed; the leverage term is *structurally expected* and must not be penalized like an industrial's) · ROA · Efficiency Ratio (opex ÷ revenue) · Net Interest Margin (NIM) · Credit Quality (non-performing loan ratio, provision-for-credit-losses trend) | **REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION.** No interpretation bands defined for any of these for a bank; no thresholds proposed — not invented here, per instruction. |
| FCF (§5) | Standard `FCF = OCF − CapEx` — OCF is dominated by loan/deposit balance-sheet growth, not an economic "free cash flow" concept | "Distributable Capital Generation" (concept only: net income in excess of what's needed to maintain target regulatory capital ratios while supporting balance-sheet/RWA growth) | **REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION.** No formula exists. This is a genuinely more complex modeling question (capital-adequacy-aware payout capacity) than a naming placeholder — real design work is required before any bank can receive an `FCF_SCORE`. |
| Balance Sheet (§6) | Debt/EBITDA, Net Debt/FCF — leverage *is* the business model for a bank | CET1 (Common Equity Tier 1) ratio or equivalent regulatory capital-adequacy proxy | **REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION.** No target/band defined. Data availability is also a Phase 2+ concern (`FilingsProvider`-dependent in most feeds). |
| Growth (§3) | — | No change — reported Total Revenue (net interest income + fee income) is usable as-is | Applies generically, no gate |
| Moat, Management, Capital Allocation, Valuation | — | No change — §8, §9, §7 apply generically; §10 already excludes EV/EBITDA and uses P/B, P/TBV | Applies generically, no gate |

**Insurance — separate from Banks, not previously addressed at all**

Insurers do not have a loan book, NIM, or NPL ratio — applying the Banks table to an insurer would
be exactly the kind of unexamined sector transplant this whole document exists to prevent.
Insurance needs its own candidate metric set, **not proposed with formulas here** (per "no
inventar fórmulas ni thresholds"), only named as the domain that needs definition:

| Domain | Excluded (not meaningful for insurers) | Candidate replacement domain (concept only — NOT defined) | Status |
|---|---|---|---|
| Quality (§4) | ROIC, ROIIC, and the Banks table above (NIM/NPL do not apply to an insurer) | Underwriting quality (e.g. combined ratio, loss ratio, expense ratio), reserve adequacy/development | **REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION.** No metrics selected, no formulas, no bands. This is a fresh gap, not previously scoped even provisionally. |
| FCF (§5) | Standard `FCF = OCF − CapEx` | Some analog of distributable capital generation, likely referencing investment-portfolio yield and float dynamics — genuinely different from a bank's version | **REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION.** Not designed. |
| Balance Sheet (§6) | Debt/EBITDA, Net Debt/FCF, and CET1 (a banking-specific regulatory ratio) | Risk-based capital adequacy (an insurance-specific regulatory framework, not CET1) | **REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION.** Not designed. |
| Growth, Moat, Management, Capital Allocation, Valuation | — | Likely closer to generic treatment than Quality/FCF/Balance-Sheet, but not verified | **OPEN — needs explicit confirmation**, not assumed to be generic by default |

**Net effect:** C4 remains fully open. The only thing this revision changes about C4 is making
explicit that "Financials" was never one problem — it is at least two (Banks, Insurance), the
Insurance side has received no design attention at all until now, and neither side has a single
approved formula or threshold. **Implementing Wealth Engine scoring for any Banks or Insurance
ticker is blocked until this subsection returns with real, human-approved content.**

**`WEALTH_SCORE` eligibility for Banks/Insurance — explicit architecture (human decision, this
round).** This closes the ambiguity between this section's hard gate and §10's Financials
valuation row: they are not in tension, because valuation diagnostics and full Wealth scoring are
different things, and only the former is available for these sectors.

- **Quality, FCF, Balance Sheet — N/A / unsupported** for any Banks or Insurance ticker, until the
  sector-specific methodology above is approved and implemented. No formula is invented here for
  any of the three, for either sector.
- **Growth — no sector-specific formula invented.** For Banks, the generic `GROWTH_SCORE`
  treatment already applies (reported Total Revenue is usable as-is, per the Banks table above).
  For Insurance, this decision does not invent a sector-specific Growth formula either — the
  existing open confirmation item in the Insurance table above (whether the generic treatment is
  verified-correct for insurers) is unchanged by this decision.
- **Valuation — sector-specific diagnostics MAY be calculated independently**, using only the
  valuation metrics already explicitly defined in §10 (P/B, P/TBV, ROE-justified P/B for Banks;
  P/B, P/TBV where meaningful for Insurance). This is diagnostic output, computed and exposed on
  its own.
- **Critically, a Banks or Insurance security must NOT receive a `WEALTH_SCORE` merely because a
  `valuation_score` is available.** `WEALTH_SCORE_RAW` (§14) is defined over all five components —
  Quality, Growth, FCF, Moat, Valuation. Because Quality, FCF, and Balance Sheet remain
  N/A/unsupported for these sectors, **`WEALTH_SCORE` = N/A** for any Banks or Insurance ticker,
  regardless of whether `VALUATION_SCORE` itself is computable from the diagnostics above. The same
  applies to `business_quality_composite` and `valuation_quadrant` (§14, C5), which also depend on
  `QUALITY_SCORE`/`FCF_SCORE`.
- The security may remain listed in the Equity Universe (§23) and may expose its diagnostic
  `valuation_score` in the output contract (§24), but it is **not eligible for full Wealth
  ranking** while C4 remains open — it does not get a `WEALTH_SCORE`, `business_quality_composite`,
  or `valuation_quadrant`.

---

## 5. Free Cash Flow

Standard definition: **FCF = Operating Cash Flow − CapEx.** (Maintenance-vs-growth CapEx
splitting requires filing-text parsing beyond standard fundamentals feeds — Phase 2+ refinement,
not v1.)

**`FCF_SCORE` is price-independent — APPROVED (Critical Review C1).** FCF Yield (FCF relative to
Market Cap or EV) is a *valuation* metric, not a cash-generation-quality metric, and previously
appeared in both `FCF_SCORE` and `VALUATION_SCORE` — a real double-count that conflated "how much
cash this business generates" with "how cheap the stock is," which is exactly the Quality-vs-Price
conflation this methodology exists to prevent. FCF Yield is removed from `FCF_SCORE` and now lives
**exclusively** inside `VALUATION_SCORE` (§10). `FCF_SCORE`'s four sub-metrics are:

| Metric | Purpose |
|---|---|
| FCF Margin | Level and scale |
| FCF Growth **or** FCF Trajectory | YoY %, CAGR when both periods are positive; **FCF Trajectory (Δ margin, percentage points) when either period is ≤ 0 or FCF crosses sign — see deterministic fallback below** |
| FCF Conversion | FCF/Net Income — should sit near or above 1.0 for high quality; sustained well below 1.0 is a flag. **See mandatory N/A rule below.** |
| FCF Consistency | Volatility across periods, % of periods FCF-positive |

*(FCF Yield still exists as a metric — see §10 — it is simply no longer part of `FCF_SCORE`'s
composition.)*

**The bridge is mandatory, not a nice-to-have.** Every FCF computation requires the full cascade
to be computable and inspectable: `Net Income → +D&A, ±ΔWorking Capital, ±other non-cash →
Operating Cash Flow → −CapEx → FCF`. The single most important red flag category in this whole
methodology is **Net Income growing while FCF does not** — everything else in this section exists
to explain *why* that might be happening:

- **Working-capital-driven FCF** — if ΔNWC drives a disproportionate share of OCF growth in a
  period (illustrative threshold: >30%), flag as low-quality, possibly reversing.
- **SBC distortion** — GAAP FCF already reflects stock-based comp only as a non-cash add-back in
  OCF, which means GAAP FCF *ignores the real dilution cost* of SBC to existing shareholders.
  Track SBC/Revenue as its own metric; do not let high-SBC companies score as if their FCF were
  fully "clean."
- **Abnormally low CapEx** vs peers/own history — ambiguous by itself (could be a genuinely
  asset-light model, could be under-investment); requires peer-relative context, never an absolute
  rule.
- **Acquisition-funded growth** — cross-check the investing section of the cash flow statement;
  M&A-funded "organic-looking" growth must be excluded/flagged, not counted as organic (§3).
- **Declining cash conversion trend** — FCF/NI ratio falling over consecutive periods.

**FCF Conversion N/A rule — APPROVED (Critical Review C2).** `FCF Conversion = FCF/NI` is marked
**N/A whenever Net Income ≤ 0**, regardless of FCF's sign. This closes a real sign-flip bug: with
both FCF and NI negative (e.g. FCF=−$50M, NI=−$100M), the raw ratio computes to +0.5 — a
plausible-looking "50% conversion" for a company that is unprofitable on both a cash and an
accrual basis. This is a hard mathematical guard, not a normalization convenience, and it applies
before §13's general negative/undefined-ratio handling.

**High-growth, pre-FCF-positive companies — deterministic fallback, APPROVED (Critical Review M2,
Rev. 3).** Two distinct problems previously conflated, now solved separately:

1. **Percentage FCF Growth is mathematically unreliable whenever the prior period is ≤ 0 or FCF
   crosses sign.** E.g. FCF moving from −$100M to −$50M is a genuine improvement, but the naive
   YoY formula computes `(−50 − (−100)) / (−100) = −50%`, which reads as decline — the opposite of
   what happened. This is a real mathematical bug, not just a coverage gap.
2. **A company can be persistently FCF-negative for years without that being informative on its
   own** — the useful signal is whether the losses are narrowing (on a credible path to breakeven)
   or widening.

**Deterministic fix for both — exact condition (fixed in Rev. 4).** `FCF_SCORE` uses **FCF
Trajectory** instead of percentage FCF Growth whenever **either**:

- the prior-period FCF is ≤ 0, **or**
- the current and prior periods have opposite signs (a sign change either direction).

Otherwise it uses ordinary percentage FCF Growth. This is a disjunction of two conditions, not one
— an earlier draft's pseudocode checked only "prior period ≤ 0," which silently fails the case
**prior FCF > 0, current FCF < 0** (a company falling *into* negative FCF): that case has no sign
match either, and must also route to Trajectory, but a same-sign-only-on-the-prior-side check would
incorrectly select percentage Growth for it and reproduce the exact sign-flip distortion this rule
exists to prevent. The two-condition form above is unambiguous for all four sign combinations
(+/+, +/−, −/+, −/−) and is now what both the prose and the pseudocode (§14) state.

FCF Trajectory is defined as the year-over-year change in **FCF Margin, in percentage points**
(e.g. FCF margin moving from −20% to −12% is a +8pp trajectory), which is well-defined and
directionally correct regardless of sign. This is not a special carve-out that marks the company
"insufficient data" — it is simply which of two always-available, always-computable formulas
`FCF_SCORE` uses for the growth/trend sub-metric, selected by the sign check above. A persistently
negative-FCF company with a strongly positive FCF Trajectory (losses narrowing quickly) scores
meaningfully differently from one with a flat or worsening trajectory — exactly the distinction
that mattered and was previously lost.

**Sector adaptation — Financials — BLOCKED, see §4.** Standard `FCF = OCF − CapEx` does not
describe cash economics for a bank (OCF is dominated by loan/deposit balance-sheet growth) or an
insurer (dominated by underwriting/float dynamics) — excluded for both, but with **no approved
replacement for either** yet. Any Banks or Insurance ticker must be marked `unsupported` /
`not_scored` for `FCF_SCORE` until §4's Financials adaptation is formally approved.

---

## 6. Balance Sheet / Financial Strength

| Metric | Notes |
|---|---|
| Cash, Total Debt, Net Debt | Net Debt = Debt − Cash |
| Debt/EBITDA | Standard leverage ratio |
| Interest Coverage | EBIT/Interest Expense |
| Current Ratio | Scored only where short-term operating cycle is meaningful |
| Net Debt/FCF | More "real" than Debt/EBITDA — EBITDA isn't cash |
| Maturity profile | When available (often requires filings text — Phase 2+) |

Proposed bands (illustrative, **OPEN** — needs real-data tuning before implementation):

| Band | Net Debt/EBITDA | Additional trigger |
|---|---|---|
| Net Cash | < 0 | — |
| Low Leverage | 0.0 – 1.5x | — |
| Moderate Leverage | 1.5 – 3.0x | — |
| High Leverage | 3.0 – 4.5x | — |
| Financial Stress | ≥ 4.5x | OR Interest Coverage < 2.0x |

**GAAP-consistent EBITDA — APPROVED (Critical Review H6).** Every EBITDA figure used above (and in
§10's EV/EBITDA) is **code-computed from GAAP financial-statement line items**
(Revenue − COGS − Opex + D&A), never a company-reported "Adjusted EBITDA." Adjusted figures
typically add back SBC, restructuring, and other charges the methodology treats skeptically
everywhere else (§5's SBC-distortion discussion) — silently accepting them here would be
inconsistent. The gap between GAAP and company-reported EBITDA may be surfaced as a diagnostic
footnote (a large gap is itself informative), but it is never the scoring input. **If the GAAP line
items needed to compute EBITDA are themselves unavailable, the metric is marked N/A (§13) — it is
never silently backfilled with the company's reported "Adjusted EBITDA" as a substitute (Critical
Review H6, refined Rev. 3).**

**Sector-specific leverage bands — Utilities — APPROVED direction, bands OPEN (Critical Review
H8).** The generic bands above are calibrated for a typical industrial and would misclassify
nearly every regulated utility as High Leverage or Financial Stress — utilities carry
structurally higher leverage safely, supported by predictable, rate-regulated cash flows. Proposed
illustrative bands for the Utilities sector profile (**OPEN — needs real-data tuning before use,
same status as the generic bands above**):

| Band | Net Debt/EBITDA (Utilities) | Additional trigger |
|---|---|---|
| Low Leverage | < 3.5x | — |
| Moderate Leverage | 3.5 – 5.0x | — |
| High Leverage | 5.0 – 6.0x | — |
| Financial Stress | ≥ 6.0x | OR Interest Coverage < 2.0x |

**This directly gates §14's `BalanceSheetMultiplier` proposal.** Per the Critical Review, that
multiplier mechanism should not be approved for general use until at least the Utilities bands
above are in place — and, separately, `BALANCE_SHEET_SCORE` cannot be computed for Banks or
Insurance at all until §4's Financials adaptation is resolved (CET1 for banks, risk-based capital
for insurers — neither defined yet, both `BLOCKED`). Otherwise every utility in the universe would
be unfairly penalized by a mechanism calibrated for a different capital-structure norm, and every
Financials name would either crash or silently mis-score. The multiplier's exact curve remains a
separate open question (§14, §26).

**Leverage is a risk flag, not a component to be averaged away.** A fast-growing company at a
Financial-Stress leverage band must not read as "high growth score, moderate balance sheet score,
therefore decent Wealth Score" — leverage should stay visible and can independently drive the
bear case in the thesis regardless of how strong the other scores are. This is the reasoning
behind proposing Balance Sheet Score as a **post-hoc risk multiplier** rather than an additively
weighted component — see §14's WEIGHT CHANGE PROPOSAL. Leverage also interacts directly with the
macro rate environment (§20): the same leverage band is more dangerous in a rising-real-yield
regime than in a falling one, which is why the macro→score channel is scoped specifically to the
discount-rate mechanism rather than left to leak in ad hoc.

---

## 7. Capital Allocation

| Input | Notes |
|---|---|
| Gross Buyback ($) | Raw spend |
| Net Buyback ($) | Gross buyback − stock issued (SBC/ESPP) |
| Share Count Change | Diluted shares outstanding YoY — the actual outcome shareholders feel |
| Dividends | Amount, payout ratio, growth |
| M&A | Capital deployed (post-acquisition performance tracking is data-availability-limited, flagged not scored in v1) |
| CapEx | CapEx/Revenue, CapEx/D&A as an expansion-spend proxy |
| Debt repayment | Contribution to deleveraging |

**A buyback is not automatically positive.** The methodology requires:

1. **Net Buyback Yield** = Net Buyback $ / beginning-of-period Market Cap.
2. **Share Count CAGR**, compared against (1) — a large gap between dollars spent and shares
   actually retired signals SBC dilution eating most of the benefit.
3. **Valuation-context cross-check** — buybacks executed while the Valuation Score (§10–§11) read
   "Expensive vs Own History" are flagged as capital-allocation red flags ("bought back stock at
   rich multiples"), not scored positively merely because a buyback occurred. This requires
   matching each buyback period against the *point-in-time* valuation history for that period
   (§22) — a company's buybacks must be judged against what its valuation looked like *then*, not
   today.
4. **Debt-funded buybacks** — buybacks happening concurrently with rising net debt is an explicit
   red-flag combination (§21), cross-referenced with §6.

`Buyback + reasonable valuation + real share-count reduction` and `Buyback + rich valuation +
SBC-driven dilution offsetting most of it` must produce visibly different Capital Allocation
outcomes, never the same "buybacks: yes" checkbox.

Capital Allocation Score is proposed as its own distinct score, separate from Management Quality
(§9) — see §14's WEIGHT CHANGE PROPOSAL for how it fits (or doesn't) into the frozen weights.

---

## 8. Moat / Competitive Advantage

> **This is the one section of Wealth Engine methodology that necessarily touches the LLM-cannot-
> calculate boundary. Flagged here, in §14, and again in the final response — REQUIRES HUMAN
> APPROVAL as a scoped exception, not assumed.**

Ten categories evaluated per company (Porter/Morningstar-style), each scored only when applicable:

`switching costs · network effects · economies of scale · brand · cost advantage (structural) ·
regulatory advantage · ecosystem/platform lock-in · intellectual property · distribution
advantage · data advantage`

The LLM is never allowed to conclude "this company has a strong moat" as free text. For every
applicable category it must produce a structured triple:

```
CATEGORY: <one of the ten>
STRENGTH: 0-100
EVIDENCE: <specific, citable — e.g. "10-yr avg ROIC 34% vs industry avg 12%",
           a filing excerpt, a market-share data point>
CONFIDENCE: 0-100  (based on evidence depth/history length available)
THESIS: <one paragraph, grounded only in the evidence cited>
```

Quantitative moat evidence (long-run ROIC/margin stability and level vs peers, from §4) is
supplied to the LLM as grounding input — the LLM is rating categories *using* numbers Quant Core
already computed, not inventing them.

**`MOAT_SCORE` itself is a deterministic aggregation (weighted average, code) of the per-category
`STRENGTH` values above.** The boundary being proposed: the LLM may produce structured, evidenced,
per-category sub-ratings under a fixed rubric; it may never produce the final composite number
directly, and it may never skip the evidence/confidence fields.

Three dimensions are kept separate, never merged:

- **Moat Strength** — composite 0–100, as above.
- **Moat Durability** — categorical (Eroding / Stable / Widening) or a years-estimate — how long
  the moat is expected to persist.
- **Moat Erosion Risk** — an explicit list of currently visible threats (new entrants, tech
  disruption, regulatory risk, customer concentration), separate from the strength score, never
  silently netted into it.

**Pharma/biotech durability rubric addition — APPROVED (Critical Review M5).** For companies
whose moat rests substantially on patent protection (pharma, biotech), **Moat Durability must
reference known patent expiration dates where available**, not rely on qualitative judgment alone
— a patent cliff is a concrete, dateable event, unlike most other moat categories, and the rubric
should ask for it explicitly rather than leave it to be volunteered.

---

## 9. Management

Separated explicitly from Capital Allocation Quality (§7, which is fully numeric). Management
Quality covers what numbers alone can't show:

| Dimension | What it requires |
|---|---|
| Guidance credibility | Track record of meeting/beating/missing own guidance, trailing N quarters. MVP proxy: consensus-beat-rate (weaker signal); true guidance-vs-actual requires filings/transcripts (Phase 2+). |
| Execution | Did the company hit disclosed strategic/margin targets? Evidence-based, same rubric as Moat. |
| Shareholder alignment | Insider ownership %, insider buy/sell activity, compensation structure (per-share/ROIC-linked vs pure top-line-linked) — largely Phase 2+ data dependency (FilingsProvider). |
| Historical execution | Multi-year synthesis across the above. |

Same discipline as Moat: every rating requires `EVIDENCE + CONFIDENCE + THESIS`, no narrative-only
conclusions. Same aggregation principle: LLM produces structured, evidenced sub-ratings; code
aggregates.

**Proposed placement:** the frozen weights (§14) have no dedicated Management slot. This document
proposes Management Quality feed into Capital Allocation Score as a qualitative input/modifier
(since management competence and capital discipline are tightly related) rather than becoming an
8th top-level component — flagged as OPEN in §26, open to the alternative of exposing it as its
own informational score in the output contract without a top-level weight, exactly as proposed for
Capital Allocation itself.

---

## 10. Valuation Engine

Multi-metric by design — no single multiple, and never the same metric set for every company.

| Metric | Applicability |
|---|---|
| P/E, Forward P/E | Requires positive trailing/forward **GAAP** EPS — else N/A |
| PEG | Secondary/diagnostic only — see caveat below |
| EV/EBITDA | Broadly applicable except financials (capital structure isn't economically meaningful there — see §4's Financials adaptation) |
| EV/FCF, P/FCF, **FCF Yield** | Preferred for capital-intensive or SBC-heavy businesses. **FCF Yield lives here exclusively (Critical Review C1) — removed from `FCF_SCORE`, see §5.** |
| Price/Sales, EV/Sales | Primary metric for negative-earnings/high-growth names where P/E is N/A |
| Price/Book, P/TBV | Only for asset-heavy models and financials — book value must be economically meaningful |
| Dividend Yield | Only for mature dividend payers |

**GAAP-consistent EPS — APPROVED (Critical Review H6).** P/E and PEG use **code-computed GAAP EPS**
(Net Income ÷ diluted shares), never company-reported "Adjusted EPS." Same rationale as EBITDA in
§6 — the methodology's SBC skepticism (§5) would be undermined if non-GAAP EPS were silently
accepted here. Same unavailable-component treatment as §6 applies: if GAAP Net Income or diluted
share count is unavailable, P/E is marked N/A, never backfilled from a reported "Adjusted EPS."

**Enterprise Value — explicit formula, with unavailable-component treatment (Critical Review M4,
refined Rev. 3).** `EV = Market Cap + Total Debt + Minority Interest + Preferred Equity − Cash &
Cash Equivalents`. Previously unspecified; minority interest and preferred stock are real
completeness gaps for conglomerates/industrials with such structures. **Treatment when a component
is unavailable:** Minority Interest and Preferred Equity default to **$0** when the company is not
known to have such a line item (the overwhelming majority of companies genuinely have none — this
is a correct zero, not a missing value). If a company **is** known to carry minority interest or
preferred equity (e.g. flagged by sector/filing metadata) but the specific figure could not be
sourced, EV is marked **N/A** and feeds the Data Quality score (§16) as a real data gap — never
silently defaulted to zero in that case, since that would understate EV specifically for the
companies where the omission matters most.

**PEG demoted to secondary/diagnostic — APPROVED (Critical Review H7).** PEG (P/E ÷ growth rate)
is fragile in three specific ways: the growth-rate horizon is ambiguous unless stated, it becomes
meaningless at low growth rates (any P/E ÷ ~2% approaches infinity), and at very high growth rates
it can make an expensive stock look artificially "cheap" because the denominator dominates —
masking real overvaluation risk. PEG is no longer a primary valuation input anywhere in §10's
sector-profile table; it is retained only as a diagnostic figure, computed exclusively using
**forward 1yr consensus growth** (fixed horizon, always disclosed alongside the number), and only
considered meaningful within an **illustrative applicable range of 5%–40% growth** (**OPEN — needs
tuning**) — outside that range it is marked N/A rather than displayed as a misleadingly precise
number.

**Sector-aware metric profiles, not one blended formula for everyone.** Comparing NVDA, JPM, COST,
and AMZN on the same P/E is a category error. Proposed profile mapping:

| Company type | Primary metrics | Notes |
|---|---|---|
| High-growth / negative-earnings tech | EV/Sales, EV/FCF (if FCF+), growth+margin composite | P/E often N/A. Peer comparison within this bucket requires gross-margin-band matching — see §12 |
| Mature profitable tech/software | P/E, EV/EBITDA, FCF Yield | PEG diagnostic-only, see caveat above |
| Financials (banks) | P/B, P/TBV, ROE-justified P/B | EV/EBITDA excluded — debt *is* the product. **Diagnostic-only valuation** — Quality/FCF/Balance-Sheet remain **N/A/unsupported** pending §4's Financials adaptation, so `WEALTH_SCORE` stays **N/A** for banks even though `valuation_score` is computable (see §4's explicit eligibility rules, §14) |
| Financials (insurance) | P/B, P/TBV where meaningful — **not otherwise designed** | Insurance is not the same profile as banks (no NIM/NPL); **diagnostic-only valuation** — Quality, FCF, Balance-Sheet all pending, see §4; `WEALTH_SCORE` stays **N/A** for insurers for the same reason as banks |
| Cyclicals (industrials, materials, energy) | EV/EBITDA on cycle-normalized earnings (**5–7yr avg — ILLUSTRATIVE, OPEN, not empirically validated**) | Single-year P/E is misleading at cycle extremes. Growth/Quality also cycle-normalized for this profile using this same window, see §3/§4 — the window length is a single shared OPEN parameter, not independently decided per section. Historical-valuation value-trap cross-check is sector-aware for this profile, see §11 |
| Consumer staples/retail | EV/EBITDA, P/E, FCF Yield | Standard set applies reasonably well |
| REITs | FFO/AFFO multiples | Standard P/E not meaningful — likely excluded from Universe v1 anyway (§23) |

`sector_metric_profile` is proposed as an explicit, code-owned lookup (sector/industry →
applicable metric set + internal weights), not a judgment call made per-ticker at run time.

---

## 11. Historical Valuation

Compare the company to its own history, not the market's:

1. Build the trailing distribution (proposed minimum 3 years / 12 quarters for any confidence — 
   **ILLUSTRATIVE, OPEN, not empirically validated**; 5 years preferred) of each applicable
   multiple, using **point-in-time price and point-in-time
   trailing/forward fundamentals at each historical point** — never fundamentals as later
   restated (§16, §21, §22).
2. Compute current value's percentile rank within that own-history distribution.
3. Map to bands (illustrative thresholds, **OPEN**, needs tuning):

| Band | Percentile |
|---|---|
| Extreme Cheap | < 10th |
| Cheap vs Own History | 10th – 30th |
| Fair vs Own History | 30th – 70th |
| Expensive vs Own History | 70th – 90th |
| Extreme Valuation | > 90th |

**"Cheap vs own history" is not automatically "cheap."** A multiple can compress structurally
because the business genuinely deteriorated (margin erosion, moat erosion, higher perceived risk)
— that's a value trap, not a bargain. Required cross-check: compare the valuation-percentile trend
against the trend in Quality/Growth/Moat scores over the same window.

- Multiple compressed **while fundamentals improved** → stronger "genuinely cheap" signal.
- Multiple compressed **while fundamentals deteriorated** → more likely "cheap for a reason."

This cross-check is mandatory output in the Valuation Score's supporting detail, not an optional
footnote — it's the difference between a defensible thesis and a value trap.

**Sector-aware carve-out for Cyclicals/Energy — APPROVED (Critical Review H9).** The cross-check
above, applied naively, misreads a normal cyclical trough as a value trap: fundamentals
"deteriorating" into a trough is expected behavior for a cyclical business, not evidence of
structural decline the way it would be for a secular one. For the Cyclicals/Energy sector profile
(§10), this cross-check compares valuation percentile against the **cycle-normalized** (5–7yr
average, per §3/§4's H2 treatment) fundamentals trend, not the single-year trend — a cyclical name
cheap on trailing multiples with a normal cyclical-trough single-year read is not automatically
flagged; the comparison must hold against the smoothed trend instead.

---

## 12. Sector Valuation

`Company vs Sector vs Industry vs Peer Group`, layered:

- **Peer definition:** same sub-industry classification as the primary filter; market-cap band and
  business-model similarity as secondary filters (sub-industry alone can still lump dissimilar
  models — e.g. "Technology" spans hyper-growth SaaS and mature semis).
- **Business-model similarity, operationalized — APPROVED direction, exact width OPEN (Critical
  Review M3).** "Business-model similarity" was previously an implicit judgment call. It is now an
  explicit **gross-margin-band match**: candidate peers must fall within an illustrative ±15
  percentage points of gross margin (**OPEN — needs tuning**) to be included in the peer set for
  EV/Sales-style comparisons — this is precisely what prevents comparing an 80%-gross-margin SaaS
  name against a 20%-gross-margin hardware reseller merely because both are tagged "Technology."
- **Peer source in v1:** drawn from within Universe v1 (~30 names, §23) first. **Explicit
  limitation, logged in §26:** with only ~30 tickers, most sector buckets will have very few (in
  many cases 1–3) peers, so Peer Valuation confidence must be marked LOW by construction in Phase
  1, not silently presented with the same confidence as Historical Valuation. Supplementing with a
  broader sector benchmark (index-level aggregate multiples) is a Phase 2 candidate, not required
  for the methodology to be internally consistent now.
- **Metrics compared:** the same sector-appropriate set from §10's profile table.

---

## 13. Normalization Engine

Every metric becomes a 0–100 sub-score before entering any weighted aggregation. Five methods are
available; none is used universally.

| Method | Strength | Weakness | Best fit |
|---|---|---|---|
| Percentile ranking (universe/sector) | Robust to outliers, simple | Loses magnitude — 2x better doesn't score 2x higher | Default for most bounded ratios |
| Z-score | Captures magnitude | Sensitive to outliers/skew — financial ratios are often fat-tailed | Growth rates, after winsorizing |
| Min-max, fixed domain bounds | Stable meaning across time (not resample-dependent) | Requires domain-reasoned floor/ceiling, not sample min/max | Margins, ROIC/ROE — level metrics |
| Sector-relative percentile | Handles structurally different scales across sectors | Needs enough peers per sector (§12's limitation) | Metrics that vary a lot by business model (margins, multiples) |
| Historical (own-history) percentile | Company judged against itself | Needs sufficient history; recent structural change can distort | Valuation multiples (§11) |

**Proposed default mapping (PROPOSED):**

- Growth rates → winsorized z-score within sector (right-skewed by nature; winsorize at 1st/99th
  percentile so one hyper-grower or a tiny-base artifact doesn't dominate the scale).
- Margins, ROIC, ROE, ROIIC → fixed-bound min-max, domain-reasoned bounds, sector-adjusted where
  the sector spread is extreme (e.g. software gross margins ~70–90% vs retail ~20–40%).
- Valuation multiples → historical percentile (§11) primary, sector-relative percentile (§12)
  secondary, blended per the Valuation Score formula.
- FCF yield / FCF margin → same treatment as margins.
- Leverage ratios → the explicit bands from §6, not a continuous percentile — the bands are
  already the unit domain experts think in.

**Edge cases — every one of these must have an explicit, testable rule, not an implicit default:**

- **Winsorization vs clipping.** Winsorizing caps at a *sample-derived* percentile (statistical
  robustness); clipping caps at a *fixed domain value* (economic plausibility, e.g. ROIC capped at
  100%). Both are used, for different reasons.
- **Missing values.** Never imputed into a score — a missing metric is *excluded* from its group's
  weighted average and deducted from Data Quality (§16). If group coverage falls below a minimum
  threshold (proposed: 60% of that group's sub-metrics present), the group score itself is marked
  "insufficient data," not computed from a thin subset.
- **Negative / undefined ratios.** Explicitly excluded (marked N/A) per documented applicability
  conditions (e.g. P/E requires positive trailing EPS; else N/A, fall back to the sector's
  alternate metric per §10's profile) — never silently computed as a nonsensical negative
  multiple.
- **Extreme-but-legitimate values.** Winsorized for the *score contribution* only — the raw value
  is always preserved and surfaced in the output/thesis, so nothing is hidden, only capped.

---

## 14. Score Architecture

Seven component scores are designed:

`QUALITY · GROWTH · FCF · MOAT · CAPITAL ALLOCATION · BALANCE SHEET · VALUATION`

### ⚠️ WEIGHT CHANGE PROPOSAL — read before anything else in this section

`config/weights/v1.0.yaml`'s `wealth` group has **five** slots, not seven:

```yaml
wealth:
  quality: 0.25
  growth: 0.25
  fcf: 0.15
  moat: 0.15
  valuation: 0.20
```

This methodology was designed against the user's brief, which asks for Capital Allocation and
Balance Sheet as their own scores. Per this phase's explicit instruction, **the frozen weights
were not modified.** Instead, this document proposes a way to keep all five existing numbers
completely unchanged while still surfacing all seven scores:

- **`QUALITY`, `GROWTH`, `FCF`, `MOAT`, `VALUATION`** map directly onto the five existing frozen
  weights — no change needed, formula below.
- **`CAPITAL_ALLOCATION_SCORE`** is proposed as an **informational score**, computed and exposed
  in the output contract (§24) and used by the Thesis Engine, but **not** part of the weighted
  `WEALTH_SCORE` sum. Alternative: fold it as a qualitative input into `QUALITY_SCORE` (capital
  stewardship is arguably a quality dimension) — both options are logged, neither is applied.

  **Explicit consequence — documented per Critical Review H3.** Because this score is
  informational-only, **sustained dilution does not, by itself, directly move `WEALTH_SCORE`.** It
  only affects the ranking indirectly: via the EPS-vs-Net-Income growth-quality check (§3, which
  down-weights EPS growth that outpaces NI growth) or if it trips a red flag (§21, e.g.
  `DILUTION_OUTPACING_BUYBACK`, `DEBT_FUNDED_BUYBACKS`). This is an accepted, explicit consequence
  of keeping Capital Allocation informational-only, not an oversight — recorded here so it is a
  conscious choice on the record, not something discovered later during implementation.
- **`BALANCE_SHEET_SCORE`** is proposed as a **post-hoc multiplicative risk modifier**, applied
  *after* the weighted sum, not as an eighth additive weight — this also matches §6's finding that
  leverage risk should stay visible rather than average away:

```
WEALTH_SCORE_RAW = 0.25·QUALITY + 0.25·GROWTH + 0.15·FCF + 0.15·MOAT + 0.20·VALUATION
WEALTH_SCORE      = WEALTH_SCORE_RAW × BalanceSheetMultiplier(BALANCE_SHEET_SCORE)
```

Where `BalanceSheetMultiplier` is proposed as e.g. `1.00` for Net Cash/Low Leverage, tapering
toward a meaningfully reduced multiplier (illustrative: `0.85` or lower, **OPEN**, needs tuning)
at the Financial Stress band. The exact curve is not decided here.

**Banks/Insurance eligibility — explicit (human decision, C4).** `WEALTH_SCORE_RAW` requires all
five components. For any Banks or Insurance ticker, `QUALITY_SCORE`, `FCF_SCORE`, and
`BALANCE_SHEET_SCORE` are N/A/unsupported (§4, C4 — no formula approved yet), so **`WEALTH_SCORE` =
N/A** for that ticker regardless of whether `VALUATION_SCORE` itself is computable from the
diagnostic metrics in §10. A `valuation_score` being available never by itself qualifies a
Banks/Insurance ticker for a `WEALTH_SCORE`.

**This entire arrangement is a proposal, not a decision.** Both `CAPITAL_ALLOCATION_SCORE`'s
placement and the `BalanceSheetMultiplier` curve are `REQUIRES HUMAN APPROVAL` in §26. No file
under `config/weights/` was touched to produce this document.

A second, smaller weight-related finding: the methodology in §3–§11 implies **sub-metric weights
within each group** (e.g., how much ROIC counts vs Gross Margin inside `QUALITY_SCORE`) that don't
exist anywhere yet — `v1.0.yaml` only defines the five top-level group weights. Implementing this
methodology will require a **new config surface** (e.g.
`config/weights/wealth_components/quality_v1.0.yaml` or nested keys under the existing file) —
this is new configuration, not a change to the five frozen numbers, but it's significant enough to
log explicitly and get approved before implementation (§26).

### Score definitions (formulas are illustrative pseudocode, not implementation)

```
QUALITY_SCORE    = weighted(ROIC_spread, ROE_dupont_adjusted[N/A if equity<=0, see §4],
                             ROA[if relevant], GrossMargin, OperatingMargin, FCFMargin,
                             EBITDAMargin, MarginStability, ROIIC)
                   # Cyclicals/Energy: ROIC/margins cycle-normalized, see §4 (H2)
                   # Financials: ROIC/ROIIC excluded, see §4 sector adaptation (C4)

GROWTH_SCORE     = weighted(RevenueGrowth, EPSGrowth[quality-adjusted vs NI growth],
                             FCFGrowth, EBITDAGrowth, ForwardGrowth[confidence-weighted,
                             own distribution — see §3 M1], Consistency, Acceleration)
                   # Cyclicals/Energy: cycle-normalized, see §3 (H2)

uses_trajectory = (prior_period_FCF <= 0) OR (sign(current_period_FCF) != sign(prior_period_FCF))
# NOT merely "prior_period_FCF <= 0" — that alone misses the case prior_FCF > 0, current_FCF < 0
# (a sign change on the way DOWN), which is exactly the case % growth breaks on. Fixed in Rev. 4
# after this exact gap was found between the Rev. 3 prose (correct) and pseudocode (incomplete).

FCF_SCORE        = weighted(FCFMargin,
                             FCFTrajectory[Δmargin, pp] if uses_trajectory else FCFGrowth,
                             FCFConversion[N/A if NI<=0, see §5 C2],
                             FCFConsistency)
                   − red_flag_deductions(§21, FCF-specific)
                   # FCF Yield REMOVED — lives in VALUATION_SCORE only, see §5 (C1)
                   # Deterministic sign-safe growth/trajectory switch, see §5 (M2)
                   # Financials: replaced by Distributable Capital Generation, see §4 (C4, BLOCKED)

MOAT_SCORE        = weighted_average(per_category_STRENGTH)   # LLM-rated inputs, code-aggregated
                    # Pharma/biotech: durability references patent expiration where known (M5)
                    # ROIC feeding Quality is WITH goodwill; ROIC_ex_goodwill is diagnostic-only (H5)

VALUATION_SCORE   = blend(HistoricalValuationPercentile §11 [sector-aware value-trap
                           cross-check for Cyclicals/Energy, H9], SectorValuationPercentile §12
                           [gross-margin-band peer matching, M3], sector_metric_profile §10
                           [GAAP EPS/EBITDA only, H6; PEG diagnostic-only, H7])
                   # FCF Yield included here, not in FCF_SCORE, see (C1)

CAPITAL_ALLOCATION_SCORE (informational) = weighted(NetBuybackYield × valuation_context_multiplier,
                           ShareCountChange, DividendPolicyQuality, MnADiscipline)
                           − red_flag_deductions(§21, capital-allocation-specific)
                           # Does not feed WEALTH_SCORE directly — explicit consequence, see (H3)

BALANCE_SHEET_SCORE (risk modifier, not additive) = banding_function(§6 bands)
                   # Sector-specific bands: Utilities (H8, OPEN), Financials CET1-based (C4, OPEN)
```

### Known modeling limitation: Quality/FCF correlation — ACCEPTED (Critical Review H1, Rev. 3)

`QUALITY_SCORE` and `FCF_SCORE` are not statistically independent inputs to `WEALTH_SCORE`'s
linear weighted sum — both are substantially driven by the same underlying profitability/margin
signal (a margin-compression event moves both scores in the same direction simultaneously). The
naive weighted-sum formula therefore understates their *combined* effective influence relative to
what the nominal 25%/15% weights would suggest in isolation.

**This is accepted as a known limitation, not fixed in this revision.** No numeric weight is
changed as a result — doing so without empirical/backtest evidence of the actual magnitude of the
effect would be exactly the kind of unjustified tuning this process exists to prevent. This is
logged here as a standing item to revisit once (a) C1's fix (removing the FCF-Yield double count)
has been implemented and (b) real historical data is available to measure whether 25/15 still
reflects the intended relative influence of Quality vs. FCF once the correlation is accounted for.
Until then, `WEALTH_SCORE` consumers should be aware that a shared profitability shock will move
the blended score by more than a naive reading of the two weights would predict.

### Business Quality Composite & Valuation Quadrant — APPROVED architecture (Critical Review C5)

`WEALTH_SCORE` remains the single ranking number Opportunity Engine consumes. But a single blended
number cannot, by construction, distinguish "excellent company, expensive" from "mediocre company,
cheap" when both land at a similar blended value — which is exactly the failure the brief's
`great company / great stock / great price / great opportunity` distinction is meant to prevent.
Two additional fields are added to the output contract (§24), **computed entirely in Python, never
by the LLM**, using explicit deterministic thresholds:

```
business_quality_composite = ( 0.25·QUALITY + 0.25·GROWTH + 0.15·FCF + 0.15·MOAT ) / 0.80
```

This reuses the **existing frozen weight ratios** for Quality/Growth/FCF/Moat exactly as they
already are in `config/weights/v1.0.yaml` — it does not invent a new number, it rescales the four
non-valuation components (which sum to 0.80 of the frozen `wealth` weights) back up to sum to 1.0,
so `business_quality_composite` is on the same 0–100 scale as everything else. No file under
`config/weights/` is touched by this — the rescaling happens in code at read time.

```
quality_tier  = "excellent" if business_quality_composite >= 70 else "weak"    # OPEN, needs tuning
valuation_tier = one of {"cheap", "fair", "expensive"}, derived from §11's existing 5-band
                 historical-valuation percentile, collapsed:
                   cheap      = Extreme Cheap ∪ Cheap vs Own History
                   fair       = Fair vs Own History
                   expensive  = Expensive vs Own History ∪ Extreme Valuation

valuation_quadrant = f(quality_tier, valuation_tier)   # one of the 6 labels below
```

**Six states, not five — explicit resolution (Rev. 3).** The approval for this revision listed
five named states (`excellent_cheap`, `excellent_fair`, `excellent_expensive`, `weak_cheap`,
`weak_expensive`) while also flagging that a five-state scheme is insufficient because "fair"
applies to both quality levels — and asked for exact deterministic thresholds if so. It is
insufficient, for a simple, mechanical reason: `quality_tier` is binary (excellent/weak) and
`valuation_tier` is a 3-state partition (cheap/fair/expensive) that is **mutually exclusive and
collectively exhaustive** by construction (every percentile falls into exactly one of the three
bands, §11). A binary axis crossed with a 3-state axis produces **2 × 3 = 6** cells, not 5 — the
missing fifth-scheme cell is `weak_fair` ("mediocre business, fairly priced"), which is a common,
real state (most companies most of the time) and cannot be merged into either `weak_cheap` or
`weak_expensive` without silently misclassifying it. **The six-cell table below is the approved,
final scheme:**

| | Cheap | Fair | Expensive |
|---|---|---|---|
| **Excellent** (`business_quality_composite ≥ 70`) | `excellent_cheap` | `excellent_fair` | `excellent_expensive` |
| **Weak** (`business_quality_composite < 70`) | `weak_cheap` | `weak_fair` | `weak_expensive` |

Exact deterministic thresholds, stated explicitly per the approval's instruction:

- `quality_tier`: single cutoff at `business_quality_composite = 70`. **`70` is an ILLUSTRATIVE
  PLACEHOLDER — NOT AN APPROVED THRESHOLD.** Only the *mechanism* (one deterministic cutoff on the
  rescaled composite) is approved; the number itself has no empirical basis yet and must not be
  hardcoded as if it were final — see §26's Implementation Readiness Classification (Category B).
- `valuation_tier`: reuses §11's existing 5-band historical-valuation percentile, collapsed exactly
  as shown in the pseudocode above (10th/30th/70th/90th percentile cut points). **These cut points
  are likewise ILLUSTRATIVE PLACEHOLDERS, not approved** — they were already logged OPEN in
  §11/§26 before the quadrant existed, and the quadrant inherits that same unresolved status; it
  does not introduce a new threshold, but it does not resolve the old one either.

**No numeric value in this subsection is implementable as-is.** The six-cell *scheme* (the labels,
the 2×3 structure, the reasoning for why five states are insufficient) is fully approved and
final. The two numeric axes that populate it are not.

Both `business_quality_composite` and `valuation_quadrant` are pure functions of already-computed
scores — no new data requirement, no LLM involvement, fully consistent with §25's testability
requirements (a golden test should assert the quadrant label directly, not just the composite
number, and must cover all six cells, not five).

---

## 15. Score vs Confidence (field renamed `data_confidence` — see below)

`SCORE` and `data_confidence` are never the same number and never displayed as one. Example,
straight from the brief:

| | Quality Score | data_confidence |
|---|---|---|
| Company A | 95 | 95% |
| Company B | 95 | 55% |

Company B's identical score rests on thinner evidence and must never be treated as an equally
strong thesis.

Proposed composition:

- **Quantitative scores** (Quality/Growth/FCF/Valuation): confidence driven by Data Quality (§16)
  and history-length coverage — e.g. `history_confidence = min(1, years_available / 3)` for
  metrics that need a 3-year minimum (growth consistency, historical valuation bands).
- **Qualitative scores** (Moat/Management): confidence additionally driven by evidence
  count/depth/source diversity — the LLM's own per-category `CONFIDENCE` field (§8, §9 — scoped to
  those rubrics, not renamed; the ambiguity risk is specific to the top-level rolled-up field)
  rolled up deterministically (code), not re-judged by the LLM at the roll-up step.
- **Forward Growth:** confidence driven by analyst estimate dispersion (`high − low` spread
  relative to consensus) and `num_analysts` — both already present in the `AnalystEstimate` DTO
  from Phase 0. Narrow dispersion + many analysts → high confidence; the reverse → low.

Overall `data_confidence` is a deterministic roll-up of the above, never a single LLM-asserted
number.

**Renamed `CONFIDENCE` → `data_confidence` — APPROVED (Critical Review M7, Rev. 3).** Documentation
alone was judged insufficient to prevent misreading this field as "confidence the investment
thesis is correct" — a self-documenting field name is more robust than a docstring nobody reads.
The field is renamed throughout the output contract (§24) and this document. It measures confidence
in the **completeness and freshness of the underlying data and evidence only** — it is not, and
must never be presented as, confidence that the investment thesis itself is correct. A company with
perfectly clean, complete, current data can still face an undisclosed risk (e.g. impending
technological disruption) that the data doesn't yet reflect; a 94% `data_confidence` describes the
inputs, not the outcome. This distinction is additionally stated in the Thesis Engine's language
(§18) so it is reinforced at the point where a human actually reads the output, not only in the
field's schema documentation.

---

## 16. Data Quality

`DATA_QUALITY_SCORE` (0–100) is computed per ticker, per `as_of` snapshot, independent of
`WEALTH_SCORE`. It detects:

- **Missing data** — % of required fields present across all metrics feeding the component
  scores.
- **Stale data** — gap between `as_of` and the most recent relevant `available_at`; e.g.
  fundamentals older than ~1.5 fiscal quarters relative to `as_of` is flagged stale (a new quarter
  should have been reported by then).
- **Inconsistent data / provider disagreement** — meaningful once a second provider exists per
  domain (Phase 2+); the concept is designed now so it isn't a schema change later.
- **Unusual values** — values outside domain-plausible bounds, flagged (not silently clipped
  without a flag — clipping affects the *score contribution*, the flag affects *Data Quality*).
- **Accounting restatements** — detectable today, without schema changes: `fundamentals_quarterly`
  is keyed by `(instrument_id, period_end, source)`, so the same `period_end` re-ingested with a
  different value and a later `available_at` **is** a restatement signal by construction of the
  Phase 0 schema.
- **Insufficient history** — below the minimum lookback window for growth-consistency/historical-
  valuation calculations; flagged explicitly and reflected in confidence (§15), not silently
  computed from a thin window.

Example from the brief:

```
WEALTH_SCORE = 91, DATA_QUALITY = 98, data_confidence = 94%   → trustworthy thesis
WEALTH_SCORE = 91, DATA_QUALITY = 62, data_confidence = 55%   → same score, NOT the same thesis
```

---

## 17. Scenario Engine

Explicitly rejects naive price multiplication. The chain is:

```
Revenue → Earnings/FCF → Valuation Multiple → Equity Value → ÷ diluted shares → Implied Price
```

For each of `BEAR / BASE / BULL`, the methodology sets scenario-specific assumptions for:

| Driver | Bear | Base | Bull |
|---|---|---|---|
| Revenue growth path | Deceleration / lower reinvestment | Trend/consensus-consistent | Acceleration / operating leverage |
| Margin trajectory (FCF or EBITDA margin) | Compression (competitive pressure, opex deleverage) | Stable, in line with historical trend | Expansion (operating leverage, mix shift) |
| Shares outstanding path | Possible dilutive raise if balance-sheet stress (§6) | Historical buyback/dilution trend continued | Continued buybacks at reasonable prices |
| Exit/terminal multiple | Low percentile of own-history/peer distribution (§11/§12) | Median | High percentile, **capped** — never a naive extrapolation of an already-extreme multiple |

**Assumption anchoring is rule-based, not freehand:** proposed default is 25th/50th/75th
percentile of the company's own trailing growth/margin distribution for Bear/Base/Bull
respectively — fully deterministic, no LLM involved in generating the numbers. The **Wealth
Analyst agent's job is narration only**: explaining *why* each scenario is plausible (drivers,
catalysts), using numbers that were already computed. Output per scenario includes the explicit
assumption set (auditable, not a black box) plus the implied price/return vs current price as of
the snapshot date.

**Fallback for thin history / structural breaks — deterministic mechanism, APPROVED (Critical
Review M6, Rev. 3).** Percentile-anchoring against a company's own trailing distribution is
undefined when that history is too short or contains a structural break that makes the trailing
window internally inconsistent. Both cases now have a defined, mechanical (rule-based, not a
fitted statistical model) detection and fallback:

1. **Thin history.** If the available trailing window is < 12 quarters (3 years — the same minimum
   already established in §11), Bear/Base/Bull assumptions are anchored to **sector-median**
   growth/margin percentiles (from the §12 peer group) instead of the company's own-history
   percentiles, and `data_confidence` is explicitly lowered to reflect the substitution.
2. **Structural break.** A break is detected — mechanically, via simple threshold rules, not a
   fitted econometric break-point test — when **either**:
   - a `CorporateAction`/M&A event within the trailing window represents more than an illustrative
     **30% of pre-event market cap** (**OPEN — needs tuning**) — a "transformative" acquisition; or
   - any single quarter's YoY revenue change (not sequential-quarter, to avoid seasonality false
     positives) exceeds an illustrative **±50%** (**OPEN — needs tuning**).

   When a break is detected, the trailing window used for percentile anchoring is **truncated to
   start after the most recent detected break**. If the resulting post-break window is itself < 12
   quarters, it falls through to the thin-history fallback (case 1) above.

Both thresholds (30% market cap, ±50% YoY revenue) are illustrative and marked **OPEN — needs
real-data tuning**, consistent with how every other band in this document is handled; the
*mechanism* — two simple, deterministic trigger rules plus window truncation plus a thin-history
fallback that itself is already-specified — is the approved part, and requires no further
invented statistical machinery.

---

## 18. Thesis Engine

Produced entirely by the Wealth Analyst agent (the one agent responsible for Wealth Engine
narrative per CLAUDE.md's 6-agent roster), consuming only: component scores, `data_confidence`,
data quality, red flags, moat/management structured evidence, and scenario numbers. Output
structure:

```
Investment Thesis
├── What the company does
├── Why it is attractive
├── Growth drivers
├── Quality drivers
├── Moat
├── Management
├── Capital allocation
├── Valuation
├── Key risks
├── Catalysts
├── Bear case
├── Base case
├── Bull case
└── Invalidation conditions
```

**Grounding rule (testability requirement, see §25):** every quantitative claim in the thesis text
must be traceable to a specific field in the upstream computed payload. The agent is not permitted
to introduce a number that isn't already present in its input.

**`data_confidence` labeling (§15, M7).** When the Wealth Analyst agent references
`data_confidence` in the narrative, it must describe it as confidence in the data/evidence
underlying the analysis, never as confidence in the investment conclusion itself — this is a
grounding-rule violation just like inventing a number would be, and should be covered by the same
testability discipline (§25).

**Invalidation conditions must be falsifiable and machine-checkable**, not vague narrative —
e.g. *"if Net Debt/EBITDA exceeds 4.0x"* or *"if FCF margin drops below X% for 2 consecutive
quarters,"* not *"if the business deteriorates."* This is what makes Visual Intelligence's "what
invalidates the thesis" (§19) something that can eventually be monitored automatically, not just
read.

---

## 19. Visual Intelligence

Per CLAUDE.md, this ships as a **structured object first, no dashboard yet.** This methodology
must persist enough to support, eventually:

`revenue growth trend · EPS growth trend · FCF trend · margins · ROIC · valuation history · peer
valuation · debt evolution · share count · sector relative strength`

— each of which is already a byproduct of §3–§12 computed at every `as_of` snapshot; nothing new
needs to be computed solely for visualization, only persisted (already required by point-in-time
correctness, §22).

Mapping to the four questions:

- **WHAT CHANGED?** — deterministic diff (code) between the current `as_of` snapshot and the prior
  one (or a specified lookback) across every component score and key metric.
- **WHY IT MATTERS?** — LLM narration grounded in the diff: which score moved, does it move
  `WEALTH_SCORE`, does it touch a red flag or an invalidation condition.
- **WHAT COULD HAPPEN?** — tied to the Scenario Engine (§17) and near-term catalysts (next
  earnings date from `EconomicCalendarEvent`, upcoming events), narrated.
- **WHAT INVALIDATES THE THESIS?** — direct pull from §18's invalidation conditions, cross-checked
  against current metric values to show proximity (e.g. *"Net Debt/EBITDA is currently 2.1x;
  invalidation threshold is 4.0x"*).

---

## 20. Macro Context

Variables tracked: `Fed Funds · CPI · PCE · 10Y · 2Y · real yields · DXY · oil · credit spreads ·
GDP · unemployment`.

**Wealth Engine must not become a Macro Engine, and macro must not get double-counted.** Market
Regime already applies a multiplier one layer up, at Opportunity Engine (per the frozen
architecture) — if Wealth Engine's own component scores also flexed with macro, the same effect
would apply twice.

Explicit split:

- **What is allowed to numerically touch a score:** only the cost-of-capital / discount-rate
  assumption used in (a) the ROIC-vs-hurdle-rate comparison (§4) and (b) the Scenario Engine's
  terminal-multiple discounting (§17). Real 10Y yield is the proposed input to that single
  channel. This is a well-understood, narrow mechanism: a higher required return means the same
  cash flows are worth less, independent of any regime-based adjustment happening elsewhere.
- **What is only allowed to touch interpretation/thesis, never the score:** everything else — CPI,
  PCE, employment, GDP, credit spreads, DXY, oil. These are the Macro Analyst agent's and the
  Narrative Synthesizer's raw material for framing risk in prose (e.g. *"in a tightening-credit
  regime, this company's leverage profile deserves more scrutiny"*), never a silent numeric nudge
  to `QUALITY_SCORE` or `GROWTH_SCORE`.

---

## 21. Accounting Quality / Red Flags

A red flag is a structured record, not a score deduction hidden inside a formula:

```
RED_FLAG {
  code, description, severity: LOW | MEDIUM | HIGH,
  evidence: [specific values/dates],
  impact: { affected_scores: [...], mechanism: informational | capped_deduction }
}
```

Registry (consolidating everything referenced across §3–§9):

`EARNINGS_FCF_DIVERGENCE · RECEIVABLES_GROWTH_OUTPACING_REVENUE ·
INVENTORY_GROWTH_OUTPACING_REVENUE · MARGIN_DETERIORATION_TREND · AGGRESSIVE_CAPITALIZATION ·
HIGH_SBC_RELATIVE_TO_FCF · DILUTION_OUTPACING_BUYBACK · ACQUISITION_DRIVEN_GROWTH ·
DEBT_FUNDED_BUYBACKS · UNUSUAL_TAX_EFFECTS · ONE_TIME_GAINS_INFLATING_EARNINGS ·
DECLINING_CASH_CONVERSION · WORKING_CAPITAL_DRIVEN_FCF · RESTATEMENT_DETECTED ·
GUIDANCE_MISS_PATTERN · REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION`

**`REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION` — mechanism APPROVED, closing Critical Review
finding H4 (informational-only behavior also APPROVED; threshold remains OPEN — see below).**
The "melting ice cube" pattern: top-line revenue is shrinking, but cost-cutting-driven margin
expansion makes EBITDA/FCF growth look flat-to-positive in the same window, potentially masking a
structurally declining business inside an otherwise unremarkable `GROWTH_SCORE`. Proposed
deterministic detection, over the same trailing-4Q-vs-prior-4Q window already used for Growth
Acceleration/Deceleration (§3):

```
fires when:
  RevenueGrowth_YoY < 0%
  AND (EBITDAMargin_current − EBITDAMargin_prior) > +X pp     # illustrative X = 2pp, OPEN
  AND EBITDAGrowth_YoY > 0%
```

i.e. revenue is genuinely declining, margin expanded by a non-trivial amount, and that margin
expansion alone is large enough to make EBITDA read as "growing" despite fewer dollars of revenue
coming in the door — the exact combination that produces a misleadingly acceptable `GROWTH_SCORE`
reading. The `+2pp` margin-expansion threshold is **illustrative — OPEN, not approved**, chosen
only to make the proposal concrete; it needs real-data calibration like every other band in this
document.

**Per instruction, this flag is informational only in v1** — it does **not** apply a deduction to
`QUALITY_SCORE` or `GROWTH_SCORE` (unlike the small subset of HIGH-severity flags described above
that do apply a capped deduction). It is surfaced through the same three channels as every other
red flag: the `red_flags` list in the output contract (§24), as grounding input to the Thesis
Engine's "key risks" section (§18), and as a candidate driver for Visual Intelligence's "what
changed" / "what could happen" / "what invalidates the thesis" narrative (§19) — a company that
trips this flag repeatedly across snapshots is exactly the kind of pattern Visual Intelligence
should be able to surface over time.

As the brief requires: a red flag does **not** automatically reduce `WEALTH_SCORE`. Proposed
architecture: flags are always surfaced in the output contract as their own list (informational,
always). A small subset of HIGH-severity flags additionally apply a **documented, deterministic,
capped deduction** to the one specific score they concern (e.g. `DEBT_FUNDED_BUYBACKS` caps
`CAPITAL_ALLOCATION_SCORE` at an illustrative ceiling of 40/100, regardless of how favorable the
raw buyback math looks) — via a fixed lookup table, not LLM discretion. **Unlike Moat/Management,
red flag detection and severity in v1 are proposed as 100% deterministic, no LLM judgment
involved** — flags are inherently more numerically checkable than "does this company have a
moat," so there's no need to import LLM discretion here, and doing so would widen the
LLM-cannot-calculate exception further than necessary.

---

## 22. Point-in-time correctness (Wealth-Engine-specific requirements)

Builds directly on Phase 0's `ProvenanceFields` / `PeriodicRecordFields` — no new primitives
proposed, only their required application:

- Every persisted `wealth_scores` row (and its component sub-scores) must record `as_of` plus,
  inside the existing `inputs` jsonb column, the exact `available_at` cutoff used to select each
  input record. This is what makes *"what would Investment Intelligence have known on
  2025-03-15?"* mechanically answerable: re-run the same scoring code with `as_of='2025-03-15'`,
  and the point-in-time query helper (already scoped in Phase 0's `packages/quant_core/backtest`)
  filters every provider read to `available_at ≤ as_of`.
- **Historical Valuation bands (§11) and Growth Consistency (§3) both build a trailing window of
  past snapshots.** That window must be constructed using only data that was itself
  `available_at`-eligible *at each historical point in the window* — never reconstructed with
  hindsight-revised figures. This is exactly where restatements (§16, §21) become dangerous if
  unhandled: a naive "pull 5 years of fundamentals" query without a per-point `available_at`
  filter would silently leak revised numbers into a supposedly historical band.
- **Moat/Management qualitative assessments are harder to version than a number, but must be
  versioned anyway.** Every such assessment run is stamped with its own `as_of` and the qualitative
  evidence snapshot (which filings/transcripts were `available_at ≤ as_of`) it was allowed to draw
  from — so a backtest replaying March 2025 cannot let the Wealth Analyst cite a 2026 filing.

---

## 23. Universe

Structure only — **no ticker list proposed here**, per instruction. Reuses the `universe_definition`
pattern already designed in Phase 0's `backtests` table rather than inventing a new mechanism.

**Per-instrument fields:** `ticker, sector, industry (sub-industry), market_cap_band, liquidity
(avg daily $ volume), inclusion_date, exclusion_date (nullable), inclusion_rationale,
exclusion_rationale`.

**Proposed inclusion criteria (illustrative, OPEN):**

- Minimum market cap floor (e.g. >$10B — large/mega-cap bias for MVP data quality).
- Minimum liquidity floor (e.g. >$50M/day avg dollar volume).
- Minimum listed history (e.g. ≥5 years public — needed for §3/§11's historical windows).
- Primary listing on a major US exchange (MVP data-provider coverage constraint).
- Sector diversification target — an explicit spread constraint so Universe v1 isn't accidentally
  25 tech names; Wealth Engine must not become a tech-only tool by default.

**Proposed exclusion criteria:**

- Would collide with the Market Context instrument list (CLAUDE.md's Equity Universe vs Market
  Context rule) — a validation check, not a judgment call.
- Acquired/delisted — record `exclusion_date`, **never delete the historical rows** (required for
  backtest integrity).
- Persistently insufficient Data Quality (§16) to score reliably.

**Survivorship considerations — explicitly not fully solved by Universe v1.** Defining the list
"today" and applying it retroactively to backtests is itself a mild survivorship-bias risk unless
`inclusion_date`/`exclusion_date` are respected by the Backtest Engine (a company must not be "in
the universe" for a backtest date before its own `inclusion_date`). This curated list avoids the
most naive form of the bias (using *today's* index membership as if it were historical); it does
**not** fully solve survivorship bias the way true point-in-time index-membership data would —
consistent with the limitation already logged in the architecture freeze (§14 of that document).
Still open from Phase 0's decision list: the actual ~30-ticker composition (§18.2 of the closure
document) — unaffected by this phase.

---

## 24. Output Contract (conceptual — not implemented)

**Type/range semantics — explicit (this round).** Fields typed `0-100` below are normalized
component scores, deterministic outputs of §13's normalization engine (`quality_score`,
`growth_score`, `fcf_score`, `moat_score`, `capital_allocation_score`, `balance_sheet_score`,
`valuation_score`, `wealth_score`, `business_quality_composite`, `data_quality`,
`data_confidence`). `roic` and `roic_ex_goodwill` are **raw financial metrics** (a percentage, per
§4), never normalized — they may be negative (value destruction) or exceed 100%, and per §13's
rule that extreme-but-legitimate values are never hidden, their raw economic value must always be
preserved and surfaced as-is, never clipped to a 0–100 range.

```jsonc
GET /v1/wealth/{ticker}
{
  "ticker": "...", "company_name": "...", "as_of": "2026-08-10",
  "wealth_score": 0-100 | null,           // normalized ranking score, blended — see quadrant fields below. NULL/N/A for Banks or Insurance tickers until §4's Financials sector methodology (C4) is approved — see §4, §14
  "quality_score": 0-100, "growth_score": 0-100, "fcf_score": 0-100,
  "moat_score": 0-100,
  "capital_allocation_score": 0-100,     // informational — does not feed wealth_score, see §14 (C1/H3)
  "balance_sheet_score": 0-100,          // risk modifier — see §14 WEIGHT CHANGE PROPOSAL, §6 (H8)
  "valuation_score": 0-100 | null,       // includes FCF Yield — see §5/§10 (C1). For Banks/Insurance, computable as a diagnostic even when wealth_score is N/A — see §4
  "business_quality_composite": 0-100 | null,   // NEW (C5) — Quality+Growth+FCF+Moat, valuation-free, Python-computed. NULL/N/A for Banks/Insurance (requires quality_score/fcf_score, see §4)
  "valuation_quadrant": "excellent_cheap | excellent_fair | excellent_expensive |
                          weak_cheap | weak_fair | weak_expensive" | null,  // NEW (C5) — 6 states, Python-computed, deterministic. NULL/N/A for Banks/Insurance, same reason as business_quality_composite
  "roic": number,                        // RAW metric (%), NOT normalized 0-100 — may be negative; NEW (H5) — WITH goodwill, feeds quality_score via the normalized ROIC-spread sub-metric
  "roic_ex_goodwill": number,            // RAW metric (%), NOT normalized 0-100 — may be negative; NEW (H5) — diagnostic only, does NOT feed quality_score
  "data_confidence": 0-100,              // RENAMED from "confidence" (M7) — data/evidence confidence, NOT outcome confidence
  "data_quality": 0-100,                 // §16
  "regime": { "market_regime": "...", "macro_regime": "..." },
  "thesis": { /* §18 structure */ },
  "scenarios": { "bear": {...}, "base": {...}, "bull": {...} },   // §17
  "red_flags": [ /* §21 records */ ],
  "key_risks": [...], "catalysts": [...],
  "what_changed": {...}, "why_it_matters": "...",
  "what_could_happen": "...", "invalidation_conditions": [...],   // §18, §19
  "weights_version": "v1.0",
  "inputs": { /* provenance snapshot — §22 */ }
}
```

Every field above traces to a section in this document. Nothing here is implemented.

---

## 25. Testability

- **Purity.** Every score function is `f(data_snapshot, weights_version, as_of) → output`. No
  wall-clock time, no randomness, no hidden global state.
- **Golden-snapshot tests.** A frozen fixture snapshot (company fundamentals/prices/etc. at a
  fixed `as_of`) must produce an exact, asserted component-score and `WEALTH_SCORE` output. Any
  future change to that output must be a deliberate, reviewed test diff — never silent drift.
- **Weights-version pinning.** Tests always reference an explicit `weights_version`, never
  "latest," so future methodology changes don't retroactively break historical golden tests.
- **Reproducibility.** Same snapshot + `as_of` + `weights_version`, run twice → byte-identical
  output. Catches accidental non-determinism (ordering, float precision, unseeded randomness).
- **Qualitative-score auditability.** Moat/Management LLM calls are logged via `agent_runs`
  (already in the frozen schema) with the exact evidence snapshot passed in. Tests cover the
  **aggregation formula only** (fixed structured category ratings as fixture input → asserted
  `MOAT_SCORE`), not the LLM's qualitative judgment itself — that's an evals concern, out of scope
  for unit tests.
- **Red flag detection tests.** Given a fixture with a known divergence pattern, assert the
  expected flag(s) fire with the expected severity.
- **Normalization edge-case tests.** Explicit coverage for missing values, negative/undefined
  ratios, and winsorization boundaries (§13).
- **Mandatory golden test — APPROVED (Critical Review H10, see also §4).** *Rising leverage
  combined with flat or declining margin/asset-turnover terms must not increase `QUALITY_SCORE`.*
  This is a required regression test verifying the DuPont ROE decomposition (§4) actually
  neutralizes leverage-driven ROE improvement — required before `QUALITY_SCORE` is considered
  implementation-complete, not an optional nice-to-have.
- **Quadrant golden test (C5).** Given a fixture with known component scores, assert
  `business_quality_composite` and `valuation_quadrant` match the expected value exactly —
  including at least one fixture per quadrant cell (all 6 combinations from §14) and one fixture
  exercising the `quality_tier` boundary threshold.
- **FCF Conversion / ROE guard tests (C2, C3).** Fixtures with NI ≤ 0 must assert FCF Conversion
  is N/A, not a computed value. Fixtures with book equity ≤ 0 must assert ROE is N/A and that
  `QUALITY_SCORE` falls back to ROIC/ROIIC/margins only.

---

## 26. Decision Log

**Status legend:** `APPROVED` = directed by the human, applied. `ACCEPTED AS KNOWN LIMITATION` =
explicitly acknowledged, deliberately not fixed pending evidence. `PROPOSED` = default
recommendation standing, not yet explicitly ratified. `OPEN` = illustrative value/parameter needs
real-data tuning. `REQUIRES HUMAN APPROVAL` = a real fork, human must pick. `NOT ADDRESSED —
CARRIED OVER` = raised by the Critical Review, not part of any approval round yet, still
unresolved. Rows updated in Rev. 3 are marked accordingly.

### Original decisions (v1) — status after Rev. 2 approval

| # | Decision | Rationale | Alternatives | Trade-off | Status |
|---|---|---|---|---|---|
| 1 | Keep the 5 frozen `wealth` weights unchanged; map Quality/Growth/FCF/Moat/Valuation directly | Respects the freeze; no reason to reopen weights that already sum to 1.0 and match the brief for 5 of 7 components | Reopen all 7 weights now | None — Critical Review found no data-backed basis to change these 5 numbers either | **APPROVED** — user explicitly confirmed no change to `config/weights/v1.0.yaml` |
| 2 | `CAPITAL_ALLOCATION_SCORE` as informational, not weighted into `WEALTH_SCORE` | Fits within frozen weights without modifying them | Fold into `QUALITY_SCORE` as a sub-input; or reopen weights to add an 8th slot | **Explicit consequence now documented (H3):** dilution alone doesn't move `WEALTH_SCORE` directly | **APPROVED** — H3 instruction to "document the behavior" read as confirming this placement |
| 3 | `BALANCE_SHEET_SCORE` as a post-hoc multiplicative risk modifier | Keeps leverage risk visible instead of averaged away (§6); fits within frozen weights | Additive 8th weight; or a hard Risk-Engine-style gate instead of a soft multiplier | Multiplier curve is a new, untested parameter; sector bands are a prerequisite | **REQUIRES HUMAN APPROVAL — still gated.** H8 explicitly blocks approving the multiplier mechanism until sector-specific bands (Utilities done this revision, Financials CET1-based still OPEN) exist. Curve itself unspecified. |
| 4 | New config surface needed for sub-metric weights inside each group | The methodology (§3–§11) implies internal weights `v1.0.yaml` doesn't have | Hardcode sub-weights in code (violates "weights are config, not code") | Adds a new versioned file set to govern | **REQUIRES HUMAN APPROVAL** — not addressed this round |
| 5 | `MOAT_SCORE` aggregates LLM-rated, evidence-gated per-category strengths | Moat has no ratio; some LLM judgment is unavoidable | Purely quantitative proxy only — less accurate but zero LLM-in-scoring exposure | Narrow, explicit exception to "LLM cannot calculate" | **REQUIRES HUMAN APPROVAL** — Critical Review found the boundary well-designed (§7 of that review) but did not itself constitute approval; not addressed in this approval message |
| 6 | Management Quality feeds Capital Allocation Score rather than its own top-level score | No frozen slot exists for it; closely related to capital stewardship | Its own informational score, same treatment as Capital Allocation | Slightly conflates two related-but-distinct judgments | **OPEN** — unchanged |
| 7 | Normalization method matrix (percentile/z-score/min-max/sector-relative/historical, per metric type) | Different metric shapes need different treatment | Single method for all metrics | Simpler, materially less accurate | **PROPOSED** — unchanged |
| 8 | Winsorization at 1st/99th percentile | Standard, simple default | Different thresholds, or IQR-based | Needs real-data tuning | **OPEN** — unchanged |
| 9 | Fixed hurdle rate (~8–10%) instead of per-company WACC in v1 | Full WACC model is Phase 2+ complexity | Full CAPM/WACC per company | Less precise across risk profiles | **PROPOSED** — unchanged |
| 10 | Sector metric profile mapping (§10) | Prevents comparing NVDA/JPM/COST/AMZN on the same multiple | Universal blended valuation formula | More upfront design/maintenance | **PROPOSED** — extended this revision (H6/H7/M4, Financials adaptation) |
| 11 | Historical valuation bands at 10/30/70/90 percentile | Standard, interpretable | Different cut points | Illustrative, needs tuning | **OPEN** — unchanged, now also feeds the C5 valuation-tier collapse |
| 12 | Leverage bands at 1.5/3.0/4.5x Net Debt/EBITDA | Standard credit-analysis heuristics | Different cut points, sector-specific bands | Illustrative, needs tuning | **OPEN** — unchanged for the generic case; Utilities-specific bands added this revision (H8, also OPEN) |
| 13 | `data_confidence` = Data Quality × history-length × evidence-depth roll-up (renamed from `Confidence`, M7) | Keeps confidence deterministic and explainable | LLM self-reported overall confidence | Requires disciplined per-component tracking | **PROPOSED** — field renamed and labeling clarified (M7), formula unchanged |
| 14 | Data Quality staleness threshold ~1.5 fiscal quarters | Reasonable buffer past expected reporting cadence | Tighter/looser threshold | Needs real ingestion-cadence data | **OPEN** — unchanged |
| 15 | Scenario assumptions anchored at 25th/50th/75th percentile of own trailing distribution | Fully deterministic, no LLM in the numbers | LLM proposes scenario assumptions directly | Could underrepresent genuinely novel cases | **PROPOSED** — unchanged; fallback for thin/broken history added this revision as new row 33 |
| 16 | Macro→score channel restricted to cost-of-capital/discount-rate only | Avoids double-counting with Opportunity Engine's regime multiplier | Let more macro variables flex the score directly | Coarser macro sensitivity within Wealth Engine | **PROPOSED** — unchanged |
| 17 | Red flag detection and severity are 100% deterministic (no LLM) | Flags are numerically checkable | Allow LLM-assessed severity | Slightly less nuanced, fully auditable | **PROPOSED** — unchanged |
| 18 | Universe v1 inclusion criteria (market cap/liquidity/history/diversification floors) | Reasonable MVP data-quality gate | Looser criteria to include more names sooner | Smaller, more homogeneous universe | **OPEN** — actual ticker list still pending from Phase 0 closure (§18.2) |
| 19 | Peer Valuation confidence explicitly flagged LOW given ~30-name universe | Honest about a real limitation | Suppress sector valuation entirely until universe grows | Some sector context better than none, if labeled | **PROPOSED** — Critical Review confirmed this finding still stands (review finding L3) |
| 20 | Historical-band construction reuses Phase 0's `available_at` filter helper exclusively | One point-in-time mechanism, not two | Bespoke point-in-time logic inside Wealth Engine | None — safer default | **PROPOSED** — unchanged |

### New decisions from the Critical Review (Rev. 2)

| # | Decision | Status |
|---|---|---|
| 21 | **(C1)** Remove FCF Yield from `FCF_SCORE`; lives exclusively in `VALUATION_SCORE` | **APPROVED — applied** (§5, §10, §14) |
| 22 | **(C2)** FCF Conversion marked N/A whenever Net Income ≤ 0 | **APPROVED — applied** (§5) |
| 23 | **(C3)** ROE marked N/A whenever book equity ≤ $0; Quality falls back to ROIC/ROIIC/margins | **APPROVED — applied, fully specified** (§4). Floor fixed at $0 (hard rule, not tunable). **Rev. 3:** added a second, soft floor (equity < 5% of Total Assets → low-reliability flag, **OPEN**, not excluded). |
| 24 | **(C4)** Financials sector adaptation: exclude ROIC/generic-FCF/Debt-EBITDA, replace with ROE/ROA/Efficiency-Ratio/NIM/CET1 within the same weight slots | **Architecture APPROVED — applied** (§4 consolidated table). **Rev. 3:** added Credit Quality (NPL ratio, provision trend) to the replacement metric set. Exact replacement formulas (Distributable Capital Generation for FCF; ROE/Credit-Quality band calibration for banks; CET1 target) **REQUIRES HUMAN APPROVAL** — genuinely more design work, not invented here. **Blocks scoring any bank/insurer until resolved.** **This round:** `WEALTH_SCORE` eligibility explicitly resolved — diagnostic `valuation_score` may be computed for Banks/Insurance from already-defined §10 metrics, but `WEALTH_SCORE` (and `business_quality_composite`/`valuation_quadrant`) remain **N/A** for these tickers until the blocked components above are approved; see §4, §14, §24. |
| 25 | **(C5)** Expose `business_quality_composite` + `valuation_quadrant`, Python-computed, deterministic thresholds | **Architecture APPROVED — applied, six-cell scheme finalized in Rev. 3** (§14, §24) — a five-state scheme was explicitly shown insufficient (2×3 axes are mutually exclusive/exhaustive, `weak_fair` cannot be merged elsewhere without misclassifying a common case). `quality_tier` cutoff (70) is **OPEN — REQUIRES HUMAN APPROVAL / data-driven tuning**; valuation-tier reuses existing §11 bands (already OPEN there). |
| 26 | **(H2)** Cycle-normalize Growth and Quality for Cyclicals/Energy, reusing §10's existing 5–7yr window | **APPROVED — applied** (§3, §4). No new numeric parameter — reuses an already-established convention. |
| 27 | **(H3)** Explicitly document Capital Allocation informational-only consequence | **APPROVED — applied** (§14). Documentation only. |
| 28 | **(H6)** GAAP-consistent, code-computed EBITDA/EPS as scoring inputs; non-GAAP "adjusted" figures never used | **APPROVED — applied** (§6, §10). **Rev. 3:** added explicit rule — if GAAP components are unavailable, metric is N/A, never backfilled from a reported "Adjusted" figure. |
| 29 | **(H7)** Demote PEG to secondary/diagnostic; fixed forward-1yr horizon; applicable range | **Demotion APPROVED — applied** (§10). Applicable range (5%–40%) is **OPEN — needs tuning**. |
| 30 | **(H8)** Sector-specific leverage bands for Utilities | **Bands added — OPEN, needs real-data tuning** (§6), same status as the original generic bands. Explicitly gates decision #3 (`BalanceSheetMultiplier`) per the Critical Review. |
| 31 | **(H9)** Sector-aware value-trap cross-check for Cyclicals/Energy, using cycle-normalized fundamentals trend | **APPROVED — applied** (§11). Reuses H2's window, no new parameter. |
| 32 | **(H10)** Mandatory golden test: rising leverage + flat margins/turnover must not increase `QUALITY_SCORE` | **APPROVED — applied** (§4, §25). Required before `QUALITY_SCORE` implementation is considered complete. |
| 33 | **(M1)** Forward Growth and Historical Growth normalized against separate distributions | **APPROVED — applied** (§3). Methodology direction only, no new numeric parameter. |
| 34 | **(M2)** Deterministic fallback for persistently-negative-FCF companies | **APPROVED — deterministic mechanism applied in Rev. 3** (§5, §14): sign-safe switch between % FCF Growth and FCF Trajectory (Δ margin, pp) — fully specified, no open parameter, fixes a real sign-flip bug as a side effect. |
| 35 | **(M3)** Gross-margin-band peer matching operationalizes "business-model similarity" | **APPROVED — applied** (§12). Band width (±15pp) is **OPEN — needs tuning**. |
| 36 | **(M4)** Explicit EV formula: Market Cap + Total Debt + Minority Interest + Preferred − Cash | **APPROVED — applied, fully specified** (§10). **Rev. 3:** added explicit unavailable-component treatment (default $0 if not known to exist; N/A if known to exist but unsourced). |
| 37 | **(M5)** Pharma/biotech Moat Durability rubric references known patent expiration dates | **APPROVED — applied** (§8). Qualitative rubric addition, no numeric threshold. |
| 38 | **(M6)** Scenario Engine fallback for thin history / structural breaks | **APPROVED — deterministic mechanism applied in Rev. 3** (§17): sector-median fallback for <12 quarters; structural-break detection via two mechanical threshold rules (30% market-cap M&A event, ±50% YoY revenue jump — both **OPEN, needs tuning**) plus window truncation. |
| 39 | **(M7)** `CONFIDENCE` explicitly labeled as data/evidence confidence, not outcome confidence | **APPROVED — applied, field renamed to `data_confidence` in Rev. 3** (§15, §24) — name change judged more robust than documentation alone. |
| 42 | **(H5)** ROIC Invested Capital goodwill treatment, and intended treatment for serial acquirers | **APPROVED BY EXPLICIT HUMAN DECISION** (this approval message, confirming the Rev. 3 proposal) — not a default or an assumption made unilaterally. The mechanism was drafted in Rev. 3 and is formally ratified here: `ROIC` (feeds `QUALITY_SCORE`) is computed WITH goodwill by design — overpriced M&A should lower it, that is the metric working correctly, not a flaw; `ROIC_ex_goodwill` is added as a diagnostic-only field, never feeding `QUALITY_SCORE`, specifically to isolate acquisition-price effects from underlying operating economics for serial acquirers. Applied in §4, §14, §24. |

### Accepted as a known limitation — explicitly NOT resolved

**H1 is not fixed and this document does not claim otherwise.** The correlation between Quality
and FCF still exists in the methodology exactly as the Critical Review found it. What *is*
approved is the decision to leave it uncorrected until real evidence exists, rather than guess at
a weight adjustment.

| # | Finding | Status |
|---|---|---|
| 40 | **(H1)** Correlated factors (Quality, FCF share a profitability/margin signal) are treated as statistically independent in the linear weighted sum, overstating their combined effective influence | **ACCEPTED AS KNOWN LIMITATION — NOT RESOLVED.** Documented explicitly in §14. The approved decision is narrow: keep `config/weights/v1.0.yaml` frozen and unchanged until empirical/backtest evidence exists — the underlying correlation itself is untouched and unfixed. Revisit once C1's fix has real data behind it. |

### Newly approved this round — mechanism approved, threshold open

| # | Finding | Status |
|---|---|---|
| 41 | **(H4)** No red flag for "growth" composed mainly of margin expansion on a declining top line (the "melting ice cube masked by cost-cutting" pattern) | **MECHANISM AND INFORMATIONAL-ONLY BEHAVIOR APPROVED BY EXPLICIT HUMAN DECISION.** `REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION` is defined in §21 with a deterministic detection rule (revenue YoY < 0% AND margin expansion > threshold AND EBITDA growth > 0%) and cross-referenced from §3. The detection *structure* and the decision to keep it informational-only (no direct `WEALTH_SCORE`/`QUALITY_SCORE`/`GROWTH_SCORE` deduction) are approved and applied. The `+2pp` margin-expansion threshold remains **OPEN / NOT APPROVED / REQUIRES EMPIRICAL CALIBRATION** — not to be hardcoded as final. |

### Implementation Readiness Classification (A/B/C) — Rev. 4

Full-document audit: every mechanism and every numeric parameter, classified so that **no OPEN
number can be mistaken for an approved one** during Phase 1B. "Implementable" below means
"implementable as a mechanism, sourced from a named config constant" — it never means "hardcode
this number as final."

**A — APPROVED AND IMPLEMENTABLE (exact rule, nothing left open)**

| Item | Section |
|---|---|
| C1 — FCF Yield exclusive to `VALUATION_SCORE`, removed from `FCF_SCORE` | §5, §10, §14 |
| C2 — FCF Conversion N/A when Net Income ≤ 0 | §5 |
| C3 hard floor only — ROE N/A when book equity ≤ $0 | §4 |
| M2 — sign-safe FCF Growth ↔ FCF Trajectory switch (corrected disjunction, Rev. 4) | §5, §14 |
| M4 — EV formula + unavailable-component treatment | §10 |
| H3 — Capital Allocation informational-only, documented consequence | §14 |
| H4 — `REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION` detection mechanism + informational-only treatment (no score deduction); threshold NOT included, see Category B | §21, §26 |
| C4 (eligibility only) — `WEALTH_SCORE`, `business_quality_composite`, `valuation_quadrant` = N/A for Banks/Insurance; diagnostic `valuation_score` MAY be computed independently | §4, §14, §24 |
| H5 — ROIC with-goodwill scored, `ROIC_ex_goodwill` diagnostic-only | §4, §14, §24 |
| H6 — GAAP-consistent EBITDA/EPS; N/A (never backfilled) if GAAP unavailable | §6, §10 |
| H7 (partial) — PEG demoted to secondary/diagnostic; horizon fixed at forward-1yr | §10 |
| M5 — Pharma/biotech Moat Durability rubric references patent expiration | §8 |
| C5 (structure only) — six-cell quadrant scheme, 2×3 exhaustive, five-state rejected with proof | §14 |
| H1 — the *decision* (freeze weights, no numeric change without evidence) — trivially implementable as "no code change" | §14 |

**B — ARCHITECTURE/MECHANISM APPROVED, PARAMETER OPEN (mechanism may be coded now, driven by a
named config constant — the illustrative value below must not be hardcoded as final)**

| Parameter | Illustrative value | Section |
|---|---|---|
| C3 soft floor | Equity < 5% of Total Assets | §4 |
| C5 `quality_tier` cutoff | `business_quality_composite ≥ 70` | §14 |
| Historical valuation percentile bands | 10th/30th/70th/90th | §11 |
| Cost-of-capital hurdle rate | 8–10% | §4 |
| Leverage bands, generic | 1.5x / 3.0x / 4.5x Net Debt/EBITDA | §6 |
| Leverage bands, Utilities | 3.5x / 5.0x / 6.0x Net Debt/EBITDA | §6 |
| Winsorization bounds | 1st/99th percentile | §13 |
| H7 — PEG applicable range | 5%–40% growth | §10 |
| M3 — gross-margin peer-band width | ±15 percentage points | §12 |
| Data Quality staleness threshold | ~1.5 fiscal quarters | §16 |
| Cycle-normalization window (shared: H2, H9, §10, §11) | 5–7yr average | §3, §4, §10, §11 |
| Thin-history minimum | 3yr / 12 quarters | §11, §17 |
| M6 — structural-break triggers | 30% market-cap M&A event; ±50% YoY revenue jump | §17 |
| Working-capital-driven-FCF flag threshold | >30% of OCF growth | §5, §21 |
| `DEBT_FUNDED_BUYBACKS` capped-deduction ceiling | 40/100 on Capital Allocation Score | §21 |
| H4 — margin-expansion flag threshold | +2 percentage points | §21 |
| §13 — group-coverage threshold | 60% of a component group's sub-metrics present | §13 |
| §23 — Universe inclusion criteria | Market cap floor >$10B; liquidity floor >$50M/day; minimum listed history ≥5yr | §23 |

**C — REQUIRES HUMAN APPROVAL / BLOCKS IMPLEMENTATION (not a number — a real fork or a missing
design, cannot be worked around with a placeholder constant)**

| Item | Why it's a hard blocker | Section |
|---|---|---|
| C4 — Banks: Quality, FCF, Balance Sheet | No formulas exist for any of the three, only candidate metric names | §4 |
| C4 — Insurance: Quality, FCF, Balance Sheet, and confirmation of Growth/Moat/Management/Capital Allocation/Valuation generic treatment | Not designed at all until this revision named the gap | §4 |
| `BalanceSheetMultiplier` — adopt the mechanism at all, and its curve | Gated on Utilities bands (Category B, at least drafted) **and** on C4 (Category C, not drafted) | §6, §14 |
| New config surface for sub-metric weights within each group | Real architectural fork — where the file lives, how it's versioned | §14 |
| `MOAT_SCORE` LLM-aggregation exception | Reviewed favorably, never formally ratified as a human decision | §8 |
| Management Quality placement (fold into Capital Allocation vs. own score) | Unresolved fork, not a tunable number | §9 |

---

*End of Phase 1A methodology document, Rev. 4. No code, weights file, schema, or dependency was
modified to produce this revision. See §26 for the complete, current status of every decision and
the Implementation Readiness Classification (A/B/C) for a full-document audit of what is truly
implementable today. Summary: M2's real logic contradiction (prior-period-only check missing the
sign-crossing case) is fixed in both prose and pseudocode. C4 is explicitly not closed — Banks and
Insurance are separated, and neither has an approved formula for Quality, FCF, or Balance Sheet;
any such ticker must be marked unsupported until resolved. C3's soft floor, C5's `quality_tier`
cutoff, and every other illustrative number in the document are now explicitly labeled
ILLUSTRATIVE/OPEN/NOT APPROVED — none may be hardcoded as final. H1 remains an accepted,
explicitly-not-fixed known limitation. H4's `REVENUE_DECLINE_MASKED_BY_MARGIN_EXPANSION` detection
mechanism and informational-only treatment are approved; its `+2pp` threshold remains OPEN, not
approved, pending empirical calibration. C4's Banks/Insurance scoring scope is now explicit:
diagnostic valuation metrics may be computed, but `WEALTH_SCORE` stays N/A until the blocked
sector-specific components are approved. H5 is recorded as an explicit human decision in this
approval round, not an assumption made unilaterally.*
