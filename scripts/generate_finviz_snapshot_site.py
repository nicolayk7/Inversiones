"""Generates the static, $0-cost visualization site under `docs/`: Finviz's public quote page ->
JSON files under `docs/data/` -> a plain HTML/JS page (`docs/index.html`) that reads them. No
backend, no database — deployable to GitHub Pages or Netlify as pure static files, refreshed by
re-running this script (see `.github/workflows/refresh-finviz-snapshot.yml` for the daily cron).

Deliberately independent of the rest of this repo's stack: no Postgres, no Redis, no SEC EDGAR, no
Wealth Engine scoring. This is a raw Finviz data mirror for visualization only — not a Quant Core
input, and its output must never be wired into Wealth Engine's storage/pipeline (that's
`ingest_finviz_price` in `packages/engines/wealth_engine/data_ingestion.py`, a separate, unrelated
concern that happens to use the same underlying provider).

TICKERS is independent of `scripts/ingest_mvp_universe.py`'s MVP_TICKERS — this script needs no CIK
mapping (Finviz scraping doesn't require one), so it isn't restricted to that set. It is the real,
verified union of the S&P 500 and Nasdaq-100 constituents (518 unique tickers) — NOT the Wealth
Engine's `universe_definition`, and must never be conflated with it (CLAUDE.md's Equity Universe
vs. Market Context split governs THAT list, not this one — this generator's output never reaches
Wealth Engine). Pass tickers as CLI args to override or narrow it for a single run.

Sourced live, not guessed (2026-08-20): S&P 500 (503 tickers) from Wikipedia's "List of S&P 500
companies" constituents table, parsed off each row's exchange-symbol template invocation (the
NyseSymbol/NasdaqSymbol/BZX-link template's own `params.1.wt` value, not the visible link text —
two rows, BRK.B and BF.B, carry an inline HTML comment between the ticker link and its cell close
tag that breaks a naive "grab the first link in the cell" parse and silently substitutes the
company name instead; this was caught by cross-checking the extracted list actually contained
"BRK" during development, not assumed correct). Nasdaq-100 (102 tickers, the real current count —
dual-class shares like GOOG/GOOGL push it slightly over 100) from slickcharts.com/nasdaq100's
constituent table. Unioned and deduplicated to 518. Two tickers use a period in their official
symbol (BRK.B, BF.B) but Finviz's own URL scheme requires a hyphen instead — confirmed live
(`quote?t=BRK-B` -> HTTP 200, `quote?t=BRK.B` -> HTTP 404) rather than assumed, and converted here.

On-demand, arbitrary-ticker search from the browser is deliberately NOT how this works: a static
site's client-side JS cannot fetch finviz.com directly (no CORS allow-origin from Finviz, and even
if there were, it would mean every visitor's browser independently scraping Finviz — unbounded
volume, the opposite of the low-volume discipline finviz.py's module docstring commits to). The
approach here instead: pre-generate a broad-but-bounded watchlist once a day from ONE controlled
runner (the GitHub Actions cron), and let the page's search box filter that already-fetched index
client-side. `docs/index.html`'s search feels instant because it's a local filter, not a live call.

A larger TICKERS list means more sequential requests per run — `_REQUEST_DELAY_SECONDS` adds a
small pause between them so a run still reads as "one script working through a list slowly," not a
burst. That is a real, deliberate increase in daily request volume over this generator's original
4/100-ticker versions — still one controlled runner, one request at a time, once a day, but worth
being explicit about rather than letting the list grow without remark.

Each ticker now costs TWO requests, not one: `get_snapshot` (the quote page) plus
`get_price_history` (the internal chart-data API, added for docs/index.html's candlestick chart —
see finviz.py's module docstring for that endpoint's own, separately-disclosed risk profile,
explicitly approved by the user before being added). ~529 tickers x 2 requests x
`_REQUEST_DELAY_SECONDS` between each puts a full run at roughly 7-8 minutes — still one
sequential runner, one request in flight at a time, once a day (the user explicitly chose to keep
that pattern over adding concurrency when asked, 2026-08-21 — trimmed the artificial pause between
requests instead, from 0.6s to 0.15s; live-measured actual network time per request is ~0.1-0.6s,
so this still reads as "working through a list steadily," not a burst), but real enough to name
here rather than let it drift up silently as more capabilities get added to this generator.

FIELD_LAYOUT is a curated, high-confidence subset of the ~84 fields Finviz's quote page exposes —
every entry's tooltip key was verified present on a live fetch during development, cross-checked
against `provider.get_snapshot(ticker)["fields"]`'s actual key list, not assumed from the visible
page alone.

CORRECTION (2026-08-20): an earlier version of this docstring claimed 12 fields (the three "Short
interest*" rows, Recom, Target Price, Dividend Est./TTM/Ex-Date/Gr., Payout, EPS/Sales Surpr.,
Earnings date) were permanently unavailable — "their on-page label `<div>` holds something other
than plain text in the raw HTML (an icon, most likely)". That was a guess, not a verified cause,
and it was wrong: the real cause was `finviz.py`'s `_ROW_PATTERN` regex requiring the label div to
contain plain text only (`[^<]*`), when these 12 labels are actually wrapped in a plain `<a
href="...">` link to that metric's own chart view — confirmed by reading the raw HTML directly.
Fixed in `_ROW_PATTERN` (now `.*?`, skips over the wrapping tag); all 84 fields resolve as of this
fix, not 72. The dividend fields below were added once this was confirmed working live.

ETFs (confirmed live 2026-08-20 against SPY/QQQ/VT): Finviz's ETF quote pages carry a COMPLETELY
DIFFERENT field set — no P/E, no EPS, no ROE (none of FIELD_LAYOUT's equity fields resolve for
them) — instead Assets Under Management, expense ratio, holdings count, tracked index, fund
manager, and 1/3/5/10-year annualized returns. `ETF_FIELD_LAYOUT` covers that set instead.
`_is_etf(fields)` decides which layout applies per ticker by checking for the "Assets Under
Management" tooltip's presence — a signal no equity page carries — rather than trusting Finviz's
own generic classification (every ETF is filed under sector="Financial",
industry="Exchange Traded Fund", which is not a real operating sector).

EXTRA_ETF_TICKERS and EXTRA_EQUITY_TICKERS are hand-picked additions outside the S&P 500 ∪
Nasdaq-100 union above — major broad/sector ETFs (not "constituents" of any equity index, so they
can't be sourced the same way) and PBR (Petrobras, a Brazilian ADR — real, liquid, but not a member
of either index). Disclosed as hand-picked, same as this module's earlier watchlist iterations —
not claimed to be exhaustive or authoritative.

The analysis section (`_build_equity_analysis`/`_build_etf_analysis`) answers "quiero que la
persona entienda mejor lo que ve" without an LLM call — this static site has no backend and no
Anthropic API key configured, and CLAUDE.md's own architecture principle ("every number computed
by deterministic code") argues against a narrative-generation step here anyway. Instead: for
equities, each ticker's P/E / P/S / EV-EBITDA / ROE / margins are compared against the MEDIAN of
its own sector *within this generated dataset* (real numbers, computed fresh every run — never an
externally-sourced "typical sector P/E" table, which this codebase has no way to verify). A sector
with fewer than 3 other equities in the dataset is skipped entirely rather than reported off a
meaningless sample. For ETFs, there is no sector to compare against (a fund isn't a company) — the
analysis instead reads the expense ratio against fixed, disclosed industry-standard bands
(<=0.10% / 0.10-0.50% / >0.50%), not computed from this dataset. This analysis module is
deliberately self-contained — it does NOT import packages/quant_core or packages/engines
(reusing those would blur the documented separation between this raw Finviz mirror and the Wealth
Engine's own, differently-sourced pipeline).

Usage:
    python scripts/generate_finviz_snapshot_site.py                  # all TICKERS
    python scripts/generate_finviz_snapshot_site.py AAPL MSFT NVDA   # any tickers you like
"""

