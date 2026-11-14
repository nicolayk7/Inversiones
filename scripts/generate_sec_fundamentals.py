"""SEC EDGAR -> docs/data/sec/{TICKER}.json — official annual fundamentals for the static site.

Second, independent data source for the Finviz snapshot mirror (docs/README.md). Finviz is a
third-party aggregator; SEC EDGAR is where the numbers originate — the XBRL facts each company
files with its own 10-K. Free, no API key, no account: `data.sec.gov` only asks for a descriptive
User-Agent (https://www.sec.gov/os/webmaster-faq#developers), read from SEC_EDGAR_USER_AGENT
(`packages.shared.config.Settings.sec_edgar_user_agent`).

Like the rest of the site, every number written here is either the company's own filed value or
plain arithmetic on two of them (FCF = operating cash flow - capex). No LLM, no estimates.

Kept apart from `packages/providers/fundamentals/sec_edgar.py` on purpose: that provider feeds the
Wealth Engine (phase-gated platform code, a hand-verified CIK list, point-in-time "as first
reported" semantics). This script serves a display page for ~520 companies and needs broad
concept fallbacks and "as currently reported" values instead — changing the provider to fit
would change what the Wealth Engine computes.

What gets extracted, per company (us-gaap taxonomy, USD only):

- The last `_YEARS` full fiscal years, identified from 10-K duration facts spanning 350-380 days
  (52/53-week fiscal calendars shift year ends by a few days). Each year is labeled by the
  calendar year its fiscal period ENDS in (Apple's year ending 2026-09-26 -> "FY2026"), which is
  also how Finviz labels its annual bars — the site's cross-check depends on that.
- For each fiscal year and metric, the FIRST concept in the metric's priority list that has a
  value for that exact period end. Per year, not per company: companies switch concepts over
  time (Apple tagged `Revenues` until 2018, then `RevenueFromContractWithCustomer...`).
  Revenue has its own rule (_resolve_revenue): the company's tagged total when there is one
  (Berkshire: Revenues 371B vs. contract revenue 247B), otherwise the largest of several partial
  measures, including bank net revenue (net interest + non-interest income), since contract
  revenue alone misses a bank's interest and a REIT's rent.
- When several filings report the same period (the original 10-K, then next years' comparative
  columns, sometimes restated), the most recently filed value wins — "as currently reported",
  which is what Finviz and the companies' own latest reports show. `first_filed` records when
  each fiscal year was first published (its original 10-K) as provenance.
- Absent concepts stay null, never approximated. Banks and insurers usually tag no capex, so
  their FCF is null rather than a meaningless OCF-only figure.

Companies with no 10-K data (foreign issuers filing 20-F, typically IFRS or non-USD) get a small
file with status "no_10k" so the site can say why the section is missing; ETFs get no file.

Before publishing, the SEC entity name must share a meaningful word with the site's company name
(names_match): a wrong ticker->CIK mapping would otherwise show another company's numbers.

Failure handling mirrors generate_finviz_snapshot_site.py: retries on 429/5xx/network errors, a
failing ticker keeps its previous file, full runs delete files for tickers no longer listed, and
if most fetches fail the run aborts without writing anything.

Usage:
    python scripts/generate_sec_fundamentals.py              # all equities in docs/data/index.json
    python scripts/generate_sec_fundamentals.py AAPL JPM     # just these (no orphan cleanup)
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from packages.shared.config import settings  # noqa: E402

logger = logging.getLogger("generate_sec_fundamentals")

_DATA_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"
_OUTPUT_DIR = _DATA_DIR / "sec"

# Ticker -> CIK. SEC's own current list first; it rejects generic User-Agents, so when it answers
# 403 (no SEC_EDGAR_USER_AGENT set) each ticker is looked up in EDGAR's company-search index
# instead, which is rebuilt daily. NOT www.sec.gov/include/ticker.txt: that file is years stale —
# it lacks every listing since ~2022 (GEHC, KVUE, GEV...) and maps BNY to an unrelated CIK.
_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index?keysTyped={ticker}"
_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_FILING_INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_nodash}/"
_DEFAULT_USER_AGENT = "investment-intelligence-dev (set SEC_EDGAR_USER_AGENT in .env)"

_YEARS = 5
_ANNUAL_SPAN_DAYS = (350, 380)
_ANNUAL_FORMS = ("10-K", "10-K/A")

# SEC's fair-access limit is 10 requests/second; one request per ~0.25 s stays well under it even
# counting retries.
_REQUEST_DELAY_SECONDS = 0.25
_RETRY_DELAYS = (2.0, 6.0)
_RETRY_STATUSES = {429, 500, 502, 503, 504}

# Revenue, per fiscal year (see _resolve_revenue):
# 1. A tagged company-wide total, first of _REVENUE_TOTALS. It can be SMALLER than contract
#    revenue and still be right: Williams nets commodity-derivative losses into Revenues ($11.95B,
#    as Finviz shows) below its $14.9B of contract revenue.
_REVENUE_TOTALS = [
    "Revenues",
    "RevenuesNetOfInterestExpense",
    "RegulatedAndUnregulatedOperatingRevenue",  # utilities (DTE)
]
# 2. Otherwise — or if that "total" is under half the largest measure below, i.e. a partial line
#    tagged as Revenues — the LARGEST of these. Each under-counts the total: contract revenue
#    leaves out lease and interest income (Camden, a REIT: $13M of contract revenue vs. ~$1.6B of
#    rent; Huntington, a bank: $1.6B of fees vs. $8B of net revenue), lease income alone leaves
#    out everything else (Copart: $17M). The largest is the closest to the real total.
_REVENUE_PARTIALS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "OperatingLeaseLeaseIncome",
]
_REVENUE_TOTAL_MIN_SHARE = 0.5
_REVENUE_CANDIDATES = _REVENUE_TOTALS + _REVENUE_PARTIALS
# ... plus, for banks, net revenue = net interest income + non-interest income (the standard
# bank "total revenue"; JPMorgan's own tagged Revenues is exactly this measure).
_BANK_NET_INTEREST, _BANK_NONINTEREST = "InterestIncomeExpenseNet", "NoninterestIncome"
_BANK_REVENUE_NOTE = "= InterestIncomeExpenseNet + NoninterestIncome"
# Contract revenue INCLUDING excise taxes over-counts (Brown-Forman: $5.1B vs. $3.9B net), so it
# only joins when the same year has no tax-excluded figure (Copart and Wynn tag only this one).
_REVENUE_INCL_TAX = "RevenueFromContractWithCustomerIncludingAssessedTax"
_REVENUE_EXCL_TAX = "RevenueFromContractWithCustomerExcludingAssessedTax"

# (key, Spanish label, concept priority list, unit, "duration" | "instant"). "revenue" lists every
# concept it may read; its selection rule is _resolve_revenue, not list order.
METRICS: list[tuple[str, str, list[str], str, str]] = [
    ("revenue", "Ingresos", _REVENUE_CANDIDATES + [_REVENUE_INCL_TAX], "USD", "duration"),
    ("operating_income", "Resultado operativo", ["OperatingIncomeLoss"], "USD", "duration"),
    ("net_income", "Beneficio neto", [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",  # Truist tags no NetIncomeLoss
        "ProfitLoss",
    ], "USD", "duration"),
    ("eps_diluted", "BPA diluido", ["EarningsPerShareDiluted"], "USD/shares", "duration"),
    ("operating_cash_flow", "Flujo de caja operativo", [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ], "USD", "duration"),
    ("capex", "Capex", [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ], "USD", "duration"),
    ("equity", "Patrimonio neto", [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ], "USD", "instant"),
]
# Which fiscal years exist: the first of these metrics with any 10-K years.
_ANCHOR_METRICS = ("net_income", "revenue", "operating_cash_flow")


class SecFetchError(Exception):
    """A request that failed after retries, or returned a non-retryable error status."""


class SecNotFoundError(SecFetchError):
    """404: SEC has no XBRL company facts for this CIK."""


# -- pure extraction (no I/O) --------------------------------------------------------------------


def _span_days(entry: dict) -> int | None:
    if "start" not in entry:
        return None
    return (date.fromisoformat(entry["end"]) - date.fromisoformat(entry["start"])).days


def _annual_entries(gaap: dict, concept: str, unit: str, kind: str) -> dict[str, list[dict]]:
    """period_end -> every 10-K entry for that concept/unit covering a full fiscal year (duration)
    or reported at a fiscal year end (instant; filtered to anchor year ends by the caller)."""
    entries = gaap.get(concept, {}).get("units", {}).get(unit, [])
    out: dict[str, list[dict]] = {}
    for e in entries:
        if e.get("form") not in _ANNUAL_FORMS:
            continue
        span = _span_days(e)
        if kind == "duration":
            if span is None or not (_ANNUAL_SPAN_DAYS[0] <= span <= _ANNUAL_SPAN_DAYS[1]):
                continue
        elif span is not None:
            continue
        out.setdefault(e["end"], []).append(e)
    return out


def _latest_filed(entries: list[dict]) -> dict:
    return max(entries, key=lambda e: (e.get("filed", ""), e.get("accn", "")))


def _value(by_concept: dict[str, dict[str, list[dict]]], concept: str, end: str):
    entries = by_concept.get(concept, {}).get(end)
    return _latest_filed(entries)["val"] if entries else None


def _resolve_revenue(by_concept: dict[str, dict[str, list[dict]]], end: str) -> tuple[float | None, str | None]:
    """(value, concept or formula) for one fiscal year; rules documented at _REVENUE_TOTALS."""
    partials = [(v, c) for c in _REVENUE_PARTIALS if (v := _value(by_concept, c, end)) is not None]
    nii, nonii = _value(by_concept, _BANK_NET_INTEREST, end), _value(by_concept, _BANK_NONINTEREST, end)
    if nii is not None and nonii is not None:
        partials.append((nii + nonii, _BANK_REVENUE_NOTE))
    if _value(by_concept, _REVENUE_EXCL_TAX, end) is None:
        incl = _value(by_concept, _REVENUE_INCL_TAX, end)
        if incl is not None:
            partials.append((incl, _REVENUE_INCL_TAX))
    best_partial = max(partials, key=lambda vc: vc[0]) if partials else None
    total = next(((v, c) for c in _REVENUE_TOTALS if (v := _value(by_concept, c, end)) is not None), None)
    if total and (best_partial is None or total[0] >= _REVENUE_TOTAL_MIN_SHARE * best_partial[0]):
        return total
    return best_partial or (None, None)


def extract_annual_fundamentals(facts: dict, years: int = _YEARS) -> dict:
    """companyfacts JSON -> {"status", "years", "metrics", "latest_10k"} (see module docstring).
    `status` is "ok", or "no_10k" when no full fiscal year could be found in us-gaap USD facts."""
    gaap = facts.get("facts", {}).get("us-gaap", {})

    # metric key -> concept -> period_end -> 10-K entries
    per_metric: dict[str, dict[str, dict[str, list[dict]]]] = {
        key: {c: _annual_entries(gaap, c, unit, kind) for c in concepts}
        for key, _, concepts, unit, kind in METRICS
    }
    for concept in (_BANK_NET_INTEREST, _BANK_NONINTEREST):
        per_metric["revenue"][concept] = _annual_entries(gaap, concept, "USD", "duration")

    anchor_key, anchor_ends = None, []
    for key in _ANCHOR_METRICS:
        ends = sorted({end for by_end in per_metric[key].values() for end in by_end})
        if ends:
            anchor_key, anchor_ends = key, ends
            break
    if not anchor_ends:
        return {"status": "no_10k"}

    def anchor_entries(end: str) -> list[dict]:
        return [e for by_end in per_metric[anchor_key].values() for e in by_end.get(end, [])]

    ends = anchor_ends[-years:]
    year_rows = [
        {"period_end": end, "label": f"FY{end[:4]}", "first_filed": min(e["filed"] for e in anchor_entries(end))}
        for end in ends
    ]

    metrics = []
    for key, label, concepts, unit, _ in METRICS:
        values, used = [], []
        for end in ends:
            if key == "revenue":
                value, concept_used = _resolve_revenue(per_metric[key], end)
            else:
                value, concept_used = next(
                    ((v, c) for c in concepts if (v := _value(per_metric[key], c, end)) is not None),
                    (None, None),
                )
            values.append(value)
            used.append(concept_used)
        metrics.append({"key": key, "label": label, "unit": unit, "values": values, "concepts": used})

    by_key = {m["key"]: m for m in metrics}
    ocf, capex = by_key["operating_cash_flow"]["values"], by_key["capex"]["values"]
    fcf = [o - c if o is not None and c is not None else None for o, c in zip(ocf, capex)]
    capex_idx = next(i for i, m in enumerate(metrics) if m["key"] == "capex")
    metrics.insert(capex_idx + 1, {
        "key": "free_cash_flow", "label": "Flujo de caja libre", "unit": "USD", "values": fcf,
        "concepts": ["= flujo de caja operativo - capex" if v is not None else None for v in fcf],
    })

    # The most recent 10-K: the newest filing among the anchor metric's annual entries.
    newest = _latest_filed([e for end in anchor_ends for e in anchor_entries(end)])
    return {
        "status": "ok",
        "years": year_rows,
        "metrics": metrics,
        "latest_10k": {"accession": newest["accn"], "filed": newest["filed"], "form": newest["form"]},
    }


def parse_company_tickers(payload: dict) -> dict[str, list[tuple[int, str]]]:
    """SEC company_tickers.json -> {"AAPL": [(320193, "Apple Inc.")], ...}. A ticker can appear
    more than once (BAC was once also listed under "BofA Finance LLC"); all entries are kept, in
    file order, and _pick_cik chooses by company name."""
    out: dict[str, list[tuple[int, str]]] = {}
    for row in payload.values():
        out.setdefault(str(row["ticker"]).upper().replace(".", "-"), []).append(
            (int(row["cik_str"]), str(row.get("title") or "")))
    return out


def _pick_cik(entries: list[tuple[int, str]], site_name: str | None) -> tuple[int, str]:
    """(cik, SEC title): the first entry whose title matches the site's name, else the first."""
    return next(((cik, title) for cik, title in entries if names_match(title, site_name)), entries[0])


