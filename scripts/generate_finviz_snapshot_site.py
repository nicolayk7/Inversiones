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
small pause between them so a 518-ticker run (~12 minutes end to end) still reads as "one script
working through a list slowly," not a burst. That is a real, deliberate increase in daily request
volume over this generator's original 4/100-ticker versions — still one controlled runner, one
request at a time, once a day, but worth being explicit about rather than letting the list grow
without remark.

FIELD_LAYOUT is a curated, high-confidence subset of the ~84 fields Finviz's quote page exposes —
every entry's tooltip key was verified present on a live fetch during development, cross-checked
against `provider.get_snapshot(ticker)["fields"]`'s actual key list (72 of 84), not assumed from
the visible page alone. 12 real fields (the three "Short interest*" rows, Recom, Target Price,
Dividend Est./TTM/Ex-Date/Gr., Payout, EPS/Sales Surpr., Earnings date) are silently absent from
EVERY fetch, not just missing their value — their on-page label `<div>` holds something other than
plain text in the raw HTML (an icon, most likely), which `finviz.py`'s `_ROW_PATTERN` regex
(deliberately strict: `[^<]*` inside the label div) does not match, so the whole row never enters
`get_snapshot`'s fields dict at all. Verified by diffing `get_snapshot`'s actual key count (72)
against every tooltip enumerated from the raw page during development (84) — the 12-field gap is
exactly this set. Omitted from this layout rather than guessed at or shown as a false "-", per this
codebase's disclosure-over-guessing rule (see finviz.py's module docstring for the same principle).

Usage:
    python scripts/generate_finviz_snapshot_site.py                  # all TICKERS
    python scripts/generate_finviz_snapshot_site.py AAPL MSFT NVDA   # any tickers you like
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from packages.providers.fundamentals.finviz import FinvizError, FinvizFundamentalsProvider

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("generate_finviz_snapshot_site")

_REQUEST_DELAY_SECONDS = 0.6

# S&P 500 ∪ Nasdaq-100, 518 unique tickers, alphabetical — see module docstring for exact sourcing
# (Wikipedia + slickcharts.com, fetched live 2026-08-20) and the BRK.B/BF.B -> BRK-B/BF-B rewrite.
# Re-running the two fetches later will drift from this list as index membership changes; this is
# a point-in-time snapshot of membership, not a live-synced one.
TICKERS = [
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


def _extract_columns(raw_fields: dict[str, str]) -> list[list[dict]]:
    return [
        [{"label": label, "value": raw_fields.get(tooltip, "-")} for label, tooltip in column]
        for column in FIELD_LAYOUT
    ]


def _generate_one(ticker: str, provider: FinvizFundamentalsProvider) -> dict:
    snapshot = provider.get_snapshot(ticker)
    return {
        "ticker": snapshot["ticker"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "columns": _extract_columns(snapshot["fields"]),
        "charts": snapshot["charts"],
    }


def main(tickers: list[str]) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    index = {"tickers": [], "generated_at": generated_at}

    with FinvizFundamentalsProvider() as provider:
        for i, ticker in enumerate(tickers):
            try:
                data = _generate_one(ticker, provider)
            except FinvizError as exc:
                logger.warning("[%s] failed, skipping: %s", ticker, exc)
            else:
                (_OUTPUT_DIR / f"{ticker}.json").write_text(json.dumps(data, indent=2))
                index["tickers"].append(ticker)
                logger.info("[%s] snapshot written.", ticker)
            if i < len(tickers) - 1:
                time.sleep(_REQUEST_DELAY_SECONDS)

    (_OUTPUT_DIR / "index.json").write_text(json.dumps(index, indent=2))
    logger.info("Wrote %d ticker(s) + index.json to %s", len(index["tickers"]), _OUTPUT_DIR)


if __name__ == "__main__":
    requested = [t.upper() for t in sys.argv[1:]] or TICKERS
    main(requested)