import json
import logging
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from packages.providers.fundamentals.finviz import FinvizError, FinvizFundamentalsProvider
from packages.providers.fundamentals.finviz import _parse_number as _parse_finviz_number

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("generate_finviz_snapshot_site")

_REQUEST_DELAY_SECONDS = 0.15  # trimmed from 0.6 (2026-08-21) to shorten the daily refresh; see
# module docstring's timing paragraph for why this stays sequential rather than adding concurrency.

# S&P 500 ∪ Nasdaq-100, 518 unique tickers, alphabetical — see module docstring for exact sourcing
# (Wikipedia + slickcharts.com, fetched live 2026-08-20) and the BRK.B/BF.B -> BRK-B/BF-B rewrite.
# Re-running the two fetches later will drift from this list as index membership changes; this is
# a point-in-time snapshot of membership, not a live-synced one.
_SP500_NASDAQ100_TICKERS = [
    "A", "AAPL", "ABBV", "ABNB", "ABT", "ACGL", "ACN", "ADBE", "ADI", "ADM",
    "ADP", "ADSK", "AEE", "AEP", "AES", "AFL", "AIG", "AIZ", "AJG", "AKAM",
    "ALAB", "ALB", "ALGN", "ALL", "ALLE", "ALNY", "AMAT", "AMCR", "AMD", "AME",
    "AMGN", "AMP", "AMT", "AMZN", "ANET", "AON", "AOS", "APA", "APD", "APH",
    "APO", "APP", "APTV", "ARE", "ARES", "ARM", "ASML", "ATO", "AVGO", "AVY",
    "AWK", "AXON", "AXP", "AZO", "BA", "BAC", "BALL", "BAX", "BBY", "BDX",
    "BEN", "BF-B", "BG", "BIIB", "BKNG", "BKR", "BLDR", "BLK", "BMY", "BNY",
    "BR", "BRK-B", "BRO", "BSX", "BX", "BXP", "C", "CAH", "CARR", "CASY",
    "CAT", "CB", "CBOE", "CBRE", "CCEP", "CCI", "CCL", "CDNS", "CDW", "CEG",
    "CF", "CFG", "CHD", "CHRW", "CHTR", "CI", "CIEN", "CINF", "CL", "CLX",
    "CMCSA", "CME", "CMG", "CMI", "CMS", "CNC", "CNP", "COF", "COHR", "COIN",
    "COO", "COP", "COR", "COST", "CPAY", "CPRT", "CPT", "CRH", "CRL", "CRM",
    "CRWD", "CRWV", "CSCO", "CSGP", "CSX", "CTAS", "CTSH", "CTVA", "CVNA", "CVS",
    "CVX", "D", "DAL", "DASH", "DD", "DDOG", "DE", "DECK", "DELL", "DG",
    "DGX", "DHI", "DHR", "DIS", "DLR", "DLTR", "DOC", "DOV", "DOW", "DPZ",
    "DRI", "DTE", "DUK", "DVA", "DVN", "DXCM", "EBAY", "ECHO", "ECL", "ED",
    "EFX", "EG", "EIX", "EL", "ELV", "EME", "EMR", "EOG", "EQIX", "EQT",
    "ERIE", "ES", "ESS", "ETN", "ETR", "EVRG", "EW", "EXC", "EXE", "EXPD",
    "EXPE", "EXR", "F", "FANG", "FAST", "FCX", "FDS", "FDX", "FDXF", "FE",
    "FER", "FERG", "FFIV", "FICO", "FIS", "FISV", "FITB", "FIX", "FLEX", "FOX",
    "FOXA", "FRT", "FSLR", "FTNT", "FTV", "GD", "GDDY", "GE", "GEHC", "GEN",
    "GEV", "GILD", "GIS", "GL", "GLW", "GM", "GNRC", "GOOG", "GOOGL", "GPC",
    "GPN", "GRMN", "GS", "GWW", "HAL", "HAS", "HBAN", "HCA", "HD", "HIG",
    "HII", "HLT", "HON", "HONA", "HOOD", "HPE", "HPQ", "HRL", "HSIC", "HST",
    "HSY", "HUBB", "HUM", "HWM", "IBKR", "IBM", "ICE", "IDXX", "IEX", "IFF",
    "INCY", "INTC", "INTU", "INVH", "IP", "IQV", "IR", "IRM", "ISRG", "IT",
    "ITW", "IVZ", "J", "JBHT", "JBL", "JCI", "JKHY", "JNJ", "JPM", "KDP",
    "KEY", "KEYS", "KHC", "KIM", "KKR", "KLAC", "KMB", "KMI", "KO", "KR",
    "KVUE", "L", "LDOS", "LEN", "LH", "LHX", "LII", "LIN", "LITE", "LLY",
    "LMT", "LNT", "LOW", "LRCX", "LULU", "LUV", "LVS", "LYB", "LYV", "MA",
    "MAA", "MAR", "MAS", "MCD", "MCHP", "MCK", "MCO", "MDLZ", "MDT", "MELI",
    "MET", "META", "MGM", "MKC", "MLM", "MMM", "MNST", "MO", "MOS", "MPC",
    "MPWR", "MRK", "MRNA", "MRSH", "MRVL", "MS", "MSCI", "MSFT", "MSI", "MSTR",
    "MTB", "MTD", "MU", "NBIS", "NCLH", "NDAQ", "NDSN", "NEE", "NEM", "NFLX",
    "NI", "NKE", "NOC", "NOW", "NRG", "NSC", "NTAP", "NTRS", "NUE", "NVDA",
    "NVR", "NWS", "NWSA", "NXPI", "O", "ODFL", "OKE", "OMC", "ON", "ORCL",
    "ORLY", "OTIS", "OXY", "PANW", "PAYX", "PCAR", "PCG", "PDD", "PEG", "PEP",
    "PFE", "PFG", "PG", "PGR", "PH", "PHM", "PKG", "PLD", "PLTR", "PM",
    "PNC", "PNR", "PNW", "PODD", "PPG", "PPL", "PRU", "PSA", "PSKY", "PSX",
    "PTC", "PWR", "PYPL", "Q", "QCOM", "RCL", "RDDT", "REG", "REGN", "RF",
    "RJF", "RKLB", "RL", "RMD", "ROK", "ROL", "ROP", "ROST", "RSG", "RTX",
    "RVTY", "SBAC", "SBUX", "SCHW", "SHOP", "SHW", "SJM", "SLB", "SMCI", "SNA",
    "SNDK", "SNPS", "SO", "SOLV", "SPCX", "SPG", "SPGI", "SRE", "STE", "STLD",
    "STT", "STX", "STZ", "SW", "SWK", "SWKS", "SYF", "SYK", "SYY", "T",
    "TAP", "TDG", "TDY", "TECH", "TEL", "TER", "TFC", "TGT", "TJX", "TKO",
    "TMO", "TMUS", "TPL", "TPR", "TRGP", "TRI", "TRMB", "TROW", "TRV", "TSCO",
    "TSLA", "TSN", "TT", "TTD", "TTWO", "TXN", "TXT", "TYL", "UAL", "UBER",
    "UDR", "UHS", "ULTA", "UNH", "UNP", "UPS", "URI", "USB", "V", "VEEV",
    "VICI", "VLO", "VLTO", "VMC", "VMRK", "VRSK", "VRSN", "VRT", "VRTX", "VST",
    "VTR", "VTRS", "VZ", "WAB", "WAT", "WBD", "WDAY", "WDC", "WEC", "WELL",
    "WFC", "WM", "WMB", "WMT", "WRB", "WSM", "WST", "WTW", "WY", "WYNN",
    "XEL", "XOM", "XYL", "XYZ", "YUM", "ZBH", "ZBRA", "ZTS",
]