def search_hit(payload: dict, ticker: str) -> tuple[int, str] | None:
    """EDGAR company-search response -> (CIK, entity name) of the entity listing exactly this
    ticker, else None."""
    for hit in payload.get("hits", {}).get("hits", []):
        source = hit.get("_source", {})
        listed = source.get("tickers") or ""
        if ticker.upper() in {t.strip().upper().replace(".", "-") for t in listed.split(",")}:
            if str(hit.get("_id", "")).isdigit():
                return int(hit["_id"]), str(source.get("entity") or "")
    return None


def cik_from_search(payload: dict, ticker: str) -> int | None:
    hit = search_hit(payload, ticker)
    return hit[0] if hit else None


_NAME_NOISE = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "companies", "the", "plc", "ltd",
    "limited", "holdings", "holding", "group", "sa", "nv", "ag", "se", "lp", "llc", "of", "and",
    "class", "new", "de", "com",
}


def _name_tokens(name: str) -> list[str]:
    lowered = name.lower().replace("&", " and ").replace("'", "").replace("’", "")
    cleaned = "".join(ch if ch.isalnum() else " " for ch in lowered)
    return [w for w in cleaned.split() if w not in _NAME_NOISE]


def _names_overlap(a: list[str], b: list[str]) -> bool:
    if set(a) & set(b):
        return True
    joined_a, joined_b = "".join(a), "".join(b)
    # Run-together words: "ConocoPhillips" vs. "Conoco Phillips".
    if any(len(w) >= 4 and w in joined_b for w in a) or any(len(w) >= 4 and w in joined_a for w in b):
        return True
    # Initials: "General Electric Company" vs. "GE Aerospace".
    initials = "".join(w[0] for w in a)
    return len(initials) >= 2 and initials in b


