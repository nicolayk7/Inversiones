// Pure, DOM-free logic for docs/index.html — loaded as a plain <script> before the page's inline
// script (top-level declarations are shared globals between classic scripts), and require()-able
// from Node so tests/js/logic.test.cjs can exercise it directly. Nothing here touches the DOM,
// fetch(), or storage: same inputs, same outputs, which is what makes it testable at all.
//
// Moved here verbatim from index.html (2026-09-24) — aggregatePriceBars and the whole
// signal/sentiment block — then extended (Año cadence, SMA, search, freshness, hash routing,
// comparison). Behavior of the moved code is unchanged; the tests pin it.

// Daily candles stay on-screen only for a recent, legible window — plotting all ~1250 trading
// days at once would compress each candle to under a pixel. Semana/Mes summarize the full ~5-year
// fetch instead, which is exactly where that much history is useful.
const DAILY_VIEW_BARS = 130; // ~6 trading months

// Buckets daily OHLCV bars into ISO weeks (Monday start), calendar months, or calendar years. Input bars are
// always oldest-first (see get_price_history's docstring), and Map preserves insertion order, so
// the aggregate comes out oldest-first too without a separate sort. Open/close are the first/
// last daily bar folded into each bucket; high/low are the bucket's extremes; volume sums.
function aggregatePriceBars(bars, cadence) {
  if (!bars || bars.length === 0) return bars;
  if (cadence === "d") return bars.slice(-DAILY_VIEW_BARS);
  const buckets = new Map();
  for (const b of bars) {
    const d = new Date(`${b.date}T00:00:00Z`);
    let key;
    if (cadence === "w") {
      const isoDow = (d.getUTCDay() + 6) % 7; // Monday = 0 ... Sunday = 6
      const monday = new Date(d);
      monday.setUTCDate(d.getUTCDate() - isoDow);
      key = monday.toISOString().slice(0, 10);
    } else if (cadence === "y") {
      key = `${b.date.slice(0, 4)}-01-01`;
    } else {
      key = `${b.date.slice(0, 7)}-01`;
    }
    const bucket = buckets.get(key);
    if (!bucket) {
      buckets.set(key, { date: key, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume });
    } else {
      bucket.high = Math.max(bucket.high, b.high);
      bucket.low = Math.min(bucket.low, b.low);
      bucket.close = b.close;
      bucket.volume += b.volume;
    }
  }
  return [...buckets.values()];
}

// -- Signal / sentiment section (client-side, deterministic, no AI, no extra Finviz requests) --
// Reuses data this ticker's own JSON already carries: the RSI/Beta/52-week fields shown in the
// grid above, the same price_history behind the candlestick chart, and (for equities) the
// sector-median valuation/quality comparisons already computed server-side for the "Análisis"
// section. Fixed rules, same for every ticker and every visitor — not a personalized
// recommendation, just a mechanical reading of public numbers, same spirit as the rest of this
// page (see CLAUDE.md: every number here comes from code, never an LLM guess).

// Parses a grid cell's display string back into a number: "-" -> null, trailing "%" -> stripped
// (kept as a plain percentage number, e.g. "-2.20%" -> -2.20, NOT a fraction), K/M/B/T suffix
// handled, and for compound cells like 52W High's "373.97 -2.20%" only the LAST whitespace-
// separated token is used (the % distance, not the price).
function parseGridNumber(raw) {
  if (raw === undefined || raw === null) return null;
  const text = String(raw).trim();
  if (!text || text === "-") return null;
  let token = text.split(/\s+/).pop().replace(/,/g, "");
  const isPct = token.endsWith("%");
  if (isPct) token = token.slice(0, -1);
  const suffix = token.slice(-1);
  const mult = { K: 1e3, M: 1e6, B: 1e9, T: 1e12 }[suffix];
  if (mult) token = token.slice(0, -1);
  const n = parseFloat(token);
  if (Number.isNaN(n)) return null;
  return mult ? n * mult : n;
}

function findColumnValue(columns, label) {
  for (const col of columns) {
    const f = col.find(x => x.label === label);
    if (f) return f.value;
  }
  return null;
}

