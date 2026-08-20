"""SEC EDGAR XBRL `companyfacts`-based `FundamentalsProvider` — the first live data integration
for the Wealth Engine (Phase 1B). Implements `get_income_statements`/`get_balance_sheets`/
`get_cash_flow_statements` — the three normalized-statement methods `compute_wealth_snapshot`
actually consumes.

Scoped intentionally narrow, per "smallest missing adapter, do not redesign":

- ONE ticker mapping (`TICKER_TO_CIK`) for this integration pass. Extending to another company is
  adding a CIK; nothing structural changes. This is deliberately not a general ticker->CIK
  resolver (SEC does publish a full ticker.json mapping file — using it is a natural next step,
  not attempted here since one real ticker is all this pass requires).
- `get_quarterly_fundamentals` (the legacy flat `FundamentalsRecord` method) is NOT implemented —
  `compute_wealth_snapshot` never calls it, and mapping the same concepts into a second DTO shape
  nothing uses would be scope creep beyond what this integration needs.
- Selects the two most recent FULL FISCAL YEARS from 10-K filings (current + prior, for YoY
  comparisons) — annual, not quarterly, to avoid seasonality noise and match how the methodology
  itself frames YoY growth. A quarterly path is a natural follow-up, not attempted here.
- No API key: SEC EDGAR's fair-access policy requires only a descriptive User-Agent header, not a
  credential (`packages.shared.config.Settings.sec_edgar_user_agent`).

Every field mapped below was verified to exist in this company's actual XBRL facts before being
used (see the implementation report). A genuinely absent concept is left `None` — which correctly
propagates to `MetricResult.na(...)` downstream in `packages.quant_core.fundamentals` — never
approximated from an unrelated tag or fabricated.
"""

from datetime import date

import httpx

from packages.shared.config import settings
from packages.shared.schemas import BalanceSheet, CashFlowStatement, IncomeStatement

TICKER_TO_CIK: dict[str, str] = {
    "AAPL": "0000320193",
    # Extended for MVP-0 (Investment Intelligence vertical slice). Each CIK below was resolved
    # against SEC's own https://www.sec.gov/files/company_tickers.json (never guessed), and each
    # company's live companyfacts response was checked for: the anchor revenue concept
    # (_ANCHOR_REVENUE_CONCEPT), >=2 distinct full-fiscal-year spans, and >=4 distinct
    # single-quarter spans under the existing span-banding logic above — same verification rigor
    # AAPL's own mapping already had, per this module's docstring. No structural code change was
    # needed for any of them (confirming the docstring's "extending is adding a CIK" claim).
    #
    # Field-coverage note, disclosed rather than silently absorbed: not every company tags every
    # concept this provider looks up (MSFT and AMZN are each missing one D&A concept, AMZN is
    # missing CommercialPaper, GOOGL is missing CostOfGoodsAndServicesSold/OperatingExpenses and
    # both D&A concepts). None of this crashes anything — _flow/_instant already return None for
    # an absent concept, which propagates to MetricResult.na(...) downstream, never fabricated —
    # but it does mean GOOGL specifically has fewer OK sub-metrics than AAPL/MSFT/AMZN (e.g.
    # gaap_ebitda needs cogs+operating_expenses+d&a, all three missing for GOOGL, so
    # ebitda_margin/ebitda_growth are N/A for GOOGL where they're OK for the other three).
    "MSFT": "0000789019",
    "AMZN": "0001018724",
    "GOOGL": "0001652044",
}

_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# The one revenue concept used to anchor which fiscal-year periods exist — every other concept is
# looked up against the same period_end/period_start this one identifies, so all statements for a
# given "current"/"prior" pair describe the same fiscal year consistently.
_ANCHOR_REVENUE_CONCEPT = "RevenueFromContractWithCustomerExcludingAssessedTax"

# Span bands (days) used to classify an XBRL duration fact by what it actually covers — the same
# technique already used for the 350-380 full-fiscal-year band, extended for quarterly data
# (Phase 7B). Bands, not exact day counts, because Apple's 52/53-week fiscal calendar shifts each
# year's quarter boundaries by up to ~7 days (verified against real AAPL data: single-quarter
# spans of 90 AND 97 days both occur for genuine single quarters, YTD-through-Q2 spans of 181 and
# 188, YTD-through-Q3 spans of 272 and 279 — all confirmed real, not noise).
_SINGLE_QUARTER_SPAN = (80, 100)
_TWO_QUARTER_YTD_SPAN = (165, 200)
_THREE_QUARTER_YTD_SPAN = (255, 290)