# Major broad-market / sector ETFs — hand-picked (ETFs aren't index "constituents", so there's no
# equivalent of the S&P 500/Nasdaq-100 sourcing above). SPY/QQQ/VT explicitly requested; the rest
# are common companions (total-market, small-cap, developed/emerging ex-US, gold) chosen for
# breadth, not an exhaustive ETF universe.
EXTRA_ETF_TICKERS = ["SPY", "QQQ", "VT", "VOO", "VTI", "IWM", "DIA", "GLD", "VXUS", "EFA"]

# Individual equities outside the S&P 500 ∪ Nasdaq-100 union — hand-picked, not sourced from an
# index. PBR (Petrobras) confirmed live: ordinary equity-shaped Finviz page (72 fields, same
# layout as any S&P 500 constituent) — no special handling needed beyond just adding the symbol.
EXTRA_EQUITY_TICKERS = ["PBR"]

TICKERS = _SP500_NASDAQ100_TICKERS + EXTRA_EQUITY_TICKERS + EXTRA_ETF_TICKERS

_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "data"

# (display label, Finviz tooltip key) — four columns, each verified against a live fetch.
FIELD_LAYOUT: list[list[tuple[str, str]]] = [
    [
        ("Market Cap", "Market capitalization"),
        ("Enterprise Value", "Enterprise Value"),
        ("Income (ttm)", "Income (ttm)"),
        ("Sales (ttm)", "Revenue (ttm)"),
        ("Book/sh", "Book value per share (mrq)"),
        ("Cash/sh", "Cash per share (mrq)"),
        ("Employees", "Full time employees"),
        ("IPO Date", "IPO Date"),
        # Confirmed live 2026-08-21 against AAPL: tooltip key literally embeds the "BMO/AMC"
        # legend as <br>-separated HTML in the key itself (Finviz's own markup, not ours) — the
        # value is just e.g. "Jul 30 AMC". Next/most recent scheduled earnings report date.
        ("Earnings Date", "Earnings date<br><br>BMO = Before Market Open<br>AMC = After Market Close"),
    ],
    [
        # Dividend fields — unavailable until the _ROW_PATTERN fix above (2026-08-20); "-" here is
        # a genuine, correct "no dividend" for a non-payer, not a parsing gap.
        ("Dividend Est.", "Analysts' Dividend Estimate (Fiscal Year)"),
        ("Dividend TTM", "Trailing 12 Months Dividend"),
        ("Dividend Ex-Date", "Ex-Dividend Date"),
        ("Dividend Gr. 3/5Y", "Dividend growth over 3 and 5 years"),
        ("Payout Ratio", "Dividend Payout Ratio (ttm)"),
    ],
    [
        ("P/E", "Price-to-Earnings (ttm)"),
        ("Forward P/E", "Forward Price-to-Earnings (next fiscal year)"),
        ("PEG", "Price-to-Earnings-to-Growth"),
        ("P/S", "Price-to-Sales (ttm)"),
        ("P/B", "Price-to-Book (mrq)"),
        ("P/FCF", "Price to Free Cash Flow (ttm)"),
        ("EV/EBITDA", "Enterprise Value to EBITDA"),
        ("EV/Sales", "Enterprise Value to Revenues"),
        ("Debt/Eq", "Total Debt to Equity (mrq)"),
        ("Current Ratio", "Current Ratio (mrq)"),
    ],
    [
        ("EPS (ttm)", "Diluted EPS (ttm)"),
        ("EPS next Y ($)", "EPS estimate for next year"),
        ("EPS next Y (%)", "EPS growth next year"),
        ("EPS next 5Y", "Long term annual growth estimate (5 years)"),
        ("EPS past 3/5Y", "Annual EPS growth past 3 and 5 years"),
        ("Sales past 3/5Y", "Annual sales growth past 3 and 5 years"),
        ("ROE", "Return on Equity (ttm)"),
        ("ROIC", "Return on Invested Capital (ttm)"),
        ("ROA", "Return on Assets (ttm)"),
        ("Gross Margin", "Gross Margin (ttm)"),
        ("Oper. Margin", "Operating Margin (ttm)"),
        ("Profit Margin", "Net Profit Margin (ttm)"),
    ],
    [
        ("Shs Outstand", "Shares outstanding"),
        ("Insider Own", "Insider ownership"),
        ("Inst Own", "Institutional ownership"),
        ("52W High", "Distance from 52-Week High"),
        ("52W Low", "Distance from 52-Week Low"),
        ("Beta", "Beta"),
        ("Avg Volume", "Average volume (3 month)"),
        ("Rel Volume", "Relative volume"),
        ("Volume", "Volume"),
        ("RSI (14)", "Relative Strength Index"),
        ("Prev Close", "Previous close"),
        ("Price", "Current stock price"),
        ("Change %", "Performance (today)"),
    ],
]