def names_match(sec_name: str | None, site_name: str | None) -> bool:
    """Guard against a wrong ticker->CIK mapping showing ANOTHER company's financials: the SEC
    entity name and the site's (Finviz) company name must share a meaningful word (or one name's
    initials / a run-together form of the other). Lenient on purpose ("Apple Inc." vs "Apple Inc",
    "LOWES COMPANIES INC" vs "Lowe's Cos. Inc"): it catches an unrelated company, not a variant
    spelling. Passes when either name is unknown."""
    if not sec_name or not site_name:
        return True
    a, b = _name_tokens(sec_name), _name_tokens(site_name)
    return not a or not b or _names_overlap(a, b) or _names_overlap(b, a)


def filing_index_url(cik: int, accession: str) -> str:
    return _FILING_INDEX_URL.format(cik=cik, accession_nodash=accession.replace("-", ""))


# -- I/O ------------------------------------------------------------------------------------------


def _user_agent() -> str:
    # An empty SEC_EDGAR_USER_AGENT (e.g. an unset GitHub Actions variable) must not send a blank
    # header — SEC rejects those outright.
    return (settings.sec_edgar_user_agent or "").strip() or _DEFAULT_USER_AGENT


def _get(client: httpx.Client, url: str, sleep=time.sleep) -> httpx.Response:
    last_error: str = ""
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            response = client.get(url)
        except httpx.TransportError as exc:
            last_error = f"network error: {exc}"
        else:
            if response.status_code == 404:
                raise SecNotFoundError(f"404 for {url}")
            if response.status_code not in _RETRY_STATUSES:
                if response.status_code != 200:
                    raise SecFetchError(f"HTTP {response.status_code} for {url}")
                return response
            last_error = f"HTTP {response.status_code}"
        if attempt < len(_RETRY_DELAYS):
            sleep(_RETRY_DELAYS[attempt])
    raise SecFetchError(f"{last_error} for {url} (after {len(_RETRY_DELAYS)} retries)")