class SecEdgarError(RuntimeError):
    pass


class SecEdgarFundamentalsProvider:
    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            headers={"User-Agent": settings.sec_edgar_user_agent}, timeout=30.0
        )
        self._facts_cache: dict[str, dict] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "SecEdgarFundamentalsProvider":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- internal: fetch + lookup -------------------------------------------------------------

    def _cik_for(self, ticker: str) -> str:
        cik = TICKER_TO_CIK.get(ticker.upper())
        if cik is None:
            raise SecEdgarError(
                f"No CIK mapping for {ticker!r} — this provider is scoped to "
                f"{sorted(TICKER_TO_CIK)} only for this integration pass"
            )
        return cik

    def _facts(self, ticker: str) -> dict:
        if ticker not in self._facts_cache:
            cik = self._cik_for(ticker)
            response = self._client.get(_COMPANY_FACTS_URL.format(cik=cik))
            response.raise_for_status()
            self._facts_cache[ticker] = response.json().get("facts", {}).get("us-gaap", {})
        return self._facts_cache[ticker]

    def _concept_known(self, ticker: str, concept: str) -> bool:
        """Whether this company reports the concept AT ALL (any period) — the M4 "known to
        exist" signal, not "has a value for this specific period"."""
        return concept in self._facts(ticker)

    def _full_fiscal_years(self, ticker: str) -> list[dict]:
        """Most recent distinct full-fiscal-year (350-380 day span) 10-K entries for the anchor
        revenue concept, most recent first.

        PIT semantics (hardened, Phase 7A): the same period_end is often mentioned in more than
        one 10-K — its own original filing, and again as a stale comparative in later filings
        (SEC income statements commonly show 2-3 years of comparatives). Naively keeping
        whichever mention has the latest `filed` (the pre-7A behavior) conflates two different
        questions: which VALUE is authoritative (latest is right) vs. WHEN the period first
        became knowable (earliest is right, unless the value itself changed). That conflation
        never produces look-ahead — the error can only push `available_at` later than the truth,
        never earlier — but it does silently understate how early a period was actually knowable,
        which matters once more than the 2 most recent years are ever retrieved (verified
        empirically against AAPL's real facts: every historical period_end's value is identical
        across every one of its mentions in this data — no genuine restatement exists here).

        Corrected rule, per period_end, over every 10-K mention that reports it — see
        `_resolve_first_available` (shared with the quarterly derivation below, Phase 7B, so the
        rule is defined exactly once).
        """
        facts = self._facts(ticker)
        entries = facts.get(_ANCHOR_REVENUE_CONCEPT, {}).get("units", {}).get("USD", [])
        candidates = []
        for e in entries:
            if e.get("form") != "10-K" or "start" not in e:
                continue
            span_days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
            if 350 <= span_days <= 380:
                candidates.append(e)

        mentions_by_end: dict[str, list[dict]] = {}
        for e in candidates:
            mentions_by_end.setdefault(e["end"], []).append(e)

        resolved = {end: self._resolve_first_available(mentions) for end, mentions in mentions_by_end.items()}
        return sorted(resolved.values(), key=lambda x: x["end"], reverse=True)

    @staticmethod
    def _resolve_first_available(mentions: list[dict]) -> dict:
        """PIT-hardening rule (Phase 7A, generalized in 7B for reuse): given every mention of the
        same exact (start, end) period across possibly-different filings, pick ONE, correctly
        dated.

        - All mentions agree on `val` (the common case): the mention with the EARLIEST `filed` —
          the true first-availability date. A later filing merely repeating the same figure as a
          stale comparative must not push `available_at` later than the truth.
        - Mentions disagree on `val` (a genuine restatement): the mention with the LATEST `filed`
          — still the most authoritative value — correctly stamped with THAT mention's own filing
          date, not an earlier, now-superseded one.

        Never produces look-ahead either way: the earliest-filed branch cannot predate the actual
        original filing (it IS the original filing), and the latest-filed branch only occurs when
        a value genuinely changed, dated to when that change actually happened.
        """
        if len({m["val"] for m in mentions}) == 1:
            return min(mentions, key=lambda m: m["filed"])
        return max(mentions, key=lambda m: m["filed"])

    # -- quarterly derivation (Phase 7B) -------------------------------------------------------
    #
    # Verified against real AAPL data (every fiscal year 2019-2026): SEC filers report BOTH the
    # single-quarter AND the YTD-cumulative dimension for the same concept in the same 10-Q for
    # Q2 and Q3 (Q1 has only one dimension, since YTD-through-Q1 IS Q1). This means the SAFER,
    # PREFERRED source for a quarter's value is always the directly-tagged single-quarter fact,
    # never a subtraction — subtraction is only used as a FALLBACK when no direct single-quarter
    # fact exists, and confirmed, when cross-checked against AAPL's own directly-tagged figures,
    # to produce identical values. Q4 is the one quarter with no direct-tag option at all (no
    # filer ever submits a discrete Q4 report) — it is always derived as
    # `FY_total (10-K) - YTD_through_Q3`.

    @staticmethod
    def _span_days(e: dict) -> int:
        return (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days

    def _entries_in_span(
        self, ticker: str, concept: str, fy_start: str, fy_end: str, span_band: tuple[int, int],
        *, anchored_at_fy_start: bool = False,
    ) -> list[dict]:
        """Every distinct duration fact for `concept` within one fiscal year whose span falls in
        `span_band`, PIT-resolved per distinct (start, end) via `_resolve_first_available`,
        earliest end first. `anchored_at_fy_start=True` restricts to facts starting exactly at the
        fiscal year's own start — the shape every YTD-cumulative fact has (it always accumulates
        from the fiscal year's beginning), used to distinguish a YTD fact from an unrelated
        mid-year duration fact of similar length."""
        facts = self._facts(ticker)
        entries = facts.get(concept, {}).get("units", {}).get("USD", [])
        matches = [
            e for e in entries
            if "start" in e and fy_start <= e["start"] and e["end"] <= fy_end
            and span_band[0] <= self._span_days(e) <= span_band[1]
            and (not anchored_at_fy_start or e["start"] == fy_start)
        ]
        by_period: dict[tuple[str, str], list[dict]] = {}
        for e in matches:
            by_period.setdefault((e["start"], e["end"]), []).append(e)
        resolved = [self._resolve_first_available(mentions) for mentions in by_period.values()]
        return sorted(resolved, key=lambda e: e["end"])

    def get_quarterly_revenue(self, ticker: str, num_quarters: int = 20) -> list[IncomeStatement]:
        """Single-quarter Revenue series, most recent first, up to `num_quarters` quarters across
        as many fiscal years as `_full_fiscal_years` resolves. Only `revenue` is populated on each
        `IncomeStatement` — every other field is `None`: this pass verified single-quarter vs.
        YTD disambiguation and quarter derivation only for the anchor revenue concept against real
        AAPL data, not for cogs/net_income/other concepts, and populating them here would be an
        unverified claim (continuity brief's no-invention rule).

        Per fiscal year: Q1 is read directly (no derivation possible or needed — YTD-through-Q1 IS
        Q1). Q2 and Q3 prefer their own directly-tagged single-quarter fact; if genuinely absent,
        each falls back to `this_quarter's_YTD - previous_quarter's_value` — but ONLY when both
        required inputs are actually present, and only chained forward (Q3's fallback needs Q2
        already resolved, whether Q2 itself came from a direct tag or a fallback). Q4 has no
        direct-tag option at all and is always `FY_total - YTD_through_Q3`, computed only when
        both those inputs exist. Any quarter that cannot be established this way — no direct fact
        and no safely-derivable fallback — is simply omitted from the result for that fiscal year;
        never fabricated, never approximated from a partial or unrelated figure.

        Each returned quarter's `reported_at`/`available_at` reflects the true first-availability
        date of whatever it depends on (PIT-hardened, reusing `_resolve_first_available` for
        direct facts); a derived quarter's date is the later of its two inputs' own dates, since
        it cannot be known before both are.
        """
        statements: list[IncomeStatement] = []
        for fy_entry in self._full_fiscal_years(ticker):
            fy_start, fy_end = fy_entry["start"], fy_entry["end"]
            concept = _ANCHOR_REVENUE_CONCEPT

            direct_quarters = self._entries_in_span(ticker, concept, fy_start, fy_end, _SINGLE_QUARTER_SPAN)
            by_start = {e["start"]: e for e in direct_quarters}

            q1 = by_start.get(fy_start)

            q2 = by_start.get(q1["end"]) if q1 is not None else None
            if q2 is None and q1 is not None:
                ytd2 = self._entries_in_span(
                    ticker, concept, fy_start, fy_end, _TWO_QUARTER_YTD_SPAN, anchored_at_fy_start=True
                )
                if ytd2:
                    y2 = ytd2[0]
                    q2 = {
                        "start": q1["end"], "end": y2["end"], "val": y2["val"] - q1["val"],
                        "filed": max(y2["filed"], q1["filed"]),
                    }

            q3 = by_start.get(q2["end"]) if q2 is not None else None
            if q3 is None and q2 is not None:
                ytd3 = self._entries_in_span(
                    ticker, concept, fy_start, fy_end, _THREE_QUARTER_YTD_SPAN, anchored_at_fy_start=True
                )
                if ytd3:
                    y3 = ytd3[0]
                    two_q_val = q1["val"] + q2["val"]  # safe: q1 and q2 are both already resolved
                    q3 = {
                        "start": q2["end"], "end": y3["end"], "val": y3["val"] - two_q_val,
                        "filed": max(y3["filed"], q2["filed"]),
                    }

            for q in (q1, q2, q3):
                if q is not None:
                    statements.append(
                        IncomeStatement(
                            ticker=ticker, period_end=q["end"], reported_at=q["filed"],
                            available_at=self._available_at(q["filed"]), source="sec_edgar",
                            revenue=float(q["val"]),
                        )
                    )

            covers_fy_end = any(q is not None and q["end"] == fy_end for q in (q1, q2, q3))
            if not covers_fy_end:
                ytd3 = self._entries_in_span(
                    ticker, concept, fy_start, fy_end, _THREE_QUARTER_YTD_SPAN, anchored_at_fy_start=True
                )
                if ytd3:
                    y3 = ytd3[0]
                    q4_val = fy_entry["val"] - y3["val"]
                    q4_filed = max(fy_entry["filed"], y3["filed"])
                    statements.append(
                        IncomeStatement(
                            ticker=ticker, period_end=fy_end, reported_at=q4_filed,
                            available_at=self._available_at(q4_filed), source="sec_edgar",
                            revenue=float(q4_val),
                        )
                    )
                # else: Q4 not safely derivable for this fiscal year (missing FY total or missing
                # Q3-YTD) — omitted, not fabricated.

            if len(statements) >= num_quarters:
                break

        statements.sort(key=lambda s: s.period_end, reverse=True)
        return statements[:num_quarters]

    def _flow(
        self, ticker: str, concept: str, period_end: str, period_start: str, unit: str = "USD"
    ) -> float | None:
        # `unit` defaults to "USD" — correct for every flow concept this provider maps except one:
        # WeightedAverageNumberOfDilutedSharesOutstanding is share-denominated, tagged under
        # units.shares in SEC's XBRL facts, not units.USD (verified against AAPL's live
        # companyfacts response). Passing unit="shares" at that one call site is the fix; every
        # other caller is unaffected by this default.
        facts = self._facts(ticker)
        entries = facts.get(concept, {}).get("units", {}).get(unit, [])
        matches = [e for e in entries if e.get("end") == period_end and e.get("start") == period_start]
        if not matches:
            return None
        return float(max(matches, key=lambda e: e["filed"])["val"])

    def _instant(self, ticker: str, concept: str, period_end: str) -> float | None:
        facts = self._facts(ticker)
        entries = facts.get(concept, {}).get("units", {}).get("USD", [])
        matches = [e for e in entries if e.get("end") == period_end and "start" not in e]
        if not matches:
            return None
        return float(max(matches, key=lambda e: e["filed"])["val"])

    @staticmethod
    def _available_at(filed: str) -> str:
        # SEC EDGAR reports a filing DATE, not an intraday timestamp — treat it as available at
        # end-of-day UTC. Disclosed, reversible simplification; no intraday filing-time data
        # exists in this API to do better.
        return f"{filed}T23:59:59Z"

    # -- FundamentalsProvider (partial — see module docstring) ---------------------------------

    def get_income_statements(self, ticker: str, as_of: date | None = None) -> list[IncomeStatement]:
        statements = []
        for entry in self._full_fiscal_years(ticker)[:2]:
            end, start, filed = entry["end"], entry["start"], entry["filed"]
            statements.append(
                IncomeStatement(
                    ticker=ticker, period_end=end, reported_at=filed,
                    available_at=self._available_at(filed), source="sec_edgar",
                    revenue=entry["val"],
                    cogs=self._flow(ticker, "CostOfGoodsAndServicesSold", end, start),
                    operating_expenses=self._flow(ticker, "OperatingExpenses", end, start),
                    net_income=self._flow(ticker, "NetIncomeLoss", end, start),
                    diluted_shares_outstanding=self._flow(
                        ticker, "WeightedAverageNumberOfDilutedSharesOutstanding", end, start,
                        unit="shares",
                    ),
                    interest_expense=self._flow(ticker, "InterestExpense", end, start),
                    # EBIT proxy: OperatingIncomeLoss — same approximation already disclosed in
                    # packages/engines/wealth_engine/pipeline.py's NOPAT-from-EBIT comment.
                    ebit=self._flow(ticker, "OperatingIncomeLoss", end, start),
                    stock_based_compensation=self._flow(ticker, "ShareBasedCompensation", end, start),
                )
            )
        return statements

    def get_balance_sheets(self, ticker: str, as_of: date | None = None) -> list[BalanceSheet]:
        statements = []
        for entry in self._full_fiscal_years(ticker)[:2]:
            end, filed = entry["end"], entry["filed"]
            debt_components = [
                self._instant(ticker, c, end)
                for c in ("LongTermDebtNoncurrent", "LongTermDebtCurrent", "CommercialPaper")
            ]
            total_debt = sum(c for c in debt_components if c is not None) if any(
                c is not None for c in debt_components
            ) else None
            statements.append(
                BalanceSheet(
                    ticker=ticker, period_end=end, reported_at=filed,
                    available_at=self._available_at(filed), source="sec_edgar",
                    total_assets=self._instant(ticker, "Assets", end),
                    total_debt=total_debt,
                    cash_and_equivalents=self._instant(ticker, "CashAndCashEquivalentsAtCarryingValue", end),
                    minority_interest=self._instant(ticker, "MinorityInterest", end),
                    minority_interest_known=self._concept_known(ticker, "MinorityInterest"),
                    preferred_equity=self._instant(ticker, "PreferredStockValue", end),
                    preferred_equity_known=self._concept_known(ticker, "PreferredStockValue"),
                    book_equity=self._instant(ticker, "StockholdersEquity", end),
                    goodwill=self._instant(ticker, "Goodwill", end),
                    inventory=self._instant(ticker, "InventoryNet", end),
                    receivables=self._instant(ticker, "AccountsReceivableNetCurrent", end),
                )
            )
        return statements

    def get_cash_flow_statements(self, ticker: str, as_of: date | None = None) -> list[CashFlowStatement]:
        statements = []
        for entry in self._full_fiscal_years(ticker)[:2]:
            end, start, filed = entry["end"], entry["start"], entry["filed"]
            d_and_a = self._flow(ticker, "DepreciationDepletionAndAmortization", end, start)
            if d_and_a is None:
                d_and_a = self._flow(ticker, "DepreciationAmortizationAndAccretionNet", end, start)
            statements.append(
                CashFlowStatement(
                    ticker=ticker, period_end=end, reported_at=filed,
                    available_at=self._available_at(filed), source="sec_edgar",
                    operating_cash_flow=self._flow(ticker, "NetCashProvidedByUsedInOperatingActivities", end, start),
                    depreciation_amortization=d_and_a,
                    capex=self._flow(ticker, "PaymentsToAcquirePropertyPlantAndEquipment", end, start),
                    # IncreaseDecreaseInOperatingCapital is not tagged for this company — left
                    # None, not derived from other line items (would be an invented figure).
                    delta_working_capital=None,
                )
            )
        return statements
