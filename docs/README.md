# Finviz Snapshot Mirror

A static, $0-cost, read-only mirror of public Finviz data for a handful of tickers — no backend,
no database. This is **separate from** the Investment Intelligence platform itself (Wealth Engine,
`apps/web/`): it does not compute any score, it just displays what Finviz's free quote page shows,
refreshed periodically.

## How it's built

```
scripts/generate_finviz_snapshot_site.py   Finviz -> docs/data/{TICKER}.json + docs/data/index.json
docs/index.html                            reads those JSON files, renders the grid + charts
.github/workflows/refresh-finviz-snapshot.yml   runs the generator daily, commits what changed
```

## Run it locally

```bash
python scripts/generate_finviz_snapshot_site.py          # writes docs/data/*.json
cd docs && python -m http.server 8020                    # docs/index.html needs to be served,
```                                                       # not opened as a file:// URL — the page
                                                           # fetches JSON, which file:// blocks.
Then open http://localhost:8020.

## Deploy it for free, always-on

Two options, both genuinely free with no expiry:

**GitHub Pages (recommended — zero extra setup once pushed):**
1. Push this repo to GitHub.
2. Repo Settings -> Pages -> Source: `main` branch, `/docs` folder. Save.
3. Your site is live at `https://<you>.github.io/<repo>/`.
4. The included GitHub Actions workflow (`.github/workflows/refresh-finviz-snapshot.yml`) already
   refreshes `docs/data/*.json` once a day automatically (and on-demand via the Actions tab's "Run
   workflow" button) — every refresh it commits is a new Pages deploy, no extra config needed.

**Netlify:**
1. Push this repo to GitHub.
2. In Netlify: "Add new site" -> "Import an existing project" -> pick this repo.
3. Build command: none. Publish directory: `docs`.
4. Same GitHub Actions workflow keeps `docs/data/*.json` fresh; Netlify auto-redeploys on every
   push to `main`, same as Pages.

## Adding tickers

`scripts/generate_finviz_snapshot_site.py`'s `TICKERS` list is independent of the rest of the
repo (no CIK mapping needed, unlike SEC EDGAR) — edit that list, or pass tickers as CLI args:

```bash
python scripts/generate_finviz_snapshot_site.py AAPL MSFT NVDA TSLA
```