// Realized volatility of the actual candles shown above: daily-return std dev, annualized
// (× √252 trading days/year) and expressed as a percentage — a measure of how much THIS asset's
// own price has swung, independent of Finviz's Beta (which measures movement relative to the
// broad market, not in absolute terms).
function computeAnnualizedVolatility(bars) {
  if (!bars || bars.length < 10) return null;
  const returns = [];
  for (let i = 1; i < bars.length; i++) {
    const prev = bars[i - 1].close;
    if (prev) returns.push((bars[i].close - prev) / prev);
  }
  if (returns.length < 5) return null;
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / (returns.length - 1);
  return Math.sqrt(variance) * Math.sqrt(252) * 100;
}

// -6..+6: tallies the same "read" verdicts already shown in the "Análisis vs. sector" section
// (cheaper-than-median or above-median-quality = +1, more-expensive or below-median = -1, in
// line = 0). Returns null for ETFs or when there weren't enough sector peers to compare against.
// `reasons` carries one entry per metric so the UI can explain exactly which factors pushed the
// score up or down, not just the final number.
function fundamentalsBreakdown(analysis) {
  if (!analysis || analysis.type !== "equity" || !analysis.comparisons) return null;
  const reasons = analysis.comparisons.map(c => {
    let contribution = 0;
    if (c.read.includes("más barato") || c.read.includes("por encima")) contribution = 1;
    else if (c.read.includes("más caro") || c.read.includes("por debajo")) contribution = -1;
    return { label: c.metric, detail: c.read, contribution };
  });
  return { score: reasons.reduce((sum, r) => sum + r.contribution, 0), reasons };
}

// -2..+2: price change over the recent window, plus proximity to the 52-week high/low. Also
// returns `reasons` (same shape as fundamentalsBreakdown's) so both feed the same explanation UI.
function computeTrend(rawBars, columns) {
  const first = rawBars[0], last = rawBars[rawBars.length - 1];
  const periodChangePct = first.close ? ((last.close - first.close) / first.close) * 100 : null;
  const distHigh = parseGridNumber(findColumnValue(columns, "52W High"));
  const distLow = parseGridNumber(findColumnValue(columns, "52W Low"));
  const reasons = [];
  let score = 0;

  if (periodChangePct !== null) {
    if (periodChangePct > 5) {
      score += 1;
      reasons.push({ label: "Momentum de precio", contribution: 1,
        detail: `subió ${periodChangePct.toFixed(1)}% en el período reciente mostrado arriba (más de +5%).` });
    } else if (periodChangePct < -5) {
      score -= 1;
      reasons.push({ label: "Momentum de precio", contribution: -1,
        detail: `cayó ${Math.abs(periodChangePct).toFixed(1)}% en el período reciente mostrado arriba (más de -5%).` });
    } else {
      reasons.push({ label: "Momentum de precio", contribution: 0,
        detail: `variación de ${periodChangePct >= 0 ? "+" : ""}${periodChangePct.toFixed(1)}% en el período reciente — dentro del rango neutral (-5% a +5%).` });
    }
  }
  if (distHigh !== null) {
    if (distHigh >= -10) {
      score += 1;
      reasons.push({ label: "Cercanía al máximo de 52 semanas", contribution: 1,
        detail: `a solo ${Math.abs(distHigh).toFixed(1)}% del máximo de 52 semanas — cerca de máximos suele leerse como fortaleza.` });
    } else {
      reasons.push({ label: "Cercanía al máximo de 52 semanas", contribution: 0,
        detail: `${Math.abs(distHigh).toFixed(1)}% por debajo del máximo de 52 semanas.` });
    }
  }
  if (distLow !== null) {
    if (distLow <= 10) {
      score -= 1;
      reasons.push({ label: "Cercanía al mínimo de 52 semanas", contribution: -1,
        detail: `solo ${distLow.toFixed(1)}% por encima del mínimo de 52 semanas — cerca de mínimos suele leerse como debilidad.` });
    } else {
      reasons.push({ label: "Cercanía al mínimo de 52 semanas", contribution: 0,
        detail: `${distLow.toFixed(1)}% por encima del mínimo de 52 semanas.` });
    }
  }
  return { score, periodChangePct, distHigh, distLow, reasons };
}