# Present on every ETF page, absent from every equity page (confirmed live 2026-08-20 against
# SPY/QQQ/VT vs. AAPL/PBR) — the signal _is_etf uses instead of trusting Finviz's own generic
# sector/industry classification for funds.
_ETF_MARKER_TOOLTIP = "Assets Under Management"

# (display label, Finviz tooltip key) — ETF pages have none of FIELD_LAYOUT's equity fields
# (no P/E, no EPS, no ROE); this is the real, separate field set confirmed live for SPY/QQQ/VT.
ETF_FIELD_LAYOUT: list[list[tuple[str, str]]] = [
    [
        ("Price", "Current stock price"),
        ("Prev Close", "Previous close"),
        ("Change %", "Performance (today)"),
        ("AUM", "Assets Under Management"),
        ("Expense Ratio", "Gross expense net of fee waivers, as a % of net assets as published by the ETF Issuer"),
        ("Inception Date", "IPO Date"),
    ],
    [
        ("Category", "Single category of the ETF"),
        ("Asset Type", "The asset type of the ETF"),
        ("Tracked Index", "Name of the underlying index tracked by the ETF, if applicable"),
        ("Fund Manager", "The fund manager (ETF) or issuing bank (ETN)"),
        ("Holdings", "Total count of all holdings in the ETF"),
    ],
    [
        ("1Y Return", "1-Year Annualized Return"),
        ("3Y Return", "3-Year Annualized Return"),
        ("5Y Return", "5-Year Annualized Return"),
        ("10Y Return", "10-Year Annualized Return"),
        ("YTD Fund Flows", "Year-to-date Net Fund Flows of the ETF as percentage of Assets Under Management"),
    ],
    [
        ("Volume", "Volume"),
        ("Avg Volume", "Average volume (3 month)"),
        ("Beta", "Beta"),
        ("52W High", "Distance from 52-Week High"),
        ("52W Low", "Distance from 52-Week Low"),
    ],
]


