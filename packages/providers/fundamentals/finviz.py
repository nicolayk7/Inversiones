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

`get_current_price` (added to connect this provider to Wealth Engine's Valuation, which needs a
scalar price — see packages/engines/wealth_engine/data_ingestion.py's `ingest_finviz_price`): the
same quote page's "Current stock price" cell, confirmed present in the same grid. This is
deliberately NOT exposed as a `MarketDataProvider.get_daily_bars` implementation — that Protocol
promises real historical daily bars over an arbitrary [start, end] range, which this free page
cannot provide (it has no Open/High/Low fields at all, confirmed by enumerating every tooltip on
the live page — only a single current "last" price, previous close, and volume). Claiming to
implement `get_daily_bars` would mean either fabricating Open/High/Low from Close (exactly what
`packages.providers.market.massive` explicitly refuses to do for even a single missing field) or
silently returning a one-bar list for any multi-day range and calling it something it structurally
isn't. `get_current_price` names what it actually is instead: a live scalar, not a bar.

`get_price_history` (added for docs/index.html's technical-analysis candlestick chart, 2026-08-20,
EXPLICITLY approved by the user after being told the risk profile below — do not extend this
further without the same explicit check-in): real daily OHLCV bars, but NOT from the public quote
page — from `finviz.com/api/quote`, an UNDOCUMENTED internal JSON API that Finviz's own quote page
calls client-side to feed its interactive chart widget (confirmed live 2026-08-20 via the page's
own network requests, `GET /api/quote?ticker=...&timeframe=d&dateFrom=...&dateTo=...&
instrument=stock`). This is a meaningfully different, more aggressive access pattern than the rest
of this module: not a page a human is meant to read, but a backend endpoint meant only for
Finviz's own frontend. Disclosed plainly rather than blurred into the same "public page" framing
as everything else here. Kept to the same low-volume discipline regardless (one request per ticker
per scheduled run, not per visitor — see `scripts/generate_finviz_snapshot_site.py`, which is the
only caller). Confirmed: works with a plain, unauthenticated GET (no cookies, no session) and
returns HTTP 404 with `{"ticker": ..., "timeframe": ...}` (no OHLCV keys) for an unknown ticker,
mirroring the quote page's own 404 behavior.
"""

import html
import json
import re
from datetime import date, datetime, timedelta, timezone

import httpx

from packages.shared.schemas import FundamentalsRecord

_QUOTE_URL = "https://finviz.com/quote?t={ticker}"
_PRICE_API_URL = "https://finviz.com/api/quote"
_PRICE_HISTORY_DAYS = 1825  # 5 calendar years -> ~1250 trading days. Widened from the original
# 190-day (~6 month) window so docs/index.html's Semana/Mes candlestick cadences have enough
# history to be meaningful (a "monthly" chart with only 6 months behind it is ~6 candles).
# Confirmed live 2026-08-20 against AAPL: the endpoint happily returns the full 5-year range in
# one request (1254 daily bars, 2021-08-23 to today) — same endpoint, same timeframe="d" param
# already approved in this module's docstring, just a larger dateFrom/dateTo span, not a new
# access pattern.

# Browser-like UA — finviz.com returns HTTP 200 with the full fundamentals grid for this UA
# (confirmed live, 2026-08-20). A bare httpx default UA is untested here and risks being treated
# as a bot.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# Matches one snapshot-grid cell pair: a labeled td (keyed by its unique tooltip, not the short
# on-screen label — see module docstring) followed immediately by its value td.
#
# The label div's inner content is `.*?` (any content, non-greedy), NOT `[^<]*` (plain text only)
# — corrected 2026-08-20 after finding a real bug: 12 fields (Dividend Est./TTM/Ex-Date/Gr.,
# Payout, Recom, Target Price, the three "Short interest*" rows, EPS/Sales Surpr., Earnings date)
# were silently absent from every fetch. The earlier docstring guessed "an icon, most likely" —
# that guess was wrong, not verified against the actual markup. The real cause, confirmed by
# reading the raw HTML directly: these labels are wrapped in a plain `<a href="...">` link (e.g.
# `<div class="snapshot-td-label"><a href="stock?t=AAPL&ty=dv" ...>Dividend TTM</a></div>`, linking
# to that metric's own detail-chart view) — the OLD pattern's `[^<]*` cannot match past that `<a`,
# so the whole row silently failed to match. `.*?` (with re.S already in effect) correctly skips
# over the wrapping tag to find the label div's real closing `</div>`, restoring all 12 fields with
# no other change needed.
_ROW_PATTERN = re.compile(
    r'data-boxover-html="(?P<tooltip>[^"]*)"><div class="snapshot-td-label">.*?</div></td>'
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


# Sector/Industry/Country/Cap-size/Exchange live in a SEPARATE header block
# (`class="quote-header_categories"`), not the snapshot-table2 grid — up to 5 links, each tagged by
# its own screener filter prefix (sec_/ind_/geo_/cap_/exch_) rather than position, since a ticker
# can be missing one (confirmed live: ETF pages omit the cap_ link entirely). Confirmed live
# 2026-08-20 against both equities (AAPL: Technology/Consumer Electronics/USA/Mega/NASD) and ETFs
# (SPY/QQQ/VT: Financial/Exchange Traded Fund/USA/-/NYSE-or-NASD) — ETFs DO have this block, but
# Finviz classifies every ETF under the same generic sector="Financial",
# industry="Exchange Traded Fund" pair, which is not a real operating sector and must not be used
# for equity-style sector-relative comparison (see scripts/generate_finviz_snapshot_site.py's
# analysis module, which instead detects "is this an ETF" from the presence of the "Assets Under
# Management" field — a signal no equity page carries — rather than from this generic label).
_CATEGORY_PATTERN = re.compile(
    r'<a href="screener\?v=111&f=(?P<kind>sec|ind|geo|cap|exch)_[^"]*" '
    r'class="quote-header_category"[^>]*>(?P<text>.*?)</a>',
    re.S,
)
_CATEGORY_KIND_NAMES = {
    "sec": "sector", "ind": "industry", "geo": "country", "cap": "cap_size", "exch": "exchange",
}


def _parse_categories(body: str) -> dict[str, str]:
    """Returns whatever subset of {sector, industry, country, cap_size, exchange} this page's
    header block actually has — never guesses a missing one. Scoped to the header block only (the
    first ~800 chars after its marker class), not searched over the whole page, so it can't
    accidentally match an unrelated `quote-header_category`-styled link elsewhere."""
    start = body.find("quote-header_categories")
    if start == -1:
        return {}
    block = body[start : start + 800]
    return {
        _CATEGORY_KIND_NAMES[m.group("kind")]: html.unescape(_clean_text(m.group("text")))
        for m in _CATEGORY_PATTERN.finditer(block)
    }


def _parse_fields(body: str, ticker: str) -> dict[str, str]:
    """The snapshot grid only (tooltip-keyed), from an already-fetched page body. Tooltip keys are
    HTML-entity-decoded (`html.unescape`) — some contain literal `&#39;`/`&lt;br&gt;` in the raw
    attribute (e.g. "Analysts&#39; Dividend Estimate...", "Earnings date&lt;br&gt;...") which would
    otherwise never match a plain-string lookup written against the human-readable tooltip text."""
    fields: dict[str, str] = {
        html.unescape(m.group("tooltip")): _clean_text(m.group("value"))
        for m in _ROW_PATTERN.finditer(body)
    }
    if not fields:
        raise FinvizResponseError(
            f"Finviz fundamentals grid not found for {ticker!r} — page markup may have changed, "
            "or this was a bot-check response, not the real quote page"
        )
    return fields


# The historical-chart data lives in a single <script id="fa-init-data-0" type="application/json">
# blob, not the snapshot-table2 grid — {"annual": {"values": [[...], [...], [...]]}, "quarterly":
# {...}}, three point-series in a FIXED, undocumented order. Confirmed empirically (2026-08-20,
# not guessed) by cross-referencing each series' most-recent value against the SAME page's own
# labeled snapshot-grid fields, for two different tickers (AAPL and MSFT): series[0] always matches
# "Diluted EPS (ttm)", series[1] always matches "Revenue (ttm)" (in $ millions), series[2] always
# matches "Shares outstanding" (in millions). If Finviz ever reorders this, the generated chart
# would show implausible magnitudes (e.g. EPS in the hundreds-of-thousands range) — a visible,
# not-silent failure mode.
#
# Widened this check across all 100 tickers in scripts/generate_finviz_snapshot_site.py's default
# watchlist (2026-08-20 audit) — order held for 99/100. The one exception, GOOGL, is NOT a mapping
# bug: its EPS and Sales chart values still cross-validate correctly against its own grid fields;
# only shares_outstanding diverges (~12.23B on the chart vs. ~5.87B on the grid's "Shares
# outstanding" field), which traces to Finviz itself reporting different share counts in different
# page sections for dual/multi-class-share companies (Alphabet trades as both GOOG and GOOGL) —
# not something this parser can reconcile, since both numbers come from the same source page.
# Flagging here so a mismatch on a multi-class ticker reads as "known Finviz quirk," not a bug.
_CHART_DATA_PATTERN = re.compile(
    r'<script id="fa-init-data-0" type="application/json">(?P<json>.*?)</script>', re.S
)
_CHART_SERIES_ORDER = ("eps", "sales", "shares_outstanding")


def _parse_charts(body: str) -> dict[str, dict[str, list[dict]]] | None:
    """Returns `{"eps": {"annual": [...], "quarterly": [...]}, "sales": {...},
    "shares_outstanding": {...}}`, each a list of `{"name": <year or "TTM"/"MRQ" or quarter
    label>, "value": <float>}` points, or `None` if this ticker's page has no chart data block at
    all (never fabricated — some tickers genuinely lack a multi-year history, e.g. recent IPOs)."""
    match = _CHART_DATA_PATTERN.search(body)
    if match is None:
        return None
    try:
        raw = json.loads(match.group("json"))
    except json.JSONDecodeError:
        return None

    result: dict[str, dict[str, list[dict]]] = {}
    for cadence in ("annual", "quarterly"):
        series_list = raw.get(cadence, {}).get("values", [])
        for name, series in zip(_CHART_SERIES_ORDER, series_list):
            result.setdefault(name, {})[cadence] = series
    return result or None


def _parse_number(raw: str) -> float | None:
    """'-' is Finviz's own "no value" marker — returns None, never 0.0. Handles 'K'/'M'/'B'/'T'
    suffixes, comma thousand-separators (e.g. Volume's '17,640,556'), and a trailing '%' (returned
    as a fraction, e.g. '48.65%' -> 0.4865, matching FundamentalsRecord's
    gross_margin/operating_margin/roic/roe convention: ratios stored as fractions, not raw
    percentages)."""
    text = raw.strip().replace(",", "")
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

    def _fetch_page(self, ticker: str) -> str:
        """The one HTTP GET every method in this class is built on. Not cached — each call is a
        fresh live fetch, matching this provider's "no historical snapshots" nature (module
        docstring)."""
        response = self._client.get(_QUOTE_URL.format(ticker=ticker.upper()))
        if response.status_code == 404:
            raise FinvizNotFoundError(f"Finviz has no quote page for {ticker!r}")
        response.raise_for_status()
        return response.text

    def _fetch_fields(self, ticker: str) -> dict[str, str]:
        """One page fetch, parsed into a tooltip-keyed field dict (the snapshot grid only — not
        the historical charts; see `get_snapshot` for both together in one fetch)."""
        return _parse_fields(self._fetch_page(ticker), ticker)

    def get_quarterly_fundamentals(
        self, ticker: str, as_of: date | None = None
    ) -> list[FundamentalsRecord]:
        """Returns at most one record: today's live TTM ratio snapshot (see module docstring's
        period_end convention). A past `as_of` is not supported by this free source — raises
        rather than silently returning today's data mislabeled as historical."""
        now = datetime.now(timezone.utc)
        today = now.date()
        if as_of is not None and as_of < today:
            raise FinvizError(
                "Finviz free quote page has no historical snapshots — cannot honor a past as_of "
                f"({as_of}); only the live/current snapshot is available"
            )

        fields = self._fetch_fields(ticker)
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

    def get_current_price(self, ticker: str) -> tuple[float, int | None, datetime]:
        """Live (price, volume, observed_at) in a single fetch — one HTTP GET, not two, per this
        provider's own low-volume ToS discipline (module docstring). `observed_at` is this fetch's
        own timestamp, not an end-of-day convention — it genuinely IS the observation time. Not
        part of the `MarketDataProvider` Protocol — see module docstring for why.

        Raises `FinvizResponseError` if the price cell itself is unparseable (never returns a
        fabricated/zero price). `volume` is best-effort and may be `None` (never 0 — 0 would
        falsely assert "no shares traded today")."""
        fields = self._fetch_fields(ticker)
        observed_at = datetime.now(timezone.utc)
        price = _parse_number(fields.get("Current stock price", ""))
        if price is None:
            raise FinvizResponseError(
                f"Finviz quote page for {ticker!r} had no parseable 'Current stock price' value"
            )
        volume = _parse_number(fields.get("Volume", ""))
        return price, (int(volume) if volume is not None else None), observed_at

    def get_snapshot(self, ticker: str) -> dict:
        """Everything on the quote page, in ONE fetch (not `get_quarterly_fundamentals`'s
        curated FundamentalsRecord subset, and not two separate requests) — built for
        `scripts/generate_finviz_snapshot_site.py`'s static-visualization use case, which wants
        the raw grid plus the historical charts together. Returns `{"ticker": ...,
        "fields": {<tooltip>: <raw string value>, ...}, "charts": {...} | None,
        "categories": {"sector": ..., "industry": ..., ...} (whatever subset is present, see
        _parse_categories)}`. `fields` is unfiltered — every tooltip->value pair on the page, not a
        hand-picked subset — so a caller can choose what to display without this provider needing
        to know in advance."""
        body = self._fetch_page(ticker)
        return {
            "ticker": ticker.upper(),
            "fields": _parse_fields(body, ticker),
            "charts": _parse_charts(body),
            "categories": _parse_categories(body),
        }

    def get_price_history(self, ticker: str, days: int = _PRICE_HISTORY_DAYS) -> list[dict]:
        """Real daily OHLCV bars for the trailing `days` calendar days, from Finviz's internal
        chart-data API — see module docstring's dedicated disclosure for what this endpoint is and
        why it's a different risk profile than the rest of this provider. Returns a list of
        `{"date": "YYYY-MM-DD", "open", "high", "low", "close", "volume"}` dicts, oldest first.

        `date` is derived from the API's Unix-timestamp `date[i]` by taking its UTC calendar date —
        confirmed live (2026-08-20) that these timestamps land at 13:00-14:00 UTC (US market-open
        time translated to UTC), never near a UTC midnight boundary, so this can't roll to the
        wrong calendar day the way a literal midnight timestamp could (same reasoning
        `packages.providers.market.massive` already documents for its own timestamp handling).

        Raises `FinvizNotFoundError` for an unknown ticker (confirmed: 404 with no OHLCV keys in
        the body) and `FinvizResponseError` if the response is missing any of the six required
        arrays, or if they disagree in length — never zips mismatched arrays and silently
        misaligns a date against the wrong bar."""
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(days=days)
        response = self._client.get(_PRICE_API_URL, params={
            "ticker": ticker.upper(), "timeframe": "d", "instrument": "stock",
            "dateFrom": int(date_from.timestamp()), "dateTo": int(date_to.timestamp()),
        })
        if response.status_code == 404:
            raise FinvizNotFoundError(f"Finviz has no price history for {ticker!r}")
        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            raise FinvizResponseError(
                f"Finviz price API returned a non-JSON response for {ticker!r}"
            ) from exc

        required = ("date", "open", "high", "low", "close", "volume")
        missing = [k for k in required if k not in body]
        if missing:
            raise FinvizResponseError(
                f"Finviz price API response for {ticker!r} is missing {missing} — refusing to "
                "build a partial price history"
            )
        lengths = {k: len(body[k]) for k in required}
        if len(set(lengths.values())) > 1:
            raise FinvizResponseError(
                f"Finviz price API response for {ticker!r} has mismatched array lengths "
                f"{lengths} — refusing to zip them and risk misaligning a date against the "
                "wrong bar"
            )

        return [
            {
                "date": datetime.fromtimestamp(body["date"][i], tz=timezone.utc).date().isoformat(),
                "open": body["open"][i],
                "high": body["high"][i],
                "low": body["low"][i],
                "close": body["close"][i],
                "volume": body["volume"][i],
            }
            for i in range(lengths["date"])
        ]


__all__ = [
    "FinvizFundamentalsProvider",
    "FinvizError",
    "FinvizNotFoundError",
    "FinvizResponseError",
]