function computeSentiment(data) {
  const rawBars = data.price_history;
  if (!rawBars || rawBars.length < 10) return null;

  // Trend/volatility are meant as a short/medium-term read (this is a "signal", not a 5-year
  // backtest) — use the same recent window as the Día chart, not the full multi-year fetch that
  // price_history now carries for the Semana/Mes cadences.
  const recentBars = rawBars.slice(-DAILY_VIEW_BARS);

  const rsi = parseGridNumber(findColumnValue(data.columns, "RSI (14)"));
  const vol = computeAnnualizedVolatility(recentBars);
  const trend = computeTrend(recentBars, data.columns);
  const fBreakdown = fundamentalsBreakdown(data.analysis);
  const fScore = fBreakdown ? fBreakdown.score : null;
  const composite = fScore !== null ? fScore + trend.score : null;
  const reasons = [...(fBreakdown ? fBreakdown.reasons : []), ...trend.reasons];

  let badge = null;
  let noBadgeReason = null;
  if (composite !== null) {
    if (composite >= 3) badge = { label: "COMPRAR", cls: "pos" };
    else if (composite <= -3) badge = { label: "VENDER", cls: "neg" };
    else badge = { label: "MANTENER", cls: "" };
  } else if (data.analysis && data.analysis.type === "etf") {
    noBadgeReason = "Los ETFs no reciben esta señal compuesta: no aplica una comparación de "
      + "valoración/calidad vs. sector a un fondo (mismo criterio que en “Análisis del "
      + "fondo” arriba). Sí se muestran abajo las lecturas de tendencia, volatilidad y RSI.";
  } else {
    noBadgeReason = "No hay suficientes acciones del mismo sector en este dataset generado para "
      + "la parte de valoración de esta señal (ver sección “Análisis” arriba) — se "
      + "omite en vez de mostrar algo poco confiable.";
  }
  // Composite ranges roughly -8..+8 (fundamentals ±6, trend ±2) -> 0..100% gauge position.
  const gaugePct = composite === null ? 50 : Math.max(0, Math.min(100, ((composite + 8) / 16) * 100));

  // Plain-language explanation of WHY this particular verdict came out, referencing the actual
  // score and the +3/-3 thresholds — not just "trust the badge".
  let verdictExplanation = null;
  if (badge) {
    const favor = reasons.filter(r => r.contribution > 0).length;
    const contra = reasons.filter(r => r.contribution < 0).length;
    const neutral = reasons.filter(r => r.contribution === 0).length;
    const tally = `${favor} a favor, ${contra} en contra${neutral ? `, ${neutral} neutral(es)` : ""}`;
    if (badge.label === "COMPRAR") {
      verdictExplanation = `Puntaje compuesto: ${composite >= 0 ? "+" : ""}${composite} (rango posible -8 a +8). `
        + `Salió COMPRAR porque ${tally}, y el total llegó a +3 o más, el umbral que usa esta señal para sugerir compra.`;
    } else if (badge.label === "VENDER") {
      verdictExplanation = `Puntaje compuesto: ${composite} (rango posible -8 a +8). `
        + `Salió VENDER porque ${tally}, y el total cayó a -3 o menos, el umbral que usa esta señal para sugerir venta.`;
    } else {
      verdictExplanation = `Puntaje compuesto: ${composite >= 0 ? "+" : ""}${composite} (rango posible -8 a +8). `
        + `Salió MANTENER porque ${tally}, y el total quedó entre -2 y +2 — ni suficientemente positivo `
        + `(se necesita +3 o más para COMPRAR) ni suficientemente negativo (se necesita -3 o menos para VENDER).`;
    }
  }

  const tags = [];
  if (trend.periodChangePct !== null) {
    if (trend.periodChangePct > 5) tags.push({ label: "TENDENCIA ALCISTA", cls: "pos" });
    else if (trend.periodChangePct < -5) tags.push({ label: "TENDENCIA BAJISTA", cls: "neg" });
    else tags.push({ label: "TENDENCIA LATERAL", cls: "" });
  }
  if (rsi !== null) {
    if (rsi >= 70) tags.push({ label: "SOBRECOMPRADO (RSI)", cls: "warn" });
    else if (rsi <= 30) tags.push({ label: "SOBREVENDIDO (RSI)", cls: "warn" });
  }
  if (vol !== null) {
    if (vol >= 45) tags.push({ label: "ALTA VOLATILIDAD", cls: "warn" });
    else if (vol <= 18) tags.push({ label: "BAJA VOLATILIDAD", cls: "pos" });
  }
  if (rsi !== null && trend.periodChangePct !== null) {
    if (rsi <= 30 && trend.periodChangePct < -10) tags.push({ label: "MERCADO CON MIEDO", cls: "neg" });
    else if (rsi >= 70 && trend.periodChangePct > 10) tags.push({ label: "MERCADO CON EUFORIA", cls: "warn" });
  }

  return {
    badge, noBadgeReason, gaugePct, tags, reasons, verdictExplanation,
    methodology: "Señal calculada por reglas fijas y deterministas (sin IA) a partir de: la "
      + "comparación de valoración/calidad vs. mediana del sector (igual que la sección "
      + "“Análisis”), la variación del precio en el período mostrado arriba, la "
      + "posición frente al máximo/mínimo de 52 semanas, el RSI(14) y la volatilidad realizada "
      + "de las propias velas diarias. Es una lectura mecánica de datos públicos, igual criterio "
      + "que el resto de este sitio — no es una recomendación personalizada ni predice el futuro.",
  };
}