def _is_etf(raw_fields: dict[str, str]) -> bool:
    return _ETF_MARKER_TOOLTIP in raw_fields


def _extract_columns(raw_fields: dict[str, str], is_etf: bool) -> list[list[dict]]:
    layout = ETF_FIELD_LAYOUT if is_etf else FIELD_LAYOUT
    return [
        # `or "-"` catches both a missing key AND a present-but-blank value (confirmed live: some
        # ETF fields, e.g. "10-Year Annualized Return" for a young fund, exist with value "" —
        # not Finviz's own "-" marker — and would otherwise render as a silently blank cell).
        [{"label": label, "value": raw_fields.get(tooltip) or "-"} for label, tooltip in column]
        for column in layout
    ]


# -- deterministic, no-LLM analysis (module docstring explains why no LLM) ---------------------

# (display label, Finviz tooltip key, direction). "lower_is_cheaper": below the sector median
# reads as cheaper, not worse. "higher_is_better": above the sector median reads as stronger.
_EQUITY_ANALYSIS_METRICS: list[tuple[str, str, str]] = [
    ("P/E", "Price-to-Earnings (ttm)", "lower_is_cheaper"),
    ("P/S", "Price-to-Sales (ttm)", "lower_is_cheaper"),
    ("EV/EBITDA", "Enterprise Value to EBITDA", "lower_is_cheaper"),
    ("ROE", "Return on Equity (ttm)", "higher_is_better"),
    ("Margen bruto", "Gross Margin (ttm)", "higher_is_better"),
    ("Margen operativo", "Operating Margin (ttm)", "higher_is_better"),
]
_MIN_SECTOR_SAMPLE = 3  # fewer peers than this and the "median" isn't meaningful — skip, don't fake it.
_EXPENSE_RATIO_TOOLTIP = "Gross expense net of fee waivers, as a % of net assets as published by the ETF Issuer"