def _gh_warning(title: str, message: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning title={title}::{message}", flush=True)


def _site_index() -> dict:
    return json.loads((_DATA_DIR / "index.json").read_text(encoding="utf-8"))


def _site_equities(index: dict) -> list[str]:
    """Tickers listed in docs/data/index.json whose own data file isn't an ETF."""
    equities = []
    for ticker in index["tickers"]:
        path = _DATA_DIR / f"{ticker}.json"
        if path.exists() and json.loads(path.read_text(encoding="utf-8")).get("is_etf"):
            continue
        equities.append(ticker)
    return equities


# Tickers whose current SEC registrant has no 10-K history yet, pointed at the registrant that
# does. Each entry needs a reason and should be removed once the new registrant files a 10-K
# (every run logs which overrides replaced the SEC-listed CIK, as a reminder).
_CIK_OVERRIDES: dict[str, int] = {
    # 2026: SEC's list maps XOM to the new "ExxonMobil Holdings Corp" (CIK 2115436), which has not
    # filed a 10-K yet; Exxon Mobil Corp's filings (and all its history) are under CIK 34088.
    "XOM": 34088,
}


def _search(client: httpx.Client, ticker: str, sleep) -> tuple[int, str] | None:
    return search_hit(_get(client, _SEARCH_URL.format(ticker=ticker), sleep).json(), ticker)


def _search_cik(client: httpx.Client, ticker: str, sleep) -> int | None:
    hit = _search(client, ticker, sleep)
    return hit[0] if hit else None


def _resolve_ciks(
    client: httpx.Client, tickers: list[str], names: dict[str, str], sleep,
) -> tuple[dict[str, int], dict[str, str], list[str]]:
    """(ticker -> CIK, ticker -> SEC's listed name for it, tickers whose lookup itself failed).
    See _COMPANY_TICKERS_URL's comment."""
    ciks: dict[str, int] = {}
    titles: dict[str, str] = {}
    failed: list[str] = []
    try:
        full = parse_company_tickers(_get(client, _COMPANY_TICKERS_URL, sleep).json())
        for t in tickers:
            if t in full:
                ciks[t], titles[t] = _pick_cik(full[t], names.get(t))
    except (SecFetchError, ValueError) as exc:
        logger.info("company_tickers.json unavailable (%s) — using EDGAR company search per ticker", exc)
        for ticker in tickers:
            try:
                hit = _search(client, ticker, sleep)
            except (SecFetchError, ValueError) as lookup_exc:
                logger.warning("[%s] CIK lookup failed: %s", ticker, lookup_exc)
                failed.append(ticker)
            else:
                if hit is not None:
                    ciks[ticker], titles[ticker] = hit
            sleep(_REQUEST_DELAY_SECONDS)
    for ticker, cik in _CIK_OVERRIDES.items():
        if ticker in tickers:
            listed = ciks.get(ticker)
            if listed not in (None, cik):
                logger.info("[%s] using override CIK %d instead of SEC-listed %s", ticker, cik, listed)
            ciks[ticker] = cik
            titles.pop(ticker, None)  # SEC's title was for the listed CIK, not the override
    return ciks, titles, failed


def main(tickers: list[str] | None = None, client: httpx.Client | None = None, sleep=time.sleep) -> None:
    full_run = not tickers
    index = _site_index()
    names: dict[str, str] = index.get("names") or {}
    tickers = tickers or _site_equities(index)
    generated_at = datetime.now(timezone.utc).isoformat()
    own_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": _user_agent()}, timeout=60.0, follow_redirects=True,
    )
    results: dict[str, dict] = {}
    unmapped: list[str] = []
    mismatched: list[str] = []
    try:
        cik_map, titles, failed = _resolve_ciks(client, tickers, names, sleep)
        for i, ticker in enumerate(tickers):
            if ticker in failed:
                continue
            cik = cik_map.get(ticker)
            base = {"ticker": ticker, "generated_at": generated_at,
                    "source": "SEC EDGAR XBRL companyfacts (10-K)"}
            if cik is None:
                unmapped.append(ticker)
                results[ticker] = {**base, "status": "not_in_sec"}
                continue
            try:
                facts = _get(client, _FACTS_URL.format(cik=cik), sleep).json()
            except SecNotFoundError:
                results[ticker] = {**base, "cik": cik, "status": "no_10k"}
                continue
            except (SecFetchError, ValueError) as exc:
                logger.warning("[%s] SEC fetch failed, keeping previous file: %s", ticker, exc)
                failed.append(ticker)
                continue
            finally:
                if i < len(tickers) - 1:
                    sleep(_REQUEST_DELAY_SECONDS)
            entity = facts.get("entityName")
            # Either SEC name may be the one that matches: companyfacts' entityName is occasionally
            # a co-registrant (Bank of America's CIK 70858 reports "BofA Finance LLC"), while the
            # ticker list still titles that CIK "BANK OF AMERICA CORP".
            entity_ok = names_match(entity, names.get(ticker))
            title_ok = bool(titles.get(ticker)) and names_match(titles[ticker], names.get(ticker))
            if not entity_ok and title_ok:
                # Show the registrant's own listed name, not the co-registrant's ("/DE/" = state).
                entity = re.sub(r"\s*/[A-Z]{2,3}/\s*$", "", titles[ticker]).strip()
            if not (entity_ok or title_ok):
                # A second opinion from EDGAR's own search before giving up on this ticker.
                try:
                    alt = _search_cik(client, ticker, sleep)
                    alt_facts = _get(client, _FACTS_URL.format(cik=alt), sleep).json() if alt not in (None, cik) else None
                except (SecFetchError, ValueError):
                    alt_facts = None
                if alt_facts and names_match(alt_facts.get("entityName"), names.get(ticker)):
                    cik, facts, entity = alt, alt_facts, alt_facts.get("entityName")
                else:
                    logger.warning("[%s] SEC entity %r doesn't match %r — not publishing",
                                   ticker, entity, names.get(ticker))
                    mismatched.append(ticker)
                    continue
            extracted = extract_annual_fundamentals(facts)
            record = {**base, "cik": cik, "entity_name": entity, **extracted}
            if extracted["status"] == "ok":
                record["latest_10k"]["url"] = filing_index_url(cik, extracted["latest_10k"]["accession"])
            results[ticker] = record
            logger.info("[%s] %s", ticker, extracted["status"])
    finally:
        if own_client:
            client.close()

    fetched = len(tickers) - len(failed)
    if fetched < max(1, len(tickers) // 2):
        raise RuntimeError(
            f"Only {fetched}/{len(tickers)} SEC fetches succeeded — aborting without writing, so "
            "the published SEC data stays as it was. Check data.sec.gov access / User-Agent."
        )
    if failed:
        _gh_warning("SEC data not refreshed", f"kept previous file for: {', '.join(failed)}")
    if unmapped:
        _gh_warning("Tickers not found in SEC EDGAR", ", ".join(unmapped))
    if mismatched:
        _gh_warning("SEC company name mismatch (not published)", ", ".join(mismatched))

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for ticker in mismatched:  # a previous file may hold the wrong company's numbers
        (_OUTPUT_DIR / f"{ticker}.json").unlink(missing_ok=True)
    for ticker, record in results.items():
        (_OUTPUT_DIR / f"{ticker}.json").write_text(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), encoding="utf-8",
        )
    if full_run:
        keep = set(tickers)
        for path in _OUTPUT_DIR.glob("*.json"):
            if path.stem not in keep:
                path.unlink()
                logger.info("Removed orphaned %s", path.name)
    ok = sum(1 for r in results.values() if r.get("status") == "ok")
    logger.info("Wrote %d SEC files (%d with 10-K data, %d failed and kept previous)",
                len(results), ok, len(failed))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    main(sys.argv[1:] or None)