// -- Moving averages ------------------------------------------------------------------------------

// Simple moving average of `values` over `period`, same length as the input: null until `period`
// values exist (never a partial-window average dressed up as a real one).
function sma(values, period) {
  const out = new Array(values.length).fill(null);
  if (period < 1) return out;
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

// Standard pairs per cadence: 50/200 sessions on daily, and the usual weekly/monthly
// equivalents (10/40) — a "200-week" line would need ~4 years of history before its first point.
const SMA_PERIODS = { d: [50, 200], w: [10, 40], m: [10, 40], y: [] };

// SMA lines aligned to the bars actually drawn. Computed over the FULL aggregated series first
// (so a daily SMA-200 is valid across the whole 130-session window, not null for its first 70
// bars), then cut down to the displayed tail.
function smaSeriesForView(rawBars, cadence) {
  const full = cadence === "d" ? rawBars : aggregatePriceBars(rawBars, cadence);
  const shown = aggregatePriceBars(rawBars, cadence);
  const offset = full.length - shown.length;
  const closes = full.map(b => b.close);
  return (SMA_PERIODS[cadence] || []).map(period => ({
    period,
    values: sma(closes, period).slice(offset),
  }));
}

// -- Tooltip formatting ---------------------------------------------------------------------------

const MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "septiembre", "octubre", "noviembre", "diciembre"];

// What one candle covers, in words: a day, "semana del ...", "agosto 2026", or a year.
function formatBarLabel(isoDate, cadence) {
  if (cadence === "y") return isoDate.slice(0, 4);
  if (cadence === "m") return `${MONTHS_ES[Number(isoDate.slice(5, 7)) - 1]} ${isoDate.slice(0, 4)}`;
  if (cadence === "w") return `semana del ${isoDate}`;
  return isoDate;
}