def _compute_sector_stats(
    snapshots: dict[str, dict],
) -> dict[str, dict[str, dict[str, float]]]:
    """sector -> tooltip -> {"median": ..., "n": ...}, computed ONLY from equities (never ETFs —
    their sector label is the generic "Financial" Finviz assigns every fund) actually present in
    THIS run's fetched dataset. Sectors with fewer than _MIN_SECTOR_SAMPLE qualifying values for a
    given metric are omitted from that metric entirely, not reported off a thin sample."""
    by_sector: dict[str, dict[str, list[float]]] = {}
    for snapshot in snapshots.values():
        if _is_etf(snapshot["fields"]):
            continue
        sector = snapshot["categories"].get("sector")
        if not sector:
            continue
        for _, tooltip, _ in _EQUITY_ANALYSIS_METRICS:
            value = _parse_finviz_number(snapshot["fields"].get(tooltip, "-"))
            if value is not None:
                by_sector.setdefault(sector, {}).setdefault(tooltip, []).append(value)

    stats: dict[str, dict[str, dict[str, float]]] = {}
    for sector, metrics in by_sector.items():
        for tooltip, values in metrics.items():
            if len(values) >= _MIN_SECTOR_SAMPLE:
                stats.setdefault(sector, {})[tooltip] = {
                    "median": statistics.median(values), "n": len(values),
                }
    return stats


