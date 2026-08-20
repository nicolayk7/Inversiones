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
mapping (Finviz scraping doesn't require one), so it isn't restricted to that set. It is a
hand-picked "commonly searched, liquid large-cap" watchlist for this static site's search box —
NOT an index constituent list, NOT the Wealth Engine's `universe_definition`, and must never be
conflated with either (CLAUDE.md's Equity Universe vs. Market Context split governs THAT list, not
this one — this generator's output never reaches Wealth Engine). Pass tickers as CLI args to
override or narrow it for a single run.

On-demand, arbitrary-ticker search from the browser is deliberately NOT how this works: a static
site's client-side JS cannot fetch finviz.com directly (no CORS allow-origin from Finviz, and even
if there were, it would mean every visitor's browser independently scraping Finviz — unbounded
volume, the opposite of the low-volume discipline finviz.py's module docstring commits to). The
approach here instead: pre-generate a broad-but-bounded watchlist once a day from ONE controlled
runner (the GitHub Actions cron), and let the page's search box filter that already-fetched index
client-side. `docs/index.html`'s search feels instant because it's a local filter, not a live call.

A larger TICKERS list means more sequential requests per run — `_REQUEST_DELAY_SECONDS` adds a
small pause between them so a ~100-ticker run still reads as "one script working through a list
slowly," not a burst.

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

# Hand-picked large-cap/liquid watchlist spanning sectors — see module docstring for what this
# list is (and isn't). Feel free to extend; each entry needs nothing beyond being a real Finviz
# ticker symbol (no CIK, no pre-registration anywhere else in this repo).
TICKERS = [
    # Technology
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AVGO", "ORCL", "ADBE",
    "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU", "UBER",
    "SHOP", "PANW", "SNPS", "CDNS", "ADI", "MU", "LRCX", "AMAT", "KLAC", "PYPL",
    # Financials
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "SCHW", "AXP", "V",
    "MA", "SPGI", "ICE", "CME",
    # Healthcare
    "UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "ISRG", "CVS", "MDT",
    # Consumer
    "WMT", "PG", "KO", "PEP", "COST", "MCD", "NKE", "SBUX", "HD", "LOW",
    "TGT", "DIS", "NFLX", "CMCSA", "BKNG",
    # Industrials
    "BA", "CAT", "GE", "HON", "UPS", "RTX", "LMT", "DE", "UNP", "MMM", "ETN",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG",
    # Communications / Telecom
    "T", "VZ", "TMUS",
    # Materials
    "LIN", "APD",
    # Utilities
    "NEE", "DUK",
    # Real Estate
    "AMT", "PLD",
    # Industrials/other
    "ADP",
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