function formatVolume(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

// -- Search -----------------------------------------------------------------------------------

function normalizeText(s) {
  return String(s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

// Ranked: exact ticker, ticker prefix, ticker substring, then company-name match (accent- and
// case-insensitive, so "visa" finds V and "berkshire" finds BRK-B). `names` may be missing
// entries (or be absent entirely on an older index.json) — those tickers still match by symbol.
function searchTickers(query, tickers, names, limit = 12) {
  const q = query.trim();
  if (!q) return [];
  const qUp = q.toUpperCase();
  const qNorm = normalizeText(q);
  const nameOf = t => (names && names[t]) || "";
  const buckets = [[], [], [], []];
  for (const t of tickers) {
    if (t === qUp) buckets[0].push(t);
    else if (t.startsWith(qUp)) buckets[1].push(t);
    else if (t.includes(qUp)) buckets[2].push(t);
    else if (qNorm.length >= 2 && normalizeText(nameOf(t)).includes(qNorm)) buckets[3].push(t);
  }
  return buckets.flat().slice(0, limit).map(t => ({ ticker: t, name: nameOf(t) || null }));
}

// -- Deep links -------------------------------------------------------------------------------

// "#aapl", "#BRK-B", "#%20v" -> the matching ticker, or null if it's not one this site has.
function tickerFromHash(hash, available) {
  if (!hash) return null;
  let raw;
  try { raw = decodeURIComponent(hash.replace(/^#/, "")); } catch { return null; }
  const t = raw.trim().toUpperCase();
  return t && available.has(t) ? t : null;
}

// "#AAPL" -> { ticker: "AAPL", compare: null }; "#AAPL+MSFT" -> compare MSFT too. Anything not in
// `available` is dropped (a bad compare half doesn't invalidate the main ticker), and comparing a
// ticker with itself is treated as no comparison.
function parseRoute(hash, available) {
  const raw = (hash || "").replace(/^#/, "");
  const [main, other] = raw.split("+");
  const ticker = tickerFromHash(main, available);
  if (!ticker) return { ticker: null, compare: null };
  const compare = other ? tickerFromHash(other, available) : null;
  return { ticker, compare: compare && compare !== ticker ? compare : null };
}

function routeHash(ticker, compare) {
  return `#${ticker}${compare ? `+${compare}` : ""}`;
}

// Company names come from Finviz's page, and are inserted via innerHTML — escape them.
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// -- Data freshness -----------------------------------------------------------------------------

// The cron failed silently once before (httpx missing, 2026-08-20) and the site just kept showing
// old numbers. Say how old the data is, and flag it once it's past two days.
const STALE_AFTER_HOURS = 48;

function dataFreshness(generatedAtIso, nowMs) {
  const t = Date.parse(generatedAtIso);
  if (Number.isNaN(t)) return null;
  const hours = Math.max(0, (nowMs - t) / 3600000);
  let label;
  if (hours < 1) label = "hace menos de 1 h";
  else if (hours < 48) label = `hace ${Math.floor(hours)} h`;
  else label = `hace ${Math.floor(hours / 24)} días`;
  return { hours, label, stale: hours > STALE_AFTER_HOURS };
}

// -- Comparison ---------------------------------------------------------------------------------

// Two tickers' closes on their COMMON dates only (a date missing from either side is dropped, not
// interpolated), each rebased to 100 at the first common date, over the last `lookbackBars`
// common sessions. Returns null when there's not enough overlap to draw anything honest.
function rebasedComparison(barsA, barsB, lookbackBars) {
  if (!barsA || !barsB) return null;
  const closeB = new Map(barsB.map(b => [b.date, b.close]));
  let common = barsA.filter(b => closeB.has(b.date) && b.close && closeB.get(b.date));
  if (lookbackBars) common = common.slice(-lookbackBars);
  if (common.length < 2) return null;
  const baseA = common[0].close, baseB = closeB.get(common[0].date);
  return common.map(b => ({
    date: b.date,
    a: (b.close / baseA) * 100,
    b: (closeB.get(b.date) / baseB) * 100,
  }));
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    DAILY_VIEW_BARS, SMA_PERIODS, STALE_AFTER_HOURS,
    aggregatePriceBars, parseGridNumber, findColumnValue, computeAnnualizedVolatility,
    fundamentalsBreakdown, computeTrend, computeSentiment,
    sma, smaSeriesForView, formatBarLabel, formatVolume, normalizeText, searchTickers, tickerFromHash, parseRoute, routeHash,
    escapeHtml, dataFreshness, rebasedComparison,
  };
}
