// Tests for docs/js/logic.js — the site's pure, DOM-free logic. Run: node --test tests/js
// No dependencies beyond Node's built-in test runner (Node 18+).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const L = require("../../docs/js/logic.js");

// -- helpers ------------------------------------------------------------------------------------

function bar(date, open, high, low, close, volume = 100) {
  return { date, open, high, low, close, volume };
}

// Business days only, linear price path — same shape the site's real price_history has.
function makeDailyBars(startIso, endIso, startPrice, endPrice) {
  const days = [];
  for (let d = new Date(`${startIso}T00:00:00Z`); d <= new Date(`${endIso}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1)) {
    const dow = d.getUTCDay();
    if (dow !== 0 && dow !== 6) days.push(d.toISOString().slice(0, 10));
  }
  return days.map((date, i) => {
    const c = startPrice + (endPrice - startPrice) * (i / Math.max(1, days.length - 1));
    return bar(date, c, c * 1.01, c * 0.99, c, 1000);
  });
}

function columns(fields) {
  return [Object.entries(fields).map(([label, value]) => ({ label, value }))];
}

// -- aggregatePriceBars ---------------------------------------------------------------------------

test("daily cadence keeps only the most recent DAILY_VIEW_BARS bars", () => {
  const bars = makeDailyBars("2021-08-23", "2026-08-20", 100, 200);
  const d = L.aggregatePriceBars(bars, "d");
  assert.equal(d.length, L.DAILY_VIEW_BARS);
  assert.equal(d[d.length - 1].date, bars[bars.length - 1].date);
});

test("weekly buckets key on the ISO Monday and fold OHLCV correctly", () => {
  const bars = [
    bar("2026-08-17", 10, 12, 9, 11, 5),  // Monday
    bar("2026-08-19", 11, 15, 10, 14, 7), // Wednesday, same week
    bar("2026-08-21", 14, 14, 8, 9, 3),   // Friday, same week
    bar("2026-08-24", 9, 10, 9, 10, 1),   // next Monday
  ];
  const w = L.aggregatePriceBars(bars, "w");
  assert.deepEqual(w[0], { date: "2026-08-17", open: 10, high: 15, low: 8, close: 9, volume: 15 });
  assert.equal(w[1].date, "2026-08-24");
  assert.equal(w.length, 2);
});

test("a Sunday-dated bar belongs to the week that started the previous Monday", () => {
  const w = L.aggregatePriceBars([bar("2026-08-23", 1, 1, 1, 1)], "w"); // Sunday
  assert.equal(w[0].date, "2026-08-17");
});

test("monthly and yearly cadences bucket by calendar month / year", () => {
  const bars = makeDailyBars("2021-08-23", "2026-08-20", 100, 200);
  const m = L.aggregatePriceBars(bars, "m");
  const y = L.aggregatePriceBars(bars, "y");
  assert.equal(m.length, 61);
  assert.equal(m[0].date, "2021-08-01");
  assert.deepEqual(y.map(b => b.date), ["2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01", "2025-01-01", "2026-01-01"]);
  assert.equal(y[0].open, bars[0].open);
  assert.equal(y[y.length - 1].close, bars[bars.length - 1].close);
});

test("empty input passes through", () => {
  assert.deepEqual(L.aggregatePriceBars([], "m"), []);
});

// -- parseGridNumber ------------------------------------------------------------------------------

test("parseGridNumber handles the grid's real display formats", () => {
  assert.equal(L.parseGridNumber("373.97 -2.20%"), -2.2); // compound: last token wins
  // Suffix multiplication is plain float math (8.19 * 1e6 = 8189999.999999999) — these values are
  // only ever compared against thresholds, never displayed, so assert within a relative epsilon.
  const close = (actual, expected) => assert.ok(Math.abs(actual - expected) <= Math.abs(expected) * 1e-12, `${actual} != ${expected}`);
  close(L.parseGridNumber("8.19M"), 8.19e6);
  close(L.parseGridNumber("4543.17B"), 4543.17e9);
  assert.equal(L.parseGridNumber("40,959,184"), 40959184);
  assert.equal(L.parseGridNumber("48.93"), 48.93);
  assert.equal(L.parseGridNumber("-"), null);
  assert.equal(L.parseGridNumber(null), null);
  assert.equal(L.parseGridNumber("Jul 30 AMC"), null);
});

// -- computeSentiment (pins the verdicts that were hand-verified in the browser earlier) --------

const AAPL_LIKE = {
  price_history: makeDailyBars("2026-01-01", "2026-08-20", 100, 121.7), // ~+21.7% over the window
  columns: columns({ "RSI (14)": "48.93", "52W High": "344.57 -9.66%", "52W Low": "223.78 39.11%" }),
  analysis: {
    type: "equity",
    comparisons: [
      { metric: "P/E", read: "en línea con la mediana del sector" },
      { metric: "P/S", read: "más caro que la mediana del sector" },
      { metric: "EV/EBITDA", read: "más caro que la mediana del sector" },
      { metric: "ROE", read: "por encima de la mediana del sector" },
      { metric: "Margen bruto", read: "por debajo de la mediana del sector" },
      { metric: "Margen operativo", read: "por encima de la mediana del sector" },
    ],
  },
};

test("AAPL-shaped input: fundamentals -1, trend +2 -> composite +1 -> MANTENER at 56.25%", () => {
  const s = L.computeSentiment(AAPL_LIKE);
  assert.equal(s.badge.label, "MANTENER");
  assert.equal(s.gaugePct, 56.25);
  const tally = s.reasons.reduce((acc, r) => acc + r.contribution, 0);
  assert.equal(tally, 1);
  assert.equal(s.reasons.length, 9);
  assert.match(s.verdictExplanation, /4 a favor, 3 en contra, 2 neutral/);
});

test("all-favorable input -> COMPRAR, gauge pinned at 100%", () => {
  const s = L.computeSentiment({
    price_history: makeDailyBars("2026-01-01", "2026-08-20", 100, 130),
    columns: columns({ "RSI (14)": "55", "52W High": "130 -1.00%", "52W Low": "70 60.00%" }),
    analysis: { type: "equity", comparisons: [
      ...["P/E", "P/S", "EV/EBITDA"].map(metric => ({ metric, read: "más barato que la mediana del sector" })),
      ...["ROE", "Margen bruto", "Margen operativo"].map(metric => ({ metric, read: "por encima de la mediana del sector" })),
    ] },
  });
  assert.equal(s.badge.label, "COMPRAR");
  assert.equal(s.gaugePct, 100);
});

test("oversold + sharp drop -> MERCADO CON MIEDO tag; no sector data -> no badge, generic reason", () => {
  const s = L.computeSentiment({
    price_history: makeDailyBars("2026-01-01", "2026-08-20", 100, 75),
    columns: columns({ "RSI (14)": "22", "52W High": "130 -40.00%", "52W Low": "75 2.00%" }),
    analysis: null,
  });
  const labels = s.tags.map(t => t.label);
  assert.ok(labels.includes("MERCADO CON MIEDO"));
  assert.ok(labels.includes("TENDENCIA BAJISTA"));
  assert.equal(s.badge, null);
  assert.match(s.noBadgeReason, /No hay suficientes acciones del mismo sector/);
});

test("ETFs never get a COMPRAR/VENDER badge", () => {
  const s = L.computeSentiment({
    price_history: makeDailyBars("2026-01-01", "2026-08-20", 100, 110),
    columns: columns({ "52W High": "110 -1.00%", "52W Low": "90 20.00%" }),
    analysis: { type: "etf" },
  });
  assert.equal(s.badge, null);
  assert.match(s.noBadgeReason, /ETFs/);
});

test("too little history -> no signal at all rather than a guess", () => {
  assert.equal(L.computeSentiment({ price_history: makeDailyBars("2026-08-17", "2026-08-20", 1, 2), columns: [], analysis: null }), null);
});

// -- SMA ------------------------------------------------------------------------------------------

test("sma is null until the window is full, then exact", () => {
  assert.deepEqual(L.sma([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
  assert.deepEqual(L.sma([1, 2], 3), [null, null]);
});

test("daily SMA-200 covers the whole displayed window when 5y of history exists", () => {
  const bars = makeDailyBars("2021-08-23", "2026-08-20", 100, 200);
  const [s50, s200] = L.smaSeriesForView(bars, "d");
  assert.equal(s50.period, 50);
  assert.equal(s200.period, 200);
  assert.equal(s200.values.length, L.DAILY_VIEW_BARS);
  assert.ok(s200.values.every(v => v !== null));
  // SMA of a straight line lags the line: last SMA-50 is below the last close on an uptrend.
  assert.ok(s50.values[s50.values.length - 1] < bars[bars.length - 1].close);
});

test("monthly SMA lines align 1:1 with the monthly candles", () => {
  const bars = makeDailyBars("2021-08-23", "2026-08-20", 100, 200);
  const m = L.aggregatePriceBars(bars, "m");
  const lines = L.smaSeriesForView(bars, "m");
  assert.deepEqual(lines.map(l => l.period), [10, 40]);
  lines.forEach(l => assert.equal(l.values.length, m.length));
  assert.equal(lines[0].values[8], null);
  assert.notEqual(lines[0].values[9], null);
});

test("formatBarLabel describes what one candle covers", () => {
  assert.equal(L.formatBarLabel("2026-08-20", "d"), "2026-08-20");
  assert.equal(L.formatBarLabel("2026-08-17", "w"), "semana del 2026-08-17");
  assert.equal(L.formatBarLabel("2026-08-01", "m"), "agosto 2026");
  assert.equal(L.formatBarLabel("2026-01-01", "m"), "enero 2026");
  assert.equal(L.formatBarLabel("2026-01-01", "y"), "2026");
});

test("formatVolume abbreviates", () => {
  assert.equal(L.formatVolume(40959184), "40.96M");
  assert.equal(L.formatVolume(2.5e9), "2.50B");
  assert.equal(L.formatVolume(8190), "8.2K");
  assert.equal(L.formatVolume(512), "512");
  assert.equal(L.formatVolume(null), "-");
});

// -- search ---------------------------------------------------------------------------------------

const TICKERS = ["A", "AAPL", "BRK-B", "V", "VEEV", "VZ", "NSRGY"];
const NAMES = { AAPL: "Apple Inc", "BRK-B": "Berkshire Hathaway Inc", V: "Visa Inc", VZ: "Verizon Communications Inc", NSRGY: "Nestlé SA" };

test("search finds a company by name, case-insensitive", () => {
  assert.deepEqual(L.searchTickers("visa", TICKERS, NAMES).map(r => r.ticker), ["V"]);
  assert.deepEqual(L.searchTickers("berkshire", TICKERS, NAMES).map(r => r.ticker), ["BRK-B"]);
});

test("search ranks exact ticker, then prefix, then substring, then name", () => {
  assert.deepEqual(L.searchTickers("v", TICKERS, NAMES).map(r => r.ticker), ["V", "VEEV", "VZ"]);
});

test("search ignores accents in company names", () => {
  assert.deepEqual(L.searchTickers("nestle", TICKERS, NAMES).map(r => r.ticker), ["NSRGY"]);
});

test("search works with no names map (older index.json)", () => {
  assert.deepEqual(L.searchTickers("aap", TICKERS, undefined).map(r => r.ticker), ["AAPL"]);
  assert.deepEqual(L.searchTickers("   ", TICKERS, NAMES), []);
});

// -- deep links -----------------------------------------------------------------------------------

test("tickerFromHash accepts known tickers in any case, rejects everything else", () => {
  const avail = new Set(TICKERS);
  assert.equal(L.tickerFromHash("#aapl", avail), "AAPL");
  assert.equal(L.tickerFromHash("#BRK-B", avail), "BRK-B");
  assert.equal(L.tickerFromHash("#%20v", avail), "V");
  assert.equal(L.tickerFromHash("#ZZZZ", avail), null);
  assert.equal(L.tickerFromHash("", avail), null);
  assert.equal(L.tickerFromHash("#%E0%A4%A", avail), null); // malformed escape must not throw
});

test("parseRoute / routeHash round-trip, including a comparison", () => {
  const avail = new Set(TICKERS);
  assert.deepEqual(L.parseRoute("#aapl", avail), { ticker: "AAPL", compare: null, unknown: [] });
  assert.deepEqual(L.parseRoute("#AAPL+v", avail), { ticker: "AAPL", compare: "V", unknown: [] });
  assert.deepEqual(L.parseRoute("#AAPL+ZZZZ", avail), { ticker: "AAPL", compare: null, unknown: ["ZZZZ"] });
  assert.deepEqual(L.parseRoute("#AAPL+AAPL", avail), { ticker: "AAPL", compare: null, unknown: [] });
  assert.deepEqual(L.parseRoute("#ZZZZ+AAPL", avail), { ticker: null, compare: null, unknown: ["ZZZZ"] });
  assert.deepEqual(L.parseRoute("", avail), { ticker: null, compare: null, unknown: [] });
  assert.deepEqual(L.parseRoute("#wbd", avail).unknown, ["WBD"]);
  assert.equal(L.routeHash("AAPL", "V"), "#AAPL+V");
  assert.equal(L.routeHash("BRK-B", null), "#BRK-B");
  assert.deepEqual(L.parseRoute(L.routeHash("BRK-B", "V"), avail), { ticker: "BRK-B", compare: "V", unknown: [] });
});

test("escapeHtml neutralizes markup in scraped names", () => {
  assert.equal(L.escapeHtml(`S&P <b>"x"</b> 'y'`), "S&amp;P &lt;b&gt;&quot;x&quot;&lt;/b&gt; &#39;y&#39;");
});

// -- freshness ------------------------------------------------------------------------------------

test("dataFreshness labels age and flags data older than 48h", () => {
  const now = Date.parse("2026-09-24T12:00:00Z");
  assert.deepEqual(
    { ...L.dataFreshness("2026-09-24T00:12:53Z", now), hours: undefined },
    { hours: undefined, label: "hace 11 h", stale: false },
  );
  assert.equal(L.dataFreshness("2026-09-24T11:30:00Z", now).label, "hace menos de 1 h");
  const old = L.dataFreshness("2026-09-20T12:00:00Z", now);
  assert.equal(old.label, "hace 4 días");
  assert.equal(old.stale, true);
  assert.equal(L.dataFreshness("not a date", now), null);
});

// -- comparison -----------------------------------------------------------------------------------

test("rebasedComparison uses common dates only and starts both series at 100", () => {
  const a = [bar("2026-01-02", 0, 0, 0, 50), bar("2026-01-05", 0, 0, 0, 55), bar("2026-01-06", 0, 0, 0, 60)];
  const b = [bar("2026-01-02", 0, 0, 0, 200), bar("2026-01-06", 0, 0, 0, 180)]; // missing 01-05
  const c = L.rebasedComparison(a, b);
  assert.deepEqual(c, [
    { date: "2026-01-02", a: 100, b: 100 },
    { date: "2026-01-06", a: 120, b: 90 },
  ]);
  assert.equal(L.rebasedComparison(a, [bar("2030-01-01", 0, 0, 0, 1)]), null);
});

// -- real generated data (structure only — values change daily) ---------------------------------

// This block is also the daily refresh workflow's gate before it commits new data: it walks EVERY
// ticker in the freshly generated index, so a malformed file anywhere blocks publishing instead of
// shipping a broken page for that ticker.
const DATA_DIR = path.join(__dirname, "..", "..", "docs", "data");
const INDEX_FILE = path.join(DATA_DIR, "index.json");
const hasData = fs.existsSync(INDEX_FILE);

test("generated index and data files match one-to-one", { skip: !hasData && "no docs/data" }, () => {
  const index = JSON.parse(fs.readFileSync(INDEX_FILE, "utf8"));
  assert.ok(index.tickers.length > 400, `only ${index.tickers.length} tickers in index.json`);
  assert.equal(new Set(index.tickers).size, index.tickers.length, "duplicate tickers in index.json");
  const files = fs.readdirSync(DATA_DIR).filter(f => f.endsWith(".json") && f !== "index.json").map(f => f.slice(0, -5));
  const listed = new Set(index.tickers);
  assert.deepEqual(index.tickers.filter(t => !files.includes(t)), [], "listed tickers with no data file");
  assert.deepEqual(files.filter(t => !listed.has(t)), [], "orphaned data files not in index.json");
  const unnamed = index.tickers.filter(t => !index.names || !index.names[t]);
  assert.ok(unnamed.length <= 5, `too many tickers without a company name: ${unnamed.join(", ")}`);
});

test("every generated ticker renders: all cadences, SMAs, and a well-formed signal", { skip: !hasData && "no docs/data" }, () => {
  const index = JSON.parse(fs.readFileSync(INDEX_FILE, "utf8"));
  const finite = v => typeof v === "number" && Number.isFinite(v);
  for (const t of index.tickers) {
    const data = JSON.parse(fs.readFileSync(path.join(DATA_DIR, `${t}.json`), "utf8"));
    assert.equal(data.ticker, t, `${t}: ticker field mismatch`);
    assert.ok(Array.isArray(data.columns) && data.columns.length > 0, `${t}: no grid columns`);
    assert.ok(!Number.isNaN(Date.parse(data.generated_at)), `${t}: bad generated_at`);
    const ph = data.price_history || [];
    for (const b of ph) {
      assert.ok(/^\d{4}-\d{2}-\d{2}$/.test(b.date) && ["open", "high", "low", "close", "volume"].every(k => finite(b[k])),
        `${t}: malformed bar ${JSON.stringify(b)}`);
    }
    for (let i = 1; i < ph.length; i++) assert.ok(ph[i - 1].date < ph[i].date, `${t}: bars not strictly oldest-first at ${ph[i].date}`);
    if (ph.length === 0) continue; // page shows "Sin historial de precio" — legitimate, not a crash
    for (const c of ["d", "w", "m", "y"]) {
      const shown = L.aggregatePriceBars(ph, c);
      assert.ok(shown.length > 0, `${t}/${c}: no bars`);
      for (const l of L.smaSeriesForView(ph, c)) {
        assert.equal(l.values.length, shown.length, `${t}/${c}: SMA ${l.period} misaligned`);
        assert.ok(l.values.every(v => v === null || finite(v)), `${t}/${c}: non-finite SMA`);
      }
    }
    const s = L.computeSentiment(data);
    if (ph.length < 10) { assert.equal(s, null, `${t}: signal from <10 bars`); continue; }
    assert.ok(s && s.gaugePct >= 0 && s.gaugePct <= 100, `${t}: gauge out of range`);
    assert.equal(Boolean(s.badge), !data.is_etf && Boolean(data.analysis && data.analysis.comparisons), `${t}: badge presence`);
  }
});

test("most equities carry a sector analysis (guards the 2026-11-04 silent wipe)", { skip: !hasData && "no docs/data" }, () => {
  const index = JSON.parse(fs.readFileSync(INDEX_FILE, "utf8"));
  const equities = index.tickers
    .map(t => JSON.parse(fs.readFileSync(path.join(DATA_DIR, `${t}.json`), "utf8")))
    .filter(d => !d.is_etf);
  const missing = equities.filter(d => !d.analysis).map(d => d.ticker);
  assert.ok(missing.length <= equities.length * 0.1,
    `${missing.length}/${equities.length} equities have no sector analysis (e.g. ${missing.slice(0, 5).join(", ")})`);
});

// -- SEC EDGAR fundamentals -----------------------------------------------------------------------

function secFixture(overrides = {}) {
  return {
    status: "ok",
    years: [
      { period_end: "2025-09-27", label: "FY2025", first_filed: "2025-10-31" },
      { period_end: "2026-09-26", label: "FY2026", first_filed: "2026-11-03" },
    ],
    metrics: [
      { key: "revenue", unit: "USD", values: [416161000000, 478834000000] },
      { key: "eps_diluted", unit: "USD/shares", values: [7.46, 8.98] },
    ],
    ...overrides,
  };
}

test("formatSecValue scales dollars and keeps per-share values plain", () => {
  assert.equal(L.formatSecValue(478834000000, "USD"), "478.8B");
  assert.equal(L.formatSecValue(-147782000000, "USD"), "-147.8B");
  assert.equal(L.formatSecValue(715000000, "USD"), "715.0M");
  assert.equal(L.formatSecValue(5.2e12, "USD"), "5.20T");
  assert.equal(L.formatSecValue(8.98, "USD/shares"), "8.98");
  assert.equal(L.formatSecValue(null, "USD"), "—");
});

test("secCrossCheck matches Finviz's bar with the same fiscal-year label", () => {
  const charts = {
    sales: { annual: [{ name: "2025", value: 416161 }, { name: "2026", value: 478834 }] },
    eps: { annual: [{ name: "2026", value: 8.979 }] },
  };
  const rows = L.secCrossCheck(secFixture(), charts);
  assert.deepEqual(rows.map(r => [r.key, r.fiscal, r.match]), [["revenue", "FY2026", true], ["eps_diluted", "FY2026", true]]);
  assert.equal(rows[0].finviz, 478834e6);
});

test("secCrossCheck flags a real difference and skips what one source lacks", () => {
  const charts = { sales: { annual: [{ name: "2026", value: 440000 }] } }; // ~8% off, no EPS bars
  const rows = L.secCrossCheck(secFixture(), charts);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].match, false);
  assert.ok(rows[0].diffPct > 7 && rows[0].diffPct < 9);
  assert.deepEqual(L.secCrossCheck(secFixture(), { sales: { annual: [{ name: "2025", value: 1 }] } }), []);
  assert.deepEqual(L.secCrossCheck({ status: "no_10k" }, charts), []);
  assert.deepEqual(L.secCrossCheck(secFixture(), null), []);
});

test("secIsStale after ~15 months without a new fiscal year", () => {
  const sec = secFixture();
  assert.equal(L.secIsStale(sec, Date.parse("2027-06-01T00:00:00Z")), false);
  assert.equal(L.secIsStale(sec, Date.parse("2028-01-15T00:00:00Z")), true);
  assert.equal(L.secIsStale({ status: "no_10k" }, Date.now()), false);
});

const SEC_DIR = path.join(DATA_DIR, "sec");
const hasSec = fs.existsSync(SEC_DIR);

test("generated SEC files are well-formed and belong to listed equities", { skip: !hasSec && "no docs/data/sec" }, () => {
  const index = JSON.parse(fs.readFileSync(INDEX_FILE, "utf8"));
  const listed = new Set(index.tickers);
  const files = fs.readdirSync(SEC_DIR).filter(f => f.endsWith(".json"));
  assert.ok(files.length > 400, `only ${files.length} SEC files`);
  let ok = 0;
  for (const f of files) {
    const t = f.slice(0, -5);
    const sec = JSON.parse(fs.readFileSync(path.join(SEC_DIR, f), "utf8"));
    assert.ok(listed.has(t), `${t}: SEC file for a ticker not in index.json`);
    assert.equal(sec.ticker, t, `${t}: ticker field mismatch`);
    assert.ok(["ok", "no_10k", "not_in_sec"].includes(sec.status), `${t}: unknown status ${sec.status}`);
    if (sec.status !== "ok") continue;
    ok++;
    assert.ok(sec.years.length >= 1 && sec.years.length <= 5, `${t}: ${sec.years.length} years`);
    for (let i = 1; i < sec.years.length; i++) assert.ok(sec.years[i - 1].period_end < sec.years[i].period_end, `${t}: years not oldest-first`);
    for (const m of sec.metrics) {
      assert.equal(m.values.length, sec.years.length, `${t}/${m.key}: values misaligned with years`);
      assert.ok(m.values.every(v => v === null || (typeof v === "number" && Number.isFinite(v))), `${t}/${m.key}: non-numeric value`);
    }
    assert.ok(/^https:\/\/www\.sec\.gov\/Archives\/edgar\/data\/\d+\/\d+\/$/.test(sec.latest_10k.url), `${t}: bad filing url`);
    const data = JSON.parse(fs.readFileSync(path.join(DATA_DIR, `${t}.json`), "utf8"));
    L.secCrossCheck(sec, data.charts); // must not throw on any real pairing
  }
  assert.ok(ok > files.length * 0.8, `only ${ok}/${files.length} SEC files have 10-K data`);
});
