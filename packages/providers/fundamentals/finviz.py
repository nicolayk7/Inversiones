"""Finviz free-tier `FundamentalsProvider` (partial) — scrapes the public, no-login quote page
(`finviz.com/quote.ashx?t=TICKER`) for a live TTM/MRQ ratio snapshot. Additive only: does not
replace or touch `packages/providers/fundamentals/sec_edgar.py`, which remains the source for
Wealth Engine's normalized statements (`get_income_statements`/`get_balance_sheets`/
`get_cash_flow_statements`). This provider implements ONLY `get_quarterly_fundamentals` — the
legacy flat `FundamentalsRecord` method SEC EDGAR explicitly left unimplemented (see that module's
own docstring: "no existing caller is broken"). The normalized-statement methods are NOT
implemented here: the free quote page exposes summary ratios, not raw statement line items (no
COGS/opex/interest-expense/SBC breakdown), and inventing a normalized statement from ratios would
be fabrication.

Real access reality, confirmed 2026-08-20 live against finviz.com itself: Finviz's actual
export/API access ("seamless exports/API", advertised on its own homepage) requires a paid Elite
subscription ($39.50/mo, 7-day free trial) — `finviz.com/export.ashx` redirects unauthenticated
requests straight back to the homepage. There is no free, permanent API key. What IS free and
requires no login is the public HTML quote page, confirmed reachable with a plain HTTP GET (no
auth, no cookies) returning HTTP 200. This adapter scrapes that page instead of using the paid API.

Confirmed against a live fetch of https://finviz.com/quote?t=AAPL (2026-08-20, browser-like
User-Agent) — the older `/quote.ashx?t=` path still exists but now 301-redirects here; this
adapter calls the canonical `/quote?t=` URL directly and also sets `follow_redirects=True`
defensively, in case Finviz's own path changes again:
- The page's fundamentals grid is server-rendered HTML, present in the raw response body itself —
  not injected by client-side JS. A plain `httpx.get` with a browser-like User-Agent is sufficient;
  no headless browser needed (verified: the same markup appears whether fetched via `curl` or via
  a real browser's rendered DOM).
- The grid is six `<table class="...snapshot-table2...">` elements (14 rows each = 84 label/value
  cell pairs total). Every cell carries a `data-boxover-html="..."` tooltip attribute holding a
  full, unique description — used here as the lookup key instead of the short on-screen label,
  because at least one short label ("EPS next Y") is reused for two different values on the same
  page (the EPS estimate in dollars vs. the EPS growth-rate percentage) and is NOT safe to key on
  alone. Every tooltip string this module looks up was read directly off that live response, not
  guessed.
- An unrecognized ticker returns HTTP 404 (confirmed against `t=ZZZZINVALIDTICKER`) — distinct
  from a markup/parse failure on a 200 response.

ToS disclosure: Finviz's Terms of Service restrict automated access to the site outside its paid
API. This adapter is scoped to low-volume, single-ticker, on-demand fetches (no bulk scraping, no
concurrent hammering, no screener scraping) with a descriptive browser User-Agent — but unlike SEC
EDGAR's fair-access policy, this is not a use explicitly sanctioned by the source. Documented here,
not hidden, per this codebase's disclosure-over-guessing rule. Do not extend this into
bulk/screener scraping, and do not increase call volume, without re-confirming ToS risk with the
user first.

period_end / reported_at convention — ASSUMED, disclosed, and DIFFERENT from SEC EDGAR's real
fiscal-period semantics: the free quote page states its ratios are trailing-twelve-month (ttm) or
most-recent-quarter (mrq) as of *right now*, but never states which exact fiscal period the ttm
window ends on. Rather than guess a fiscal period_end, this adapter stamps `period_end =
reported_at` = the scrape date itself, and the returned record represents "TTM ratios as observed
on this date" — not a substitute for a true fiscal-period record. Callers needing real fiscal
periods must use SEC EDGAR; this provider is a supplementary ratio snapshot only. `as_of` in the
past is therefore not supported (this free source has no historical snapshots) and raises rather
than silently mislabeling today's data as historical.
"""

import re
from datetime import date, datetime, timezone

import httpx

from packages.shared.schemas import FundamentalsRecord

_QUOTE_URL = "https://finviz.com/quote?t={ticker}"

# Browser-like UA — finviz.com returns HTTP 200 with the full fundamentals grid for this UA
# (confirmed live, 2026-08-20). A bare httpx default UA is untested here and risks being treated
# as a bot.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# Matches one snapshot-grid cell pair: a labeled td (keyed by its unique tooltip, not the short
# on-screen label — see module docstring) followed immediately by its value td.
_ROW_PATTERN = re.compile(
    r'data-boxover-html="(?P<tooltip>[^"]*)"><div class="snapshot-td-label">[^<]*</div></td>'
    r'<td[^>]*><div class="snapshot-td-content">(?P<value>.*?)</div>',
    re.S,
)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_SUFFIX_MULTIPLIER = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