def _read_comparison(value: float, median: float, direction: str) -> str:
    if median == 0:
        return "sin referencia (mediana del sector es 0)"
    ratio = value / median
    if 0.9 <= ratio <= 1.1:
        return "en línea con la mediana del sector"
    above = ratio > 1.1
    if direction == "lower_is_cheaper":
        return "más caro que la mediana del sector" if above else "más barato que la mediana del sector"
    return "por encima de la mediana del sector" if above else "por debajo de la mediana del sector"


def _growth_note(charts: dict | None) -> str | None:
    """One sentence from the sales chart's last two annual points, already scraped — no extra
    fetch. None if there isn't enough history to compare (never fabricated)."""
    if not charts or "sales" not in charts:
        return None
    annual = charts["sales"].get("annual", [])
    if len(annual) < 2:
        return None
    latest, prior = annual[-1], annual[-2]
    if not prior["value"]:
        return None
    yoy = (latest["value"] - prior["value"]) / abs(prior["value"]) * 100
    direction = "creciendo" if yoy > 0 else "cayendo"
    return f"Ventas {direction} {abs(yoy):.1f}% interanual ({prior['name']} → {latest['name']})."


def _build_equity_analysis(
    fields: dict[str, str], categories: dict[str, str], charts: dict | None,
    sector_stats: dict[str, dict[str, dict[str, float]]],
) -> dict | None:
    sector = categories.get("sector")
    sector_metrics = sector_stats.get(sector) if sector else None
    if not sector_metrics:
        return None  # not enough same-sector peers in this run to say anything meaningful

    comparisons = []
    for label, tooltip, direction in _EQUITY_ANALYSIS_METRICS:
        value = _parse_finviz_number(fields.get(tooltip, "-"))
        metric_stats = sector_metrics.get(tooltip)
        if value is None or metric_stats is None:
            continue
        comparisons.append({
            "metric": label,
            "value": value,
            "sector_median": metric_stats["median"],
            "sector_n": metric_stats["n"],
            "read": _read_comparison(value, metric_stats["median"], direction),
        })

    return {
        "type": "equity",
        "sector": sector,
        "industry": categories.get("industry"),
        "comparisons": comparisons,
        "growth_note": _growth_note(charts),
        "methodology": (
            f"Comparación calculada contra la mediana real de las acciones del sector "
            f"‘{sector}’ presentes en este mismo dataset generado (no un promedio de "
            f"mercado externo) — determinista, sin IA."
        ),
    }


def _build_etf_analysis(fields: dict[str, str]) -> dict:
    expense_ratio = _parse_finviz_number(fields.get(_EXPENSE_RATIO_TOOLTIP, "-"))
    if expense_ratio is None:
        expense_read = None
    elif expense_ratio <= 0.001:
        expense_read = "costo muy bajo (≤ 0.10%) — típico de fondos indexados grandes"
    elif expense_ratio <= 0.005:
        expense_read = "costo bajo-moderado (0.10%-0.50%)"
    else:
        expense_read = "costo relativamente alto (> 0.50%) frente a fondos indexados pasivos"

    return {
        "type": "etf",
        "expense_ratio": expense_ratio,
        "expense_ratio_read": expense_read,
        "holdings_count": fields.get("Total count of all holdings in the ETF") or "-",
        "tracked_index": fields.get(
            "Name of the underlying index tracked by the ETF, if applicable"
        ) or "-",
        "category": fields.get("Single category of the ETF") or "-",
        "manager": fields.get("The fund manager (ETF) or issuing bank (ETN)") or "-",
        "methodology": (
            "Este es un fondo (ETF), no una empresa operativa — no aplica comparación de P/E, "
            "márgenes ni ROE contra un sector. Lectura de costo basada en umbrales fijos y "
            "públicos de la industria, no calculados de este dataset."
        ),
    }


