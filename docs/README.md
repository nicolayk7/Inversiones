# Nicolas Invest (Finviz Snapshot Mirror)

A static, $0-cost, read-only mirror of public Finviz data for ~529 tickers (S&P 500 ∪ Nasdaq-100
+ a few ETFs) — no backend, no database. This is **separate from** the Investment Intelligence
platform itself (Wealth Engine, `apps/web/`): nothing here feeds that pipeline. Every number shown
is either Finviz's own value or computed by deterministic code in this folder — no LLM anywhere.

Live: https://nicolayk7.github.io/Inversiones/

## How it's built

```
scripts/generate_finviz_snapshot_site.py   Finviz -> docs/data/{TICKER}.json + docs/data/index.json
docs/js/logic.js                           pure, DOM-free logic (candle aggregation, SMA, signal,
                                           search, routing) — shared by the page and the tests
docs/index.html                            fetches the JSON, renders everything
tests/js/logic.test.cjs                    tests for docs/js/logic.js (node --test, no npm deps)
.github/workflows/refresh-finviz-snapshot.yml   daily: generate -> validate -> commit
.github/workflows/tests.yml                on every push: pytest + node tests
```

## Run it locally

```bash
python scripts/generate_finviz_snapshot_site.py          # full run, ~6 min, writes docs/data/*.json
cd docs && python -m http.server 8020                    # serve it (file:// can't fetch the JSON)
```

Then open http://localhost:8020.

Tests:

```bash
python -m pytest tests/unit -q
node --test "tests/js/*.test.cjs"
```

## Features worth knowing about

- **Shareable links.** Every view is a URL fragment: `#AAPL`, and `#AAPL+MSFT` for a comparison.
  Back/forward and reload keep the view. Link previews (WhatsApp, X…) use `docs/og-image.png`.
- **Search by ticker or company name** ("visa" finds V), with ↑/↓/Enter/Esc keyboard support.
- **Favorites** are stored in the visitor's own browser (`localStorage`) — nothing server-side.
- **Data freshness.** Each ticker shows "actualizado hace X h"; past 48 h a warning appears, in
  case the daily cron fails again silently (it did once — `httpx` missing, 2026-08-20).

## Analytics (off by default)

`docs/index.html` has a `GOATCOUNTER_CODE` constant. Left empty, nothing is loaded or tracked. To
turn it on: create a free account at https://www.goatcounter.com, then set the constant to your
site code (e.g. `"nicolas"` for `https://nicolas.goatcounter.com`). It then counts one view per
ticker opened (`/AAPL`), clicks on each promo placement (`promo-banner`, `promo-senal`), and
shares. GoatCounter is cookie-free.

Promo links also carry Hotmart's own `src=` parameter (`nicolasinvestbanner` /
`nicolasinvestsenal`), so sales from each placement show up separately in Hotmart's reports even
without GoatCounter.

## Deploy it for free, always-on

**GitHub Pages (what the live site uses):** Repo Settings -> Pages -> Source: `main` branch,
`/docs` folder. The refresh workflow commits new data daily; each commit is a new Pages deploy.
It can also be run on demand from the Actions tab ("Run workflow").

**Netlify:** import the repo, no build command, publish directory `docs`.

## When something fails

- **One ticker fails** (network blip after 3 retries, odd page): the run keeps that ticker's
  previous data (up to 7 days old) and carries on. The site shows that ticker's own older
  "actualizado hace X". Listed as a yellow warning on the Actions run page.
- **A ticker returns 404** (delisted or renamed — WBD in Oct 2026): it's dropped and its data
  file deleted; warning "Tickers no longer on Finviz" on the run page. Refresh `TICKERS` (see the
  comment above `_SP500_NASDAQ100_TICKERS` for the sources).
- **Most tickers fail at once** (Finviz blocking or redesigned): the run aborts, nothing is
  committed, the site keeps the last good data and shows a "más de 2 días" warning after 48 h.
- **Generated data malformed:** the "Validate generated data" step (node tests over every
  ticker) fails and nothing is committed.

## Adding tickers / partial runs

Edit `TICKERS` in the generator, or pass tickers as CLI args for a quick look:

```bash
python scripts/generate_finviz_snapshot_site.py AAPL MSFT NVDA
```

A partial run **merges** into the existing `index.json` (it no longer drops the other tickers),
but its sector medians only include the tickers you passed — so most of them lose their
"Análisis vs. sector" and COMPRAR/VENDER badge. Use it to preview, never commit its output: do a
full run first.