class FinvizError(RuntimeError):
    """Base for every error this adapter raises — never silently swallowed into a fabricated
    result."""


class FinvizNotFoundError(FinvizError):
    """Finviz has no quote page for this ticker (HTTP 404) — distinct from a network/parse
    failure."""


class FinvizResponseError(FinvizError):
    """Page fetched but the expected fundamentals grid was not found — Finviz changed its markup,
    or returned something else (e.g. a bot-check page) instead of the real quote page. Never
    fabricate a record from this."""


def _clean_text(html_fragment: str) -> str:
    return _TAG_PATTERN.sub("", html_fragment).strip()


def _parse_number(raw: str) -> float | None:
    """'-' is Finviz's own "no value" marker — returns None, never 0.0. Handles 'K'/'M'/'B'/'T'
    suffixes and a trailing '%' (returned as a fraction, e.g. '48.65%' -> 0.4865, matching
    FundamentalsRecord's gross_margin/operating_margin/roic/roe convention: ratios stored as
    fractions, not raw percentages)."""
    text = raw.strip()
    if not text or text == "-":
        return None
    is_percent = text.endswith("%")
    if is_percent:
        text = text[:-1]
    multiplier = 1.0
    if text and text[-1] in _SUFFIX_MULTIPLIER:
        multiplier = _SUFFIX_MULTIPLIER[text[-1]]
        text = text[:-1]
    try:
        value = float(text)
    except ValueError:
        return None
    value *= multiplier
    return value / 100 if is_percent else value


class FinvizFundamentalsProvider:
    """Partial `FundamentalsProvider` — implements `get_quarterly_fundamentals` only. See module
    docstring for why the normalized-statement methods are intentionally absent."""

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(
            headers={"User-Agent": _USER_AGENT}, timeout=30.0, follow_redirects=True
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FinvizFundamentalsProvider":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get_quarterly_fundamentals(
        self, ticker: str, as_of: date | None = None
    ) -> list[FundamentalsRecord]:
        """Returns at most one record: today's live TTM ratio snapshot (see module docstring's
        period_end convention). A past `as_of` is not supported by this free source — raises
        rather than silently returning today's data mislabeled as historical."""
        if as_of is not None and as_of < date.today():
            raise FinvizError(
                "Finviz free quote page has no historical snapshots — cannot honor a past as_of "
                f"({as_of}); only the live/current snapshot is available"
            )

        response = self._client.get(_QUOTE_URL.format(ticker=ticker.upper()))
        if response.status_code == 404:
            raise FinvizNotFoundError(f"Finviz has no quote page for {ticker!r}")
        response.raise_for_status()
        body = response.text

        fields: dict[str, str] = {
            m.group("tooltip"): _clean_text(m.group("value")) for m in _ROW_PATTERN.finditer(body)
        }
        if not fields:
            raise FinvizResponseError(
                f"Finviz fundamentals grid not found for {ticker!r} — page markup may have "
                "changed, or this was a bot-check response, not the real quote page"
            )

        today = date.today()
        now = datetime.now(timezone.utc)
        return [
            FundamentalsRecord(
                ticker=ticker.upper(),
                period_end=today,
                reported_at=today,
                available_at=now,
                revenue=_parse_number(fields.get("Revenue (ttm)", "")),
                eps=_parse_number(fields.get("Diluted EPS (ttm)", "")),
                fcf=self._derive_fcf(fields),
                gross_margin=_parse_number(fields.get("Gross Margin (ttm)", "")),
                operating_margin=_parse_number(fields.get("Operating Margin (ttm)", "")),
                roic=_parse_number(fields.get("Return on Invested Capital (ttm)", "")),
                roe=_parse_number(fields.get("Return on Equity (ttm)", "")),
                # Not exposed as raw dollar figures anywhere on the free page — only Debt/Eq and
                # LT Debt/Eq ratios are, and reconstructing a dollar net-debt figure from a ratio
                # plus an approximate book-equity would compound two approximations into a third.
                # Left None rather than fabricated.
                net_debt=None,
                debt_ebitda=None,
                source="finviz",
            )
        ]

    @staticmethod
    def _derive_fcf(fields: dict[str, str]) -> float | None:
        """FCF is not published directly on the free page — only Price/FCF (a per-share ratio).
        Derived as `price * shares_outstanding / (price / fcf)`, computed ONLY when all three
        inputs parse successfully; otherwise None, never a partial guess. Disclosed derivation, not
        a Finviz-reported figure verbatim — callers auditing provenance should know this one is
        computed."""
        price = _parse_number(fields.get("Current stock price", ""))
        shares_outstanding = _parse_number(fields.get("Shares outstanding", ""))
        price_to_fcf = _parse_number(fields.get("Price to Free Cash Flow (ttm)", ""))
        if price is None or shares_outstanding is None or not price_to_fcf:
            return None
        return price * shares_outstanding / price_to_fcf


__all__ = [
    "FinvizFundamentalsProvider",
    "FinvizError",
    "FinvizNotFoundError",
    "FinvizResponseError",
]