def main(tickers: list[str]) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()

    # Pass 1: fetch every ticker's raw snapshot (fields + charts + categories) AND its price
    # history — two requests per ticker now, not one (see finviz.py's get_price_history docstring
    # for why that's a second, distinct endpoint). Kept in memory, not yet written — sector
    # medians (pass 2) need the whole dataset fetched first.
    raw_snapshots: dict[str, dict] = {}
    with FinvizFundamentalsProvider() as provider:
        for i, ticker in enumerate(tickers):
            try:
                snapshot = provider.get_snapshot(ticker)
            except FinvizError as exc:
                logger.warning("[%s] failed, skipping: %s", ticker, exc)
                continue
            finally:
                time.sleep(_REQUEST_DELAY_SECONDS)

            try:
                snapshot["price_history"] = provider.get_price_history(ticker)
            except FinvizError as exc:
                # Grid + analysis are still worth having even if the chart can't be built — don't
                # drop the whole ticker over a second, independent endpoint failing.
                logger.warning("[%s] price history failed, chart will be empty: %s", ticker, exc)
                snapshot["price_history"] = []
            if i < len(tickers) - 1:
                time.sleep(_REQUEST_DELAY_SECONDS)

            raw_snapshots[ticker] = snapshot

    logger.info("Fetched %d/%d tickers — computing sector medians...", len(raw_snapshots), len(tickers))

    # Operational safety net for the daily GH Actions cron: if Finviz starts blocking this
    # scraper wholesale (redesigned markup, IP block, bot-check page — see finviz.py's own
    # disclosed ToS-risk section), every ticker fails and raw_snapshots ends up empty or tiny.
    # Without this guard, the loop below would still write an (empty) index.json over yesterday's
    # good one, and the deployed site would go from "stale but real data" to "broken" in one
    # commit. Abort loudly instead — the workflow step fails, nothing gets committed, the
    # currently-published site (last good run) stays up untouched.
    if len(raw_snapshots) < max(1, len(tickers) // 2):
        raise RuntimeError(
            f"Only {len(raw_snapshots)}/{len(tickers)} tickers succeeded — aborting without "
            "writing any output, so a bad run never overwrites the last good one. If this "
            "persists, finviz.com's markup or access policy likely changed; see finviz.py's "
            "module docstring for what this scraper depends on."
        )

    sector_stats = _compute_sector_stats(raw_snapshots)

    # Pass 2: build each ticker's columns + analysis (now that sector_stats exists) and write.
    index = {"tickers": [], "generated_at": generated_at}
    for ticker, snapshot in raw_snapshots.items():
        is_etf = _is_etf(snapshot["fields"])
        analysis = (
            _build_etf_analysis(snapshot["fields"]) if is_etf
            else _build_equity_analysis(
                snapshot["fields"], snapshot["categories"], snapshot["charts"], sector_stats
            )
        )
        data = {
            "ticker": snapshot["ticker"],
            "generated_at": generated_at,
            "is_etf": is_etf,
            "columns": _extract_columns(snapshot["fields"], is_etf),
            "charts": snapshot["charts"],
            "analysis": analysis,
            "price_history": snapshot["price_history"],
        }
        # Compact, not indent=2: price_history now carries 5 years of daily bars (~1250 entries,
        # see finviz.py's _PRICE_HISTORY_DAYS), and every ticker click on docs/index.html fetches
        # this file fresh over the network — pretty-printing was ~38% of the payload for nothing
        # a browser's fetch()/JSON.parse ever renders. Not meant for humans to read raw.
        (_OUTPUT_DIR / f"{ticker}.json").write_text(json.dumps(data, separators=(",", ":")))
        index["tickers"].append(ticker)
        logger.info("[%s] snapshot written.", ticker)

    (_OUTPUT_DIR / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    logger.info("Wrote %d ticker(s) + index.json to %s", len(index["tickers"]), _OUTPUT_DIR)


if __name__ == "__main__":
    requested = [t.upper() for t in sys.argv[1:]] or TICKERS
    main(requested)
