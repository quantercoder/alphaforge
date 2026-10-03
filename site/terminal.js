"use strict";
// AlphaForge terminal: one script for both pages. window.PAGE = { kind: "equity" | "crypto", data: "<json>" }.

const PAGE = window.PAGE;
const CRYPTO = PAGE.kind === "crypto";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v, d = 2) => v == null ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pxd = (v) => v == null ? 2 : Math.abs(v) < 1 ? 5 : Math.abs(v) < 10 ? 4 : 2;
const price = (v, ref) => fmt(v, pxd(ref ?? v));  // ref: size decimals by the price level, not the change
const qty = (q) => q == null ? "–" : Number.isInteger(q) ? fmt(q, 0) : q.toLocaleString("en-US", { maximumFractionDigits: 6 });
const pct = (v, d = 2, sign = true) => v == null ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
const cls = (v) => v == null || v === 0 ? "" : v > 0 ? "up" : "dn";
const big = (v) => v == null ? "–" : v >= 1e9 ? (v / 1e9).toFixed(1) + "B" : v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? (v / 1e3).toFixed(0) + "K" : v.toFixed(0);
const money = (v, d = 0) => v == null ? "–" : (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const smoney = (v) => v == null ? "–" : (v > 0 ? "+" : "") + money(v);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const nyDate = () => new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
const utcDate = () => new Date().toISOString().slice(0, 10);
const et = (iso) => {
  if (!iso) return "–";
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(iso)).map((x) => [x.type, x.value]));
  return `${p.month}-${p.day} ${p.hour}:${p.minute}`;
};

let D = null, sym = null, range = 130, ptab = "growth", mtab = "all", gpChart, pChart, gpSeries, gpBars = [];
let rtab = "sum", btab = "pos", otab = "ord", stab = "scores", atab = "alerts";
const REPO = "https://github.com/z125081-Sam-Lam/alphaforge";
const FUNCS = {
  MON: ["mon", "Monitor: every ticker with price and change"], GP: ["gp", "Price chart of the selected ticker"],
  PORT: ["book", "Paper book: positions and live P&L"], BLTR: ["bltr", "Order blotter: orders, fills, slippage"],
  SIG: ["sig", "Signals: model scores and targets"], RISK: ["risk", "Risk: volatility, VaR, correlation"],
  BT: ["perf", "Backtest and benchmarks"], MTH: ["mth", "Monthly returns"],
  ATTR: ["perf", "P&L attribution: market, sector, style, stock, costs", () => { ptab = "attr"; renderPerf(); }],
  FACT: ["risk", "Factor risk model: market, sector, style vs specific risk", () => { rtab = "model"; renderRisk(); }],
  STRESS: ["risk", "Stress tests: historical crashes and factor shocks", () => { rtab = "stress"; renderRisk(); }],
  LIQ: ["risk", "Liquidity: days to exit each position", () => { rtab = "liq"; renderRisk(); }],
  LIM: ["risk", "Risk limits with traffic lights", () => { rtab = "lim"; renderRisk(); }],
  EXP: ["book", "Active weights, drift from target, sector exposure", () => { btab = "exp"; renderBook(); }],
  TCA: ["bltr", "Transaction cost analysis: decision vs fill, participation", () => { otab = "tca"; renderBltr(); }],
  IC: ["sig", "Signal diagnostics: IC and decay", () => { stab = "ic"; renderSig(); }],
  PREV: ["pre", "Next-trade preview and approval"], DATA: ["dh", "Data health checks"],
  AUD: ["aud", "Alerts, audit trail, controls and permissions"],
};
const EXTRA = {
  HELP: "List of commands", LIVE: "Connect real-time prices", "LIVE OFF": "Disconnect real-time prices",
  "LIVE LIST": "Live-tracked tickers",
  EQUITY: "Open the equities page", CRYPTO: "Open the crypto page",
};
const PAGES = { EQUITY: "index.html", EQ: "index.html", STOCKS: "index.html", CRYPTO: "crypto.html", CRY: "crypto.html" };
const FKEYS = [["F1", "HELP"], ["F2", "MON"], ["F3", "GP"], ["F4", "PORT"], ["F5", "BLTR"], ["F6", "SIG"], ["F7", "RISK"], ["F8", "BT"], ["F9", "PREV"]];
const SERIES = ["--amber", "--blue", "--aqua", "--violet"];
const GROUPS = { Market: "--blue", Sector: "--violet", Style: "--amber", Specific: "--aqua", Cash: "--dim", Costs: "--down" };
const OPEN_ST = ["new", "accepted", "pending_new", "partially_filled", "held", "submitted"];
const LIGHT = { green: "--up", amber: "--cmd", red: "--down", ok: "--up", warn: "--cmd", fail: "--down" };
const dot = (k, t) => `<i class="light" style="background:${css(LIGHT[k] || "--dim")}" title="${esc(t || k)}" role="img" aria-label="${esc(t || k)}"></i>`;
const bps = (v, d = 1) => v == null ? "–" : (v > 0 ? "+" : "") + v.toFixed(d) + "bp";
const lab = (s) => s.replace(/_/g, " ");
const days = (d) => d == null ? "–" : d < 0.01 ? "<0.01" : fmt(d, 2);
const fmtv = (v, f) => f === "usd" ? money(v) : f === "pct" ? pct(v, 1, false) : fmt(v);
const later = `<p class="empty">Appears after the next data refresh.</p>`;
const table = (head, rows) => `<table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
const ubar = (u, k) => `<div class="bar"><i style="left:0;width:${Math.min(100, Math.max(0, u) * 100)}%;background:${css(LIGHT[k] || "--amber")}"></i></div>`;
const kpiRow = (items, n = 4) => `<div class="kpis" style="grid-template-columns:repeat(${n},minmax(0,1fr))">${
  items.map(([a, b]) => `<div class="kpi"><div>${a}</div><div>${b}</div></div>`).join("")}</div>`;

function setTabs(id, items, cur, pick) {
  $(id).innerHTML = items.map(([k, l]) => `<button aria-pressed="${k === cur}" data-k="${k}">${l}</button>`).join("");
  $(id).querySelectorAll("button").forEach((b) => b.onclick = () => pick(b.dataset.k));
}

function nyseOpen() {
  const ny = new Date(new Date().toLocaleString("en-US", { timeZone: "America/New_York" }));
  const m = ny.getHours() * 60 + ny.getMinutes(), wd = ny.getDay();
  return wd > 0 && wd < 6 && m >= 570 && m < 960;
}

function chartOpts(el) {
  return { autoSize: true,  // follows its panel's size (ResizeObserver), so late layout or window changes can't squash it
    layout: { background: { color: css("--panel") }, textColor: css("--dim"), fontFamily: css("--f"), fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: "#15100b" }, horzLines: { color: "#15100b" } },
    rightPriceScale: { borderColor: css("--rule") }, timeScale: { borderColor: css("--rule") },
    crosshair: { mode: 0, vertLine: { color: "#6b5a33", labelBackgroundColor: "#4a3410" },
      horzLine: { color: "#6b5a33", labelBackgroundColor: "#4a3410" } } };
}

// ---------------------------------------------------------------- panels

function renderStrip() {
  $("strip").innerHTML = Object.entries(D.strip).map(([k, q]) => {
    if (!q) return "";
    const bp = k === "UST10Y";  // a yield: show the change in basis points
    const chg = bp ? `${q.chg >= 0 ? "+" : ""}${(q.chg * 100).toFixed(1)}bp` : `${price(q.chg, q.last)} ${pct(q.pct)}`;
    return `<div class="tile" data-k="${esc(k)}"><div class="n">${esc(k)}</div><div class="v lv">${bp ? q.last.toFixed(3) + "%" : price(q.last)}</div>
      <div class="c ${cls(q.chg)}">${chg}</div></div>`;
  }).join("");
}

function spark(arr) {
  if (!arr || arr.length < 2) return "";
  const lo = Math.min(...arr), hi = Math.max(...arr), w = 54, h = 14;
  const pts = arr.map((v, i) => `${(i / (arr.length - 1)) * w},${h - ((v - lo) / (hi - lo || 1)) * h}`).join(" ");
  const c = arr[arr.length - 1] >= arr[0] ? css("--up") : css("--down");
  return `<svg width="${w}" height="${h}" aria-hidden="true"><polyline fill="none" stroke="${c}" stroke-width="1.2" points="${pts}"/></svg>`;
}

const nm = (s) => (D.names[s] || [s])[0];

function renderMon() {
  const uni = new Set(D.universe), trk = new Set(LIVE.subs);
  $("mtabs").innerHTML = [["all", `All ${Object.keys(D.quotes).length}`], ["strat", "Strategy"], ["live", "Live"]].map(([k, l]) =>
    `<button aria-pressed="${k === mtab}" data-k="${k}">${l}</button>`).join("");
  $("mtabs").querySelectorAll("button").forEach((b) => b.onclick = () => { mtab = b.dataset.k; renderMon(); });
  $("livecount").textContent = `● ${LIVE.subs.length}/${MAX_SYMS} live`;
  const keep = mtab === "strat" ? (s) => uni.has(s) : mtab === "live" ? (s) => trk.has(s) : () => true;
  const rows = Object.entries(D.quotes).filter(([s, q]) => q && keep(s));
  if (mtab === "live") rows.sort((a, b) => LIVE.subs.indexOf(b[0]) - LIVE.subs.indexOf(a[0]));  // newest first
  else rows.sort((a, b) => b[1].pct - a[1].pct);
  $("monb").innerHTML = `<table><thead><tr><th>${CRYPTO ? "Coin" : "Ticker"}</th><th>Last</th><th>Chg%</th><th>YTD</th><th>30d</th></tr></thead><tbody>${
    rows.map(([s, q]) => `<tr class="click ${s === sym ? "on" : ""}" data-s="${esc(s)}" tabindex="0" title="${esc(nm(s))}">
      <td class="s">${esc(s)}${trk.has(s) ? '<span class="dot" title="Live tracked" aria-label="live tracked">●</span>' : ""}</td>
      <td class="lv">${price(q.last)}</td><td class="${cls(q.pct)}">${pct(q.pct)}</td>
      <td class="${cls(q.ytd)}">${pct(q.ytd, 1)}</td><td>${spark(q.spark)}</td></tr>`).join("")}</tbody></table>`;
  bindRows($("monb"));
}

function bindRows(root) {
  root.querySelectorAll("tr.click").forEach((tr) => {
    tr.onclick = () => loadSym(tr.dataset.s);
    tr.onkeydown = (e) => { if (e.key === "Enter") loadSym(tr.dataset.s); };
  });
}

function renderGP() {
  const q = D.quotes[sym], bars = (D.ohlc[sym] || []).slice(-range);
  if (!q) return;
  const s = D.signals.find((x) => x.sym === sym);
  const [name, sector] = D.names[sym] || [sym, ""];
  $("ghead").innerHTML = `<b class="sym">${esc(sym)}</b><span>${esc(name)}${sector && !CRYPTO ? " · " + esc(sector) : ""}</span>
    <b class="px lv" id="gpx">${price(q.last)}</b><b class="${cls(q.pct)}" id="gchg">${price(q.chg, q.last)} ${pct(q.pct)}</b>
    ${LIVE.subs.includes(sym) ? `<span class="trk">● live tracked</span>` : ""}
    <span>52w <b>${price(q.lo52)} – ${price(q.hi52)}</b></span><span>Avg vol <b>${big(q.vol20)}</b></span>
    ${s ? `<span>${CRYPTO ? "Trend" : "Alpha"} <b class="${cls(s.alpha)}">${fmt(s.alpha)}</b></span><span>Target <b>${pct(s.target, 1, false)}</b></span>` : ""}`;
  $("range").innerHTML = [[22, "1M"], [65, "3M"], [130, "6M"], [CRYPTO ? 365 : 260, "1Y"]].map(([n, l]) =>
    `<button aria-pressed="${n === range}" data-n="${n}">${l}</button>`).join("");
  $("range").querySelectorAll("button").forEach((b) => b.onclick = () => { range = +b.dataset.n; renderGP(); });
  const el = $("gpc");
  if (gpChart) gpChart.remove();
  gpChart = LightweightCharts.createChart(el, { ...chartOpts(el), localization: { priceFormatter: price } });
  const up = css("--up"), dn = css("--down");
  gpSeries = gpChart.addCandlestickSeries({ upColor: up, downColor: dn, wickUpColor: up, wickDownColor: dn, borderUpColor: up, borderDownColor: dn });
  gpBars = bars;
  gpSeries.setData(bars.map(([t, o, h, l, c]) => ({ time: t, open: o, high: h, low: l, close: c })));
  const v = gpChart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
  gpChart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  v.setData(bars.map(([t, o, , , c, vol]) => ({ time: t, value: vol, color: c >= o ? "#1d5c43" : "#5c2420" })));
  gpChart.timeScale().fitContent();
  if (LIVE.last[sym] != null) applyLive(sym, false);
}

function lineSeries(chart, color, title) {
  return chart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title });
}

function renderPerf() {
  const B = D.backtest, s = B.summary;
  $("ptabs").innerHTML = [["growth", "Growth"], ["dd", "Drawdown"], ["attr", "Attribution"], ["sleeve", "Paper vs backtest"], ["compare", "Compare"]].map(([k, l]) =>
    `<button aria-pressed="${k === ptab}" data-k="${k}">${l}</button>`).join("");
  $("ptabs").querySelectorAll("button").forEach((b) => b.onclick = () => { ptab = b.dataset.k; renderPerf(); });
  const el = $("pc"), names = Object.keys(B.lines);
  if (pChart) { pChart.remove(); pChart = null; }
  el.style.display = ptab === "compare" ? "none" : "";
  $("pcompare").innerHTML = "";
  const kp = (rows) => $("kpis").innerHTML = rows.map(([a, b]) => `<div class="kpi"><div>${a}</div><div>${b}</div></div>`).join("");
  const bench = names[1];
  if (ptab === "sleeve") return renderTracking(el, kp);
  if (ptab === "attr") return renderAttr(el, kp);
  kp([["CAGR", pct(s.CAGR, 1)], ["Sharpe", `${fmt(s.Sharpe)} <span class="mut">±${fmt(s["Sharpe SE"])}</span>`],
    ["Max DD", pct(s["Max Drawdown"], 1)], ["Vol", pct(s["Ann. Vol"], 1, false)], [`Beta (${bench.split(" ")[0]})`, fmt(s.Beta)],
    ["Alpha", pct(s["Alpha (ann.)"], 1)]]);
  $("plegend").innerHTML = names.map((n, i) => `<span><i style="background:${css(SERIES[i % 4])}"></i>${esc(n)}</span>`).join("") +
    `<span>since ${B.start}, weekly${ptab === "growth" ? ", log scale" : ""}</span>`;
  if (ptab === "compare") {
    const bn = (B.bench_name || "benchmark").split(" ")[0];
    $("pcompare").innerHTML = `<table><thead><tr><th>Series</th><th>CAGR</th><th>Vol</th><th>Sharpe</th><th>Max DD</th><th>Active vs ${esc(bn)}</th><th>TE</th><th>IR</th></tr></thead><tbody>${
      B.compare.map((r) => `<tr><td class="s">${esc(r.name)}</td><td class="${cls(r.CAGR)}">${pct(r.CAGR, 1)}</td><td>${pct(r["Ann. Vol"], 1, false)}</td>
      <td>${fmt(r.Sharpe)}</td><td class="dn">${pct(r["Max Drawdown"], 1)}</td><td class="${cls(r.active)}">${pct(r.active, 1)}</td>
      <td>${pct(r.te, 1, false)}</td><td class="${cls(r.ir)}">${fmt(r.ir)}</td></tr>`).join("")}</tbody></table>
      <p class="note">Active = annual return above ${esc(bn)}; TE (tracking error) = volatility of that difference; IR (information ratio) = active ÷ TE.</p>`;
    return;
  }
  pChart = LightweightCharts.createChart(el, chartOpts(el));
  if (ptab === "growth") {
    pChart.priceScale("right").applyOptions({ mode: 1 });
    names.slice().reverse().forEach((n) => {
      const i = names.indexOf(n);
      lineSeries(pChart, css(SERIES[i % 4]), n.split(" ")[0]).setData(B.dates.map((d, j) => ({ time: d, value: B.lines[n][j] })));
    });
  } else {
    names.slice().reverse().forEach((n) => {
      const i = names.indexOf(n), c = css(SERIES[i % 4]);
      const data = B.dates.map((d, j) => ({ time: d, value: B.drawdown[n][j] * 100 }));
      if (i === 0) pChart.addAreaSeries({ lineColor: c, topColor: "rgba(255,159,28,0)", bottomColor: "rgba(255,159,28,.35)", lineWidth: 2,
        invertFilledArea: true, priceFormat: { type: "custom", formatter: (v) => v.toFixed(1) + "%" } }).setData(data);
      else lineSeries(pChart, c, n.split(" ")[0]).setData(data);
    });
  }
  pChart.timeScale().fitContent();
}

function renderTracking(el, kp) {
  // Paper sleeve vs a shadow backtest started the same day: the test of whether the strategy survives live trading.
  const T = D.tracking, st = D.status, sl = D.slippage, need = 126;
  if (!T) { el.style.display = "none"; kp([["Sleeve NAV", money(st.nav)]]); $("plegend").innerHTML = "";
    $("pcompare").innerHTML = `<p class="empty">Tracking starts with the sleeve's first trading run.</p>`; return; }
  const gap = T.paper_ret - T.shadow_ret;
  kp([["Paper", `<span class="${cls(T.paper_ret)}">${pct(T.paper_ret)}</span>`], ["Backtest", `<span class="${cls(T.shadow_ret)}">${pct(T.shadow_ret)}</span>`],
    ["Gap", `<span class="${cls(gap)}">${pct(gap)}</span>`], ["Tracking error", T.te == null ? '<span class="mut">after 5 days</span>' : pct(T.te, 1, false)],
    ["Correlation", T.corr == null ? '<span class="mut">after 20 days</span>' : fmt(T.corr)], ["Days", T.n]]);
  $("plegend").innerHTML = `<span><i style="background:${css("--amber")}"></i>Paper sleeve</span><span><i style="background:${css("--blue")}"></i>Backtest, same start and settings</span><span>since ${T.start}, growth of 1</span>`;
  if (T.dates.length >= 2) {
    pChart = LightweightCharts.createChart(el, chartOpts(el));
    lineSeries(pChart, css("--blue"), "Backtest").setData(T.dates.map((d, i) => ({ time: d, value: T.shadow[i] })));
    lineSeries(pChart, css("--amber"), "Paper").setData(T.dates.map((d, i) => ({ time: d, value: T.paper[i] })));
    pChart.timeScale().fitContent();
  } else el.style.display = "none";
  const rule = (ok, txt, ev) => `<tr><td>${dot(ok == null ? "warn" : ok ? "ok" : "fail", ok == null ? "not enough data yet" : ok ? "pass" : "fail")}</td><td class="l">${txt}</td><td class="wrap mut">${ev}</td></tr>`;
  const assumed = st.cost_bps;
  $("pcompare").innerHTML = `<div class="sub">Pass/fail rule before any real money (LIVE_TRADING.md)</div>${table(["", "Rule", "Now"], [
    rule(T.n >= need ? true : null, `At least ${need} trading days (6 months)`, `${T.n} so far`),
    rule(T.corr == null || T.n < need ? null : T.corr >= 0.9, "Daily returns correlate with the backtest at 0.9 or more", T.corr == null ? "needs 20 days" : fmt(T.corr)),
    rule(sl.n ? sl.avg_bps <= assumed : null, `Average slippage within the ${assumed}bp the backtest assumes`, sl.n ? `${bps(sl.avg_bps)} over ${sl.n} fills` : "no fills measured"),
    rule(false, "Beats equal weight of the same names by more than luck (RESEARCH.md §7)", "failed the pre-registered test: no demonstrated edge"),
  ])}<p class="note">The backtest line runs the strategy's current settings from the paper book's first day, with the backtest's costs. The gap is fills, timing, rounding and cash; a growing gap means live trading doesn't reproduce the research.${CRYPTO ? "" : " The paper book still holds the old 4-factor portfolio until the next full rebalance, so expect a gap before then."}</p>`;
}

function renderAttr(el, kp) {
  const A = D.desk && D.desk.attribution;
  if (!A) { el.style.display = "none"; kp([]); $("plegend").innerHTML = ""; $("pcompare").innerHTML = later; return; }
  const G = Object.keys(GROUPS).filter((g) => !CRYPTO || !["Sector", "Style"].includes(g));
  kp([["Total", `<span class="${cls(A.total)}">${pct(A.total, 1)}</span>`], ...G.filter((g) => g !== "Cash").map((g) =>
    [g, `<span class="${cls(A.parts[g])}">${pct(A.parts[g], 1)}</span>`])]);
  $("plegend").innerHTML = G.map((g) => `<span><i style="background:${css(GROUPS[g])}"></i>${g}</span>`).join("") +
    `<span>backtest ${A.start} → ${A.end}, cumulative</span>`;
  pChart = LightweightCharts.createChart(el, chartOpts(el));
  G.forEach((g) => {
    const s = lineSeries(pChart, css(GROUPS[g]), g);
    s.applyOptions({ priceFormat: { type: "custom", formatter: (v) => v.toFixed(1) + "%" } });
    s.setData(A.dates.map((d, i) => ({ time: d, value: A.lines[g][i] * 100 })));
  });
  pChart.timeScale().fitContent();
  const mx = (o) => Math.max(0.005, ...Object.values(o).map(Math.abs));
  const names = Object.entries(A.names), top = Object.fromEntries([...names.slice(0, 5), ...names.slice(-5)]);
  $("pcompare").innerHTML = `${CRYPTO ? "" : `<div class="sub">By style factor</div>${hbars(A.styles, mx(A.styles), (v) => pct(v, 2))}
    <div class="sub">By sector</div>${hbars(A.sectors, mx(A.sectors), (v) => pct(v, 2))}`}
    <div class="sub">Best and worst ${CRYPTO ? "coins" : "stocks"}</div>${hbars(top, mx(top), (v) => pct(v, 2))}
    <p class="note">The strategy's return split by the ${CRYPTO ? "one-factor crypto" : "S&P 100 factor"} risk model: Market = the average ${CRYPTO ? "coin" : "stock"}${
      CRYPTO ? "" : ", Sector = sector moves against the market, Style = momentum, reversal, low-vol and trend tilts"}, Specific = ${CRYPTO ? "coin" : "stock"} picking left after the factors, Cash = T-bill interest, Costs = trading costs. The parts add up exactly to the total.</p>`;
}

function renderBook() {
  const pend = D.blotter.filter((o) => OPEN_ST.includes(o.status));
  setTabs("btabs", [["pos", "Positions"], ["exp", "Exposure"], ["pend", `Pending${pend.length ? " " + pend.length : ""}`]], btab,
    (k) => { btab = k; renderBook(); });
  bookPositions();
  if (btab === "exp") $("bookb").innerHTML = bookExposure();
  if (btab === "pend") $("bookb").innerHTML = bookPending(pend);
  bindRows($("bookb"));
}

function bookExposure() {
  const K = D.desk;
  if (!K) return later;
  const sec = {};
  K.exposure.forEach((r) => { const s = sec[r.sector] ||= { w: 0, target: 0, bench: 0 }; s.w += r.w; s.target += r.target; s.bench += r.bench; });
  const nameRows = K.exposure.map((r) => `<tr class="click" data-s="${esc(r.sym)}" title="${esc(nm(r.sym))}"><td class="s">${esc(r.sym)}</td>
    <td>${pct(r.w, 1, false)}</td><td class="mut">${pct(r.target, 1, false)}</td><td class="${cls(r.drift)}">${pct(r.drift, 2)}</td>
    <td class="mut">${pct(r.bench, 1, false)}</td><td class="${cls(r.active)}">${pct(r.active, 1)}</td></tr>`);
  return `${CRYPTO ? "" : `<div class="sub">Sectors vs benchmark</div>${table(["Sector", "Held", "Target", "Bench", "Active"],
    Object.entries(sec).sort((a, b) => (b[1].w - b[1].bench) - (a[1].w - a[1].bench)).map(([k, s]) => `<tr><td>${esc(k)}</td>
      <td>${pct(s.w, 1, false)}</td><td class="mut">${pct(s.target, 1, false)}</td><td class="mut">${pct(s.bench, 1, false)}</td>
      <td class="${cls(s.w - s.bench)}">${pct(s.w - s.bench, 1)}</td></tr>`))}`}
    <div class="sub">Names: held vs target vs benchmark</div>
    ${table([CRYPTO ? "Coin" : "Ticker", "Held", "Target", "Drift", "Bench", "Active"], nameRows)}
    <p class="note">Benchmark: ${esc(K.bench_label)}. Drift = held − the last rebalance's target (prices moved since). Active = held − benchmark.${
      CRYPTO ? "" : " Every holding is US-listed: country exposure is United States 100%."}</p>`;
}

function bookPending(pend) {
  const p = D.status.pending, aw = D.desk && D.desk.preview.awaiting;
  const head = (p ? `<p class="note">The ${esc(p)} signal fills at the next close.</p>` : "") +
    (aw ? `<p class="note dn">${esc(aw.kind)} waiting for approval since ${esc(aw.since)}: see Next trade.</p>` : "");
  if (!pend.length) return head + `<p class="empty">No open orders at the broker.</p>`;
  return head + table(["Time ET", "Side", CRYPTO ? "Coin" : "Ticker", "Qty", "Filled", "Status"], pend.map((o) =>
    `<tr class="click" data-s="${esc(o.symbol)}"><td class="mut">${et(o.time)}</td><td class="${o.qty > 0 ? "up" : "dn"}">${o.qty > 0 ? "BUY" : "SELL"}</td>
    <td class="s">${esc(o.symbol)}</td><td>${qty(Math.abs(o.qty))}</td><td>${qty(Math.abs(o.filled || 0))}</td><td class="mut">${esc(o.status.replace(/_/g, " "))}</td></tr>`));
}

function bookPositions() {
  const st = D.status, a = D.account, t = D.totals;
  const other = CRYPTO ? `<a href="index.html">Equities NAV <b>${money(a.equity_nav)}</b></a>`
    : a.crypto_enabled ? `<a href="crypto.html">Crypto NAV <b>${money(a.crypto_nav)}</b></a>` : `<span>Crypto held <b>${money(a.crypto_mv)}</b> (not managed)</span>`;
  $("acct").innerHTML = `<span>Account <b>${money(a.equity)}</b></span><span>${CRYPTO ? "Crypto" : "Equities"} NAV <b>${money(st.nav)}</b></span>
    ${other}<span>Rule <b>${esc(st.rule)}</b></span>`;
  const cash = st.nav - (t.mv || 0);
  $("bkpis").innerHTML = [["Invested", money(t.mv)], ["Cash", money(cash)],
    ["Unrealized", `<span class="${cls(t.upl)}">${smoney(t.upl)} <small>${pct(t.upl_pct)}</small></span>`],
    ["Today", `<span class="${cls(t.day_pl)}">${smoney(t.day_pl)}</span>`]].map(([x, y]) =>
    `<div class="kpi"><div>${x}</div><div>${y}</div></div>`).join("");
  const fn = D.book.some((p) => p.cost_source === "order history") ? "* average cost rebuilt from your order history (the broker reported none). " : "";
  const unk = t.unknown_cost ? `${t.unknown_cost} position(s) with no recorded cost are left out of unrealized P&L.` : "";
  if (!D.book.length) {
    const p = st.pending;
    $("bookb").innerHTML = `<p class="empty">No positions yet. ${p ? `The ${p} rebalance fills at the next close.`
      : D.blotter.some((o) => ["new", "accepted", "pending_new", "partially_filled"].includes(o.status)) ? "Orders are queued at the broker."
      : CRYPTO ? "The sleeve buys at its next weekly signal." : "The book opens at the next month-end signal."}</p>`;
    return;
  }
  $("bookb").innerHTML = `<table><thead><tr><th>${CRYPTO ? "Coin" : "Ticker"}</th><th>Qty</th><th>Avg</th><th>Last</th><th>Value</th><th>Wt</th><th>Today</th><th>Unrealized</th></tr></thead><tbody>${
    D.book.map((p) => `<tr class="click" data-s="${esc(p.sym)}" title="${esc(p.name)}"><td class="s">${esc(p.sym)}</td><td>${qty(p.qty)}</td>
      <td title="${p.cost_source === "broker" ? "" : "Average cost: " + esc(p.cost_source)}">${p.avg == null ? '<span class="mut">unknown</span>' : price(p.avg)}${p.cost_source === "order history" ? '<small class="mut">*</small>' : ""}</td><td class="lv" data-f="last">${price(p.last)}</td><td data-f="mv">${money(p.mv)}</td><td data-f="w">${pct(p.weight, 1, false)}</td>
      <td data-f="day" class="${cls(p.day_pl)}">${smoney(p.day_pl)} <small class="mut">${pct(p.day_pct, 1)}</small></td>
      <td data-f="upl" class="${cls(p.upl)}">${p.upl == null ? '<span class="mut">cost unknown</span>' : `${smoney(p.upl)} <small class="mut">${pct(p.upl_pct, 1)}</small>`}</td></tr>`).join("")}</tbody>
    <tfoot><tr><td>Total</td><td></td><td></td><td></td><td>${money(t.mv)}</td><td>${pct(t.weight, 1, false)}</td>
      <td class="${cls(t.day_pl)}">${smoney(t.day_pl)}</td><td class="${cls(t.upl)}">${smoney(t.upl)} <small class="mut">${pct(t.upl_pct, 1)}</small></td></tr></tfoot></table>
    ${fn || unk ? `<p class="note">${fn}${unk}</p>` : ""}`;
  bindRows($("bookb"));
}

function bookLive(s, p) {
  // Recompute one position's P&L from a live price, the way Alpaca does: unrealized vs cost, today vs last close.
  const r = D.book.find((x) => x.sym === s);
  if (!r) return false;
  r.last = p; r.mv = r.qty * p;
  if (r.cost != null) { r.upl = r.mv - r.cost; r.upl_pct = r.cost ? r.upl / Math.abs(r.cost) : null; }
  if (r.lastday) { r.day_pl = (p - r.lastday) * r.qty; r.day_pct = p / r.lastday - 1; }
  r.weight = D.status.nav ? r.mv / D.status.nav : null;
  const t = D.totals;
  ["mv", "day_pl"].forEach((k) => t[k] = D.book.reduce((a, x) => a + (x[k] || 0), 0));
  const known = D.book.filter((x) => x.upl != null);
  t.cost = known.reduce((a, x) => a + x.cost, 0); t.upl = known.reduce((a, x) => a + x.upl, 0);
  t.upl_pct = t.cost ? t.upl / Math.abs(t.cost) : null; t.weight = D.status.nav ? t.mv / D.status.nav : null;
  return true;
}

function renderBltr() {
  setTabs("otabs", [["ord", "Orders"], ["tca", "TCA"]], otab, (k) => { otab = k; renderBltr(); });
  bltrOrders();
  if (otab === "tca") $("bltrb").innerHTML = bltrTCA();
}

function bltrTCA() {
  const K = D.desk;
  if (!K) return later;
  const S = K.tca, rows = K.tca_rows.filter((r) => r.filled);
  const na = CRYPTO ? '<span class="mut">n/a</span>' : null;
  return `${kpiRow([["Fill rate", pct(S.fill_rate, 1, false)], ["Avg slippage", bps(S.slip_bps)], ["Delay", na || bps(S.delay_bps)],
      ["Impact", na || bps(S.impact_bps)], ["Shortfall", `<span class="${S.shortfall > 0 ? "dn" : S.shortfall < 0 ? "up" : ""}">${money(S.shortfall)}</span>`],
      ["Traded", money(S.notional)], ["Max % of volume", S.max_participation == null ? "–" : pct(S.max_participation, 4, false)], ["Assumed cost", S.assumed_bps + "bp"]])}
    ${rows.length ? table(["Time ET", "Side", CRYPTO ? "Coin" : "Ticker", "Decision", ...(CRYPTO ? [] : ["Arrival"]), "Fill", ...(CRYPTO ? [] : ["Delay", "Impact"]), "Total", "% vol"],
      rows.map((r) => `<tr class="click" data-s="${esc(r.symbol)}"><td class="mut">${et(r.time)}</td><td class="${r.side > 0 ? "up" : "dn"}">${r.side > 0 ? "BUY" : "SELL"}</td>
        <td class="s">${esc(r.symbol)}</td><td>${price(r.decision)}</td>${CRYPTO ? "" : `<td>${price(r.arrival)}</td>`}<td>${price(r.fill)}</td>
        ${CRYPTO ? "" : `<td class="${cls(-(r.delay_bps || 0))}">${bps(r.delay_bps)}</td><td class="${cls(-(r.impact_bps || 0))}">${bps(r.impact_bps)}</td>`}
        <td class="${cls(-(r.slip_bps || 0))}">${bps(r.slip_bps)}</td><td class="mut">${r.participation == null ? "–" : pct(r.participation, 4, false)}</td></tr>`))
      : `<p class="empty">No fills yet.</p>`}
    <p class="note">Decision = the close when the signal was made. ${CRYPTO ? "" : "Arrival = the open of the fill day (orders go in before the open). Delay = the overnight move from decision to arrival; impact = fill vs arrival. "}Positive bp = cost. Shortfall = what slippage cost in dollars. % vol = shares filled ÷ that day's volume.</p>`;
}

function bltrOrders() {
  const sl = D.slippage, cost = D.status.cost_bps;
  $("slip").textContent = sl.n ? `avg slippage ${sl.avg_bps >= 0 ? "+" : ""}${sl.avg_bps.toFixed(1)}bp vs ${cost}bp assumed (${sl.n} fills)` : "times in New York";
  $("bltrb").innerHTML = D.blotter.length ? `<table><thead><tr><th>Time ET</th><th>Side</th><th>${CRYPTO ? "Coin" : "Ticker"}</th><th>Filled</th><th>Avg</th><th>Value</th><th>Slip</th><th>Status</th></tr></thead><tbody>${
    D.blotter.map((o) => {
      const f = o.filled ?? 0, side = o.qty > 0 ? "BUY" : "SELL";
      return `<tr><td class="mut">${et(o.time)}</td><td class="${o.qty > 0 ? "up" : "dn"}">${side}</td>
      <td class="s">${esc(o.symbol)}${o.auto ? "" : ' <small class="mut" title="Placed by hand, not by the strategy">manual</small>'}</td>
      <td>${qty(Math.abs(f))}<span class="mut">/${qty(Math.abs(o.qty))}</span></td><td>${price(o.price)}</td>
      <td>${o.price ? money(Math.abs(f) * o.price) : "–"}</td>
      <td class="${o.slip_bps == null ? "mut" : o.slip_bps > 0 ? "dn" : "up"}">${o.slip_bps == null ? "–" : o.slip_bps.toFixed(1) + "bp"}</td>
      <td class="mut">${esc(o.status.replace(/_/g, " "))}</td></tr>`;
    }).join("")}</tbody></table>`
    : `<p class="empty">No orders yet. Fills appear here after each rebalance.</p>`;
}

function renderSig() {
  setTabs("stabs", CRYPTO ? [["scores", "Scores"], ["ic", "IC & decay"], ["cap", "Capacity"]]
    : [["scores", "Scores"], ["ic", "IC & decay"], ["corr", "Correlation"], ["cap", "Crowding & capacity"]], stab, (k) => { stab = k; renderSig(); });
  if (stab === "scores") return sigScores();
  const S = D.desk && D.desk.signals;
  $("sigb").innerHTML = !S ? later : stab === "ic" ? sigIC(S) : stab === "corr" ? sigCorr(S) : sigCap(S);
}

function sigIC(S) {
  const H = S.horizons.map(String);
  const rows = Object.entries(S.ic).map(([n, x]) => `<tr><td class="s">${esc(lab(n))}</td>${H.map((h) => {
    const c = x[h] || {};
    return `<td class="${cls(c.ic)}" title="t = ${c.t == null ? "–" : fmt(c.t, 1)}, n = ${c.n}">${c.ic == null ? "–" : fmt(c.ic, 3)}${c.t != null && Math.abs(c.t) >= 2 ? "*" : ""}</td>`;
  }).join("")}${CRYPTO ? "" : `<td>${x[H[2]] && x[H[2]].hit != null ? pct(x[H[2]].hit, 0, false) : "–"}</td>`}</tr>`);
  return table(["Signal", ...H.map((h) => `IC ${h}d`), ...(CRYPTO ? [] : [`Hit ${H[2]}d`])], rows) +
    `<p class="note">Rank IC = correlation between a signal today and the next N days' returns, ${CRYPTO ? "pooled across coins and month-ends" : "across the " + D.universe.length + " names at each month-end"} since the data starts. Read across a row for decay: a real signal stays positive as N grows. * = |t| ≥ 2. ${CRYPTO ? "" : "Hit = share of months with a positive IC."}</p>`;
}

function sigCorr(S) {
  const C = S.corr;
  if (!C || !C.corr) return later;
  return table(["", ...C.names.map((n) => esc(lab(n)))], C.corr.map((row, i) => `<tr><td class="s">${esc(lab(C.names[i]))}</td>${
    row.map((v) => `<td style="background:${corrColor(v)};color:#000">${fmt(v)}</td>`).join("")}</tr>`)) +
    `<p class="note">Average rank correlation between signals at month-ends over 3 years. High correlation means two signals bet on the same thing.</p>`;
}

function sigCap(S) {
  const C = S.crowding || {}, P = S.capacity || {};
  const crowd = Object.keys(C).length ? `<div class="sub">Crowding (co-movement of the top third)</div>${table(["Signal", "Now", "Median 3y", "Percentile"],
    Object.entries(C).map(([n, c]) => `<tr><td class="s">${esc(lab(n))}</td><td>${fmt(c.now, 3)}</td><td class="mut">${fmt(c.median, 3)}</td>
      <td>${dot(c.pct >= 0.9 ? "red" : c.pct >= 0.7 ? "amber" : "green")} ${pct(c.pct, 0, false)}</td></tr>`))}
    <p class="note">Average pairwise correlation of the top-ranked names' market-adjusted returns over 63 days (Lou &amp; Polk's comomentum). When many funds hold the same names they move together; a high percentile warns of a crowded trade that can unwind fast.</p>` : "";
  return crowd + `<div class="sub">Capacity</div>${table(["Portfolio", "Capacity", "Binding name", "Turnover / rebalance"],
    Object.entries(P).map(([n, c]) => `<tr class="click" data-s="${esc(c.binding)}"><td class="s">${esc(lab(n))}</td><td>$${big(c.aum)}</td><td>${esc(c.binding)}</td><td>${pct(c.turnover, 0, false)}</td></tr>`))}
    <p class="note">Fund size at which an average rebalance trade in any name is still under 10% of its daily dollar volume. Above it, the trades start moving prices against you.</p>`;
}

function sigScores() {
  if (CRYPTO) {
    $("sigb").innerHTML = `<table><thead><tr><th>Coin</th><th>Trend</th><th>20d</th><th>60d</th><th>120d</th><th>Vol</th><th>Target</th></tr></thead><tbody>${
      D.signals.map((s) => `<tr class="click" data-s="${esc(s.sym)}"><td class="s">${esc(s.sym)}</td><td class="${cls(s.alpha)}"><b>${fmt(s.alpha)}</b></td>
        ${["r20", "r60", "r120"].map((k) => `<td class="${cls(s[k])}">${pct(s[k], 1)}</td>`).join("")}
        <td>${pct(s.vol, 0, false)}</td><td>${s.target ? pct(s.target, 1, false) : '<span class="mut">cash</span>'}</td></tr>`).join("")}</tbody></table>
      <p class="note">Trend = average sign of the 20, 60 and 120-day returns. Only coins with a positive trend are held, sized by inverse volatility.</p>`;
  } else {
    const f = ["momentum", "reversal", "low_vol", "quality_trend"], lab = ["Mom", "Rev", "LoVol", "Trend"];
    $("sigb").innerHTML = `<table><thead><tr><th>Ticker</th><th>Alpha</th>${lab.map((l) => `<th>${l}</th>`).join("")}<th>Target</th></tr></thead><tbody>${
      D.signals.map((s) => `<tr class="click" data-s="${esc(s.sym)}" title="${esc(nm(s.sym))} · ${esc(s.sector)}"><td class="s">${esc(s.sym)}</td><td class="${cls(s.alpha)}"><b>${fmt(s.alpha)}</b></td>
        ${f.map((k) => `<td class="${cls(s[k])}">${fmt(s[k])}</td>`).join("")}<td>${s.target ? pct(s.target, 1, false) : '<span class="mut">–</span>'}</td></tr>`).join("")}</tbody></table>`;
  }
  bindRows($("sigb"));
}

function hbars(obj, max, fmtv) {
  return `<table><tbody>${Object.entries(obj).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td class="${cls(v)}">${fmtv(v)}</td>
    <td style="width:45%"><div class="bar"><i style="left:${v < 0 ? 50 + (v / max) * 50 : 50}%;width:${Math.min(50, Math.abs(v / max) * 50)}%;background:${v < 0 ? css("--down") : css("--up")}"></i></div></td></tr>`).join("")}</tbody></table>`;
}

function corrColor(v) {
  const a = Math.min(1, Math.abs(v));
  return v >= 0 ? `rgba(255,159,28,${0.06 + 0.85 * a})` : `rgba(74,158,255,${0.06 + 0.85 * a})`;
}

function renderRisk() {
  const K = D.desk, bad = K ? K.limits.filter((x) => x.light !== "green").length : 0;
  setTabs("rtabs", [["sum", "Summary"], ["model", "Factor model"], ["stress", "Stress"], ["liq", "Liquidity"],
    ["lim", `Limits${bad ? ` <b class="${K.limits.some((x) => x.light === "red") ? "dn" : ""}">${bad}</b>` : ""}`]], rtab, (k) => { rtab = k; renderRisk(); });
  $("risklabel").textContent = CRYPTO ? "Crypto sleeve" : "Equities sleeve";
  $("riskb").innerHTML = rtab === "sum" ? riskSummary() : !K ? later
    : rtab === "model" ? riskModel(K) : rtab === "stress" ? riskStress(K) : rtab === "liq" ? riskLiq(K) : riskLimits(K);
  bindRows($("riskb"));
}

function riskModel(K) {
  const M = K.model, T = M && M.total, A = M && M.active;
  if (!T) return `<p class="empty">No positions to decompose yet.</p>`;
  const G = CRYPTO ? ["Market", "Specific"] : ["Market", "Sector", "Style", "Specific"];
  const share = (o, k) => o ? pct(o.groups[k], 0, false) : "–";
  const nsec = M.names.length - 1 - Object.keys(T.styles).length;
  return `<div class="rgrid">
    <div><span>Total risk</span>${pct(T.vol, 1, false)}</div><div><span>Active risk vs ${esc(K.bench_label)}</span>${A ? pct(A.vol, 1, false) : "–"}</div>
    <div><span>Factor risk</span>${pct(T.factor_vol, 1, false)}</div><div><span>Specific risk</span>${pct(T.specific_vol, 1, false)}</div></div>
    <div class="sub">Where the risk comes from (share of variance)</div>
    ${table(["Source", "Total", "Active", ""], G.map((k) => `<tr><td><i class="light" style="background:${css(GROUPS[k])}"></i> ${k}</td>
      <td>${share(T, k)}</td><td class="mut">${share(A, k)}</td><td style="width:40%">${ubar(T.groups[k])}</td></tr>`))}
    ${CRYPTO ? "" : `<div class="sub">Style factors</div>${table(["Factor", "Exposure (z)", "Factor vol", "Share of risk"],
      Object.keys(T.styles).map((f) => `<tr><td>${esc(lab(f))}</td><td class="${cls(T.exposure[f])}">${fmt(T.exposure[f])}</td>
        <td class="mut">${pct(M.factor_vol[f], 1, false)}</td><td class="${cls(T.styles[f])}">${pct(T.styles[f], 1)}</td></tr>`))}
      <div class="sub">Sector risk (share of variance)</div>${hbars(T.sectors, Math.max(0.05, ...Object.values(T.sectors).map(Math.abs)), (v) => pct(v, 1))}`}
    <div class="sub">Each position's share of risk</div>
    ${table([CRYPTO ? "Coin" : "Ticker", "Weight", "Share of risk", "of which specific"], Object.entries(T.names).map(([s, n]) =>
      `<tr class="click" data-s="${esc(s)}"><td class="s">${esc(s)}</td><td>${pct(n.w, 1, false)}</td><td>${pct(n.share, 1, false)}</td><td class="mut">${pct(n.specific, 1, false)}</td></tr>`))}
    <p class="note">${CRYPTO ? `One-factor model on ${M.n} coins: the crypto market (average coin) plus coin-specific risk`
      : `Cross-sectional model on ${M.n} S&amp;P 100 stocks: market + ${nsec} sectors + ${Object.keys(T.styles).length} styles + stock-specific`}, a year of daily returns, 90-day half-life. Shares add up to 100% of the forecast variance.</p>`;
}

function riskStress(K) {
  const S = K.stress, r = D.risk, star = (x) => x.proxied.length ? ` <small class="mut" title="No price history then, moved with beta: ${esc(x.proxied.join(", "))}">*</small>` : "";
  return `<div class="sub">Historical replay on today's weights</div>
    ${table(["Scenario", "Window", CRYPTO ? "BTC" : "S&P 500", "Book", "P&L"], S.history.map((x) => `<tr><td>${esc(x.label)}${star(x)}</td>
      <td class="mut">${x.start} → ${x.end}</td><td class="${cls(x.bench)}">${pct(x.bench, 1)}</td><td class="${cls(x.ret)}">${pct(x.ret, 1)}</td><td class="${cls(x.pnl)}">${smoney(x.pnl)}</td></tr>`))}
    ${S.factor.length ? `<div class="sub">Factor shocks (risk model)</div>${table(["Shock", "Book", "P&L"], S.factor.map((x) =>
      `<tr><td>${esc(x.label)}</td><td class="${cls(x.ret)}">${pct(x.ret, 1)}</td><td class="${cls(x.pnl)}">${smoney(x.pnl)}</td></tr>`))}` : ""}
    <div class="sub">Parametric</div>${table(["Shock", "P&L"], [`<tr><td>${esc(r.stress.label)} × beta ${fmt(r.beta)}</td><td class="${cls(r.stress.pnl)}">${smoney(r.stress.pnl)}</td></tr>`])}
    <p class="note">Each name's actual move over the window, applied to today's weights; a name with no price history then (*) moves with beta × the benchmark. Factor shocks move one style factor 3 standard deviations over a month, in the direction that hurts the book.</p>`;
}

function riskLiq(K) {
  const L = K.liquidity;
  return `<div class="rgrid"><div><span>Slowest exit</span>${days(L.max_days)} days</div><div><span>Sellable in 1 day</span>${pct(L.one_day, 0, false)}</div></div>
    ${table([CRYPTO ? "Coin" : "Ticker", "Value", "ADV $", "% of ADV", "Days to exit"], L.rows.map((x) => `<tr class="click" data-s="${esc(x.sym)}"><td class="s">${esc(x.sym)}</td>
      <td>${money(x.mv)}</td><td>$${big(x.adv)}</td><td>${pct(x.pct_adv, 4, false)}</td><td>${days(x.days)}</td></tr>`))}
    <p class="note">Days to exit = position ÷ (${pct(L.participation, 0, false)} of 20-day average dollar volume), selling no more than a tenth of a normal day's trading.</p>`;
}

function riskLimits(K) {
  return table(["", "Limit", "Type", "Now", "Max", "Used", ""], K.limits.map((x) => `<tr><td>${dot(x.light)}</td><td class="l">${esc(x.name)}</td>
    <td class="mut">${x.kind}</td><td>${fmtv(x.value, x.fmt)}</td><td class="mut">${fmtv(x.limit, x.fmt)}</td><td>${pct(x.util, 0, false)}</td><td style="width:20%">${ubar(x.util, x.light)}</td></tr>`)) +
    `<p class="note">Green under 90% of the limit, amber 90–100%, red at or over (also listed under Alerts). Hard limits are enforced by the trading job (order caps, position caps, drawdown halt); soft limits are monitored here. Change them under "limits" in live.json.</p>`;
}

function riskSummary() {
  const r = D.risk, st = D.status, a = D.account, nav = st.nav;
  const share = (v) => a.equity ? pct(v / a.equity, 0, false) : "–";
  const used = st.halt_at ? Math.min(1, Math.max(0, st.drawdown / st.halt_at)) : 0;
  const n = r.corr_syms.length;
  return `
    <div class="acct"><span>Account <b>${money(a.equity)}</b></span><span>Equities <b>${money(a.equity_nav)}</b> ${share(a.equity_nav)}</span>
      <span>Crypto <b>${money(a.crypto_enabled ? a.crypto_nav : a.crypto_mv)}</b> ${share(a.crypto_enabled ? a.crypto_nav : a.crypto_mv)}</span></div>
    <div class="rgrid">
      <div><span>Forecast vol</span>${pct(r.ex_ante_vol, 1, false)}</div><div><span>Realized vol</span>${pct(r.realized_vol, 1, false)}</div>
      <div><span>1d VaR 95% (normal)</span>${money(r.var95)}</div><div><span>1d VaR 95% (history)</span>${money(r.hvar95)}</div>
      <div><span>Beta</span>${fmt(r.beta)}</div><div><span>${esc(r.stress.label)}</span><b class="${cls(r.stress.pnl)}">${smoney(r.stress.pnl)}</b></div>
      <div><span>Gross</span>${pct(r.gross, 0, false)}</div><div><span>Net</span>${pct(r.net, 0, false)}</div>
    </div>
    <div class="halt"><span class="mut">Drawdown ${pct(st.drawdown, 1)} of the ${pct(st.halt_at, 0)} halt</span>
      <div class="bar" title="${pct(used, 0, false)} of the way to the halt"><i style="left:0;width:${used * 100}%;background:${used > 0.66 ? css("--down") : used > 0.33 ? css("--cmd") : css("--up")}"></i></div></div>
    ${r.sectors ? `<div class="sub">Sector exposure</div>${hbars(r.sectors, Math.max(0.3, ...Object.values(r.sectors).map(Math.abs)), (v) => pct(v, 0, false))}` : ""}
    ${r.exposures ? `<div class="sub">Factor exposure (Σ w·z)</div>${hbars(r.exposures, Math.max(0.5, ...Object.values(r.exposures).map(Math.abs)), (v) => fmt(v))}` : ""}
    ${Object.keys(r.contrib).length ? `<div class="sub">Share of sleeve risk</div>${hbars(Object.fromEntries(Object.entries(r.contrib).slice(0, 8)), Math.max(0.2, ...Object.values(r.contrib)), (v) => pct(v, 0, false))}` : ""}
    <div class="sub">Correlation, last ${CRYPTO ? 60 : 63} days${CRYPTO ? "" : ", grouped by sector"}</div>
    <div class="legend"><span><i style="background:rgba(74,158,255,.9)"></i>−1</span><span><i style="background:rgba(255,159,28,.9)"></i>+1</span><span>hover a cell</span></div>
    <div class="corr" style="grid-template-columns:${CRYPTO ? 44 : 38}px repeat(${n},1fr)"><span></span>${
      r.corr_syms.map((s) => `<span class="cl">${esc(s.split("/")[0])}</span>`).join("")}${
      r.corr.map((row, i) => `<span class="rl">${esc(r.corr_syms[i].split("/")[0])}</span>` + row.map((v, j) =>
        `<i style="background:${corrColor(v)}" title="${esc(r.corr_syms[i])} / ${esc(r.corr_syms[j])}: ${fmt(v)}"></i>`).join("")).join("")}</div>`;
}

function renderMth() {
  const m = D.backtest.monthly;
  const shade = (v) => v == null ? "transparent" : v >= 0 ? `rgba(46,229,157,${Math.min(0.75, v * (CRYPTO ? 3 : 8))})` : `rgba(255,90,79,${Math.min(0.75, -v * (CRYPTO ? 3 : 8))})`;
  $("mthb").innerHTML = `<table class="mth"><thead><tr><th>Year</th>${m.cols.map((c) => `<th>${c === "Year" ? "FY" : c}</th>`).join("")}</tr></thead><tbody>${
    m.years.map((y, i) => `<tr><td class="s">${y}</td>${m.values[i].map((v, j) =>
      `<td style="background:${m.cols[j] === "Year" ? "transparent" : shade(v)}" class="${m.cols[j] === "Year" ? cls(v) : ""}">${v == null ? "" : (v * 100).toFixed(1)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function renderPre() {
  const K = D.desk;
  if (!K) { $("preb").innerHTML = later; return; }
  const P = K.preview, R = P.rebalance, n = P.next, S = P.swap;
  $("prelabel").textContent = P.require_approval ? "approval required" : "automatic";
  const orders = (o) => o.length ? table(["Side", CRYPTO ? "Coin" : "Ticker", "Qty", "Price", "Notional", ""], o.map((x) =>
    `<tr class="click" data-s="${esc(x.sym)}"><td class="${x.qty > 0 ? "up" : "dn"}">${x.qty > 0 ? "BUY" : "SELL"}</td><td class="s">${esc(x.sym)}</td>
    <td>${qty(Math.abs(x.qty))}</td><td>${price(x.px)}</td><td>${money(Math.abs(x.notional))}</td>
    <td>${x.capped ? '<small class="dn" title="Cut to the maximum order size">capped</small>' : ""}</td></tr>`))
    : `<p class="empty">No trades: the book already matches the target.</p>`;
  const sum = (x) => kpiRow([["Buys", money(x.buys)], ["Sells", money(x.sells)], ["Turnover", pct(x.turnover, 1, false)], ["Est. cost", money(x.cost)],
    ["Gross after", pct(x.post_gross, 0, false)], ["Max weight", pct(x.post_max, 1, false)],
    [CRYPTO ? "Cash after" : "Max sector", CRYPTO ? pct(1 - x.post_gross, 0, false) : pct(x.post_max_sector, 0, false)], ["Names after", x.post_names]]);
  const appr = P.require_approval
    ? `<div class="appr">${P.awaiting ? `<b class="dn">${esc(P.awaiting.kind)} waiting since ${esc(P.awaiting.since)}</b>` : "<span>Each rebalance and swap waits for approval.</span>"}
       <a class="go" href="${esc(P.approve_url)}" target="_blank" rel="noopener">Approve in GitHub</a>
       <small class="mut">Run workflow → approve: ${CRYPTO ? "crypto" : "equity"}</small></div>`
    : `<p class="note">Approval is off, so trades go through automatically. Set <code>"require_approval": true</code> in live.json${CRYPTO ? ' under "crypto"' : ""} to make each rebalance wait for your OK.</p>`;
  $("preb").innerHTML = `<div class="acct"><span>Next rebalance <b>${esc(n.rebalance || "–")}</b></span>${n.swap ? `<span>Next swap check <b>${esc(n.swap)}</b></span>` : ""}
      <span>Max order <b>${money(P.max_order)}</b></span><span>Min trade <b>${money(P.min_trade)}</b></span></div>
    ${appr}
    <div class="sub">Rebalance, if it ran on today's prices</div>${sum(R)}${orders(R.orders)}
    ${S ? `<div class="sub">Swap check: ${S.drop.length ? `drop ${S.drop.map((s) => `${esc(s)} <span class="dn">${pct(S.pnl[s], 1)}</span>`).join(", ")} → add ${S.add.map(esc).join(", ")}`
      : "nothing would be swapped"}</div>${S.drop.length ? orders(S.orders) : ""}` : ""}
    <p class="note">Built with the trading job's own sizing (targets, caps, minimum trade, max order) on today's prices; the real run uses that day's close.</p>`;
  bindRows($("preb"));
}

function renderDH() {
  const K = D.desk;
  const age = LIVE.lastTick ? (Date.now() - LIVE.lastTick) / 1000 : null;
  const closed = !CRYPTO && !nyseOpen();
  const feed = LIVE.status !== "on" ? ["warn", LIVE.status === "off" ? "not connected: prices are delayed" : LIVE.status]
    : age == null ? [closed ? "ok" : "warn", `${FEED.name} connected, no ticks yet${closed ? " (market closed)" : ""}`]
    : [age < 60 || closed ? "ok" : "warn", `${FEED.name}: last tick ${age < 1 ? "<1" : Math.round(age)}s ago, ${LIVE.subs.length} symbols`];
  const gen = (Date.now() - new Date(D.generated_at)) / 60000;
  const built = [gen < 45 || (!nyseOpen() && gen < 72 * 60) ? "ok" : gen < 24 * 60 ? "warn" : "fail", `built ${Math.round(gen)} min ago (${et(D.generated_at)} ET)`];
  const all = [[built[0], "Terminal data", built[1]], [feed[0], "Live feed", feed[1]], ...(K ? K.health.map((h) => [h.status, h.check, h.detail]) : [])];
  const bad = all.filter((x) => x[0] !== "ok").length;
  $("dhlabel").innerHTML = bad ? `<span class="dn">${bad} to check</span>` : `<span class="up">all clear</span>`;
  $("dhb").innerHTML = table(["", "Check", "Detail"], all.map(([s, c, d]) =>
    `<tr><td>${dot(s)}</td><td class="l">${esc(c)}</td><td class="mut wrap">${esc(d)}</td></tr>`));
}

function renderAud() {
  const K = D.desk;
  if (!K) { $("audb").innerHTML = later; return; }
  const C = K.controls, now = K.alerts_now;
  setTabs("atabs", [["alerts", `Alerts${now.length ? ` <b class="dn">${now.length}</b>` : ""}`], ["audit", "Audit trail"], ["ctl", "Controls"]], atab,
    (k) => { atab = k; renderAud(); });
  if (atab === "alerts") {
    $("audb").innerHTML = `<div class="sub">Now</div>${now.length ? table(["", "Alert"], now.map((a) => `<tr><td>${dot("red")}</td><td class="wrap">${esc(a)}</td></tr>`))
      : `<p class="empty">No limit breached, no failing data check.</p>`}
      <div class="sub">From trading runs</div>${C.alerts.length ? table(["Time ET", "Alert"], C.alerts.map((a) => `<tr><td class="mut">${et(a.time)}</td><td class="wrap">${esc(a.alert)}</td></tr>`))
      : `<p class="empty">None recorded.</p>`}
      <p class="note">A trading run that raises an alert also fails its GitHub job, and GitHub emails you.</p>`;
  } else if (atab === "audit") {
    $("audb").innerHTML = C.audit.length ? table(["Time ET", "By", "How", "Orders", "What happened"], C.audit.map((a) => `<tr>
      <td class="mut">${et(a.time)}</td><td>${esc(a.actor)}</td><td class="mut">${a.run ? `<a href="${REPO}/actions/runs/${esc(a.run)}" target="_blank" rel="noopener">${esc(a.trigger)}</a>` : esc(a.trigger)}${
        a.sha ? ` <a href="${REPO}/commit/${esc(a.sha)}" target="_blank" rel="noopener">${esc(a.sha)}</a>` : ""}</td><td>${a.orders}</td>
      <td class="wrap">${esc((a.events || []).join("; ") || "no action")}${a.alerts && a.alerts.length ? ` <span class="dn">${esc(a.alerts.join("; "))}</span>` : ""}</td></tr>`))
      : `<p class="empty">The audit trail starts with the next trading run.</p>`;
  } else {
    $("audb").innerHTML = `<div class="sub">Controls</div>${table(["", "Control", "State"], C.controls.map(([n, v, s]) =>
      `<tr><td>${dot(s)}</td><td class="l">${esc(n)}</td><td class="wrap">${esc(v)}</td></tr>`))}
      <div class="sub">Who can do what</div>${table(["Action", "Who"], C.permissions.map(([a, w]) => `<tr><td class="l">${esc(a)}</td><td class="wrap mut">${esc(w)}</td></tr>`))}`;
  }
}

function renderStatus() {
  const st = D.status;
  $("asof").textContent = D.as_of;
  $("asof").title = `Data built ${D.generated_at}`;
  $("mode").innerHTML = st.halted ? `<span class="badge halt">HALTED</span>`
    : st.live_money ? `<span class="badge real">LIVE MONEY</span>` : `<span class="badge paper">PAPER · ${esc(st.broker.toUpperCase())}</span>`;
  $("note").innerHTML = CRYPTO
    ? `Backtest from ${D.backtest.start} on today's ${D.universe.length} coins: survivorship-biased (coins that died aren't in it). Sharpe uses 365 days a year and no risk-free rate.`
    : `Backtest on today's ${D.universe.length} mega caps: survivorship-biased, read it as a ceiling. Cash earns T-bills${D.backtest.rf_avg != null ? ` (avg ${pct(D.backtest.rf_avg, 1, false)})` : ""}; Sharpe and alpha are excess of them.`;
}

function tick() {
  const now = new Date();
  const ny = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  $("ny").textContent = ny.toTimeString().slice(0, 8);
  $("utc").textContent = now.toISOString().slice(11, 19);
  const open = CRYPTO || nyseOpen();
  $("mkt").innerHTML = CRYPTO ? `<b class="open">Crypto 24/7</b>` : open ? `<b class="open">NYSE open</b>` : `<b class="closed">NYSE closed</b>`;
  if (LIVE.status === "on") $("livebtn").textContent = open ? `LIVE · ${FEED.name}${LIVE.backup ? " (backup)" : ""}` : "LIVE · market closed";
}

function loadSym(s) {
  if (!D.ohlc[s]) return false;
  sym = s; track(s); renderGP(); renderMon();
  try { history.replaceState(null, "", "#" + encodeURIComponent(s)); } catch (e) {}
  return true;
}

function focusPanel(id) {
  const el = $(id);
  el.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
}

// ---------------------------------------------------------------- command line with suggestions

function resolveSym(q) {
  if (D.ohlc[q]) return q;
  const pair = Object.keys(D.ohlc).find((s) => s.startsWith(q + "/"));
  return pair || null;
}

function run(text) {
  const t = text.trim().toUpperCase().replace(/<GO>/g, "").split(/\s+/).filter(Boolean);
  closeSugg();
  if (!t.length) return;
  if (t[0] === "HELP" || t[0] === "?") return $("help").showModal();
  if (PAGES[t[0]]) { if (!location.pathname.endsWith(PAGES[t[0]]) && !(PAGES[t[0]] === "index.html" && !CRYPTO)) location.href = PAGES[t[0]]; return; }
  if (t[0] === "LIVE" && t[1] === "LIST") { mtab = "live"; renderMon(); return focusPanel("mon"); }
  if (t[0] === "LIVE") return t[1] === "OFF" ? disconnectLive() : openLiveDialog();
  if (FUNCS[t[0]]) { if (D && FUNCS[t[0]][2]) FUNCS[t[0]][2](); return focusPanel(FUNCS[t[0]][0]); }
  const s = resolveSym(t[0]);
  if (s && loadSym(s)) return focusPanel("gp");
  const best = suggest(t[0])[0];
  if (best && best.kind !== "FN" && loadSym(best.code)) return focusPanel("gp");
  $("cmd").value = ""; $("cmd").placeholder = `No match for ${t[0]}. Try a ticker, a company name, or HELP.`;
}

function score(q, code, label) {
  // Exact code > code prefix > word prefix in the name > substring > letters in order.
  const c = code.toUpperCase(), n = label.toUpperCase();
  if (c === q || c.split("/")[0] === q) return 1000;
  if (c.startsWith(q)) return 900 - c.length;
  if (n.split(/[\s&.-]+/).some((w) => w.startsWith(q))) return 700 - n.length / 10;
  if (n.includes(q)) return 500 - n.indexOf(q);
  let i = 0;  // letters in order, codes only: names are long enough to match almost anything
  for (const ch of c) if (ch === q[i]) i++;
  return i === q.length && q.length > 1 ? 200 - c.length : -1;
}

function suggest(raw) {
  const q = raw.trim().toUpperCase();
  if (!q) return [];
  const items = [
    ...Object.entries(D.names).filter(([s]) => D.quotes[s]).map(([s, [n, sec]]) => ({ kind: CRYPTO ? "CRY" : "EQ", code: s, label: n, sub: sec })),
    ...Object.entries(FUNCS).map(([k, [, d]]) => ({ kind: "FN", code: k, label: d })),
    ...Object.entries(EXTRA).map(([k, d]) => ({ kind: "FN", code: k, label: d })),
  ];
  return items.map((it) => ({ ...it, sc: score(q, it.code, it.label) })).filter((it) => it.sc >= 0)
    .sort((a, b) => b.sc - a.sc || a.code.localeCompare(b.code)).slice(0, 8);
}

const hl = (text, q) => {
  const i = text.toUpperCase().indexOf(q);
  return i < 0 || !q ? esc(text) : `${esc(text.slice(0, i))}<mark>${esc(text.slice(i, i + q.length))}</mark>${esc(text.slice(i + q.length))}`;
};

let SUG = [], SEL = -1;
function showSugg() {
  const q = $("cmd").value.trim().toUpperCase();
  SUG = D ? suggest(q) : [];
  SEL = SUG.length ? 0 : -1;
  const ul = $("sugg");
  if (!SUG.length) return closeSugg();
  ul.innerHTML = SUG.map((it, i) => {
    const qt = D.quotes[it.code];
    return `<li role="option" id="sg${i}" aria-selected="${i === SEL}" data-i="${i}"><span class="t ${it.kind}">${it.kind}</span>
      <span class="c">${hl(it.code, q)}</span><span class="n">${hl(it.label, q)}${it.sub ? ` <small>${esc(it.sub)}</small>` : ""}</span>
      <span class="q">${qt ? `${price(qt.last)} <span class="${cls(qt.pct)}">${pct(qt.pct)}</span>` : ""}</span></li>`;
  }).join("");
  ul.hidden = false;
  $("cmd").setAttribute("aria-expanded", "true");
  $("cmd").setAttribute("aria-activedescendant", "sg0");
  ul.querySelectorAll("li").forEach((li) => li.onmousedown = (e) => { e.preventDefault(); pick(+li.dataset.i); });
}
function moveSel(d) {
  if (!SUG.length) return;
  SEL = (SEL + d + SUG.length) % SUG.length;
  $("sugg").querySelectorAll("li").forEach((li, i) => li.setAttribute("aria-selected", i === SEL));
  $("cmd").setAttribute("aria-activedescendant", "sg" + SEL);
  $("sg" + SEL)?.scrollIntoView({ block: "nearest" });
}
function pick(i) { const it = SUG[i]; if (!it) return; $("cmd").value = ""; run(it.code); }
function closeSugg() { $("sugg").hidden = true; $("cmd").setAttribute("aria-expanded", "false"); $("cmd").removeAttribute("aria-activedescendant"); SUG = []; SEL = -1; }

$("cmd").addEventListener("input", showSugg);
$("cmd").addEventListener("blur", () => setTimeout(closeSugg, 100));
$("cmd").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); if ($("sugg").hidden) showSugg(); else moveSel(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); moveSel(-1); }
  else if (e.key === "Tab" && SUG.length && SEL >= 0) { e.preventDefault(); $("cmd").value = SUG[SEL].code; showSugg(); }
  else if (e.key === "Escape") { closeSugg(); }
});
$("cmdform").onsubmit = (e) => {
  e.preventDefault();
  const typed = $("cmd").value.trim().toUpperCase();
  const exact = typed && (resolveSym(typed.split(/\s+/)[0]) || FUNCS[typed] || EXTRA[typed] || PAGES[typed] || typed.startsWith("LIVE"));
  if (!exact && SEL >= 0 && SUG[SEL]) pick(SEL); else run($("cmd").value);
  $("cmd").value = "";
};
$("fkeys").innerHTML = FKEYS.map(([k, f]) => `<button data-f="${f}"><b>${k}</b>${f}</button>`).join("");
$("fkeys").querySelectorAll("button").forEach((b) => b.onclick = () => run(b.dataset.f));
document.addEventListener("keydown", (e) => {
  const fk = FKEYS.find(([k]) => k === e.key);
  if (fk) { e.preventDefault(); return run(fk[1]); }
  const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName) || document.querySelector("dialog[open]");
  if (!typing && e.key.length === 1 && /[a-z]/i.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) $("cmd").focus();
});

// ---------------------------------------------------------------- live prices
// Equities stream from Alpaca's IEX feed (needs an API key). Crypto streams from Alpaca when a key is
// saved, so prices match the account, and falls back to Coinbase's public feed (no key) when there is
// no key or Alpaca fails. Keys stay in this browser.

const alpacaFeed = (name, url, wire, unwire, quotes = false) => ({
  name, keyed: true, url, wire, unwire,
  hello: (c) => ({ action: "auth", key: c.key, secret: c.secret }),
  // Crypto trades on Alpaca can be minutes apart; bid/ask quotes update constantly, so use their midpoint too.
  sub: (syms) => ({ action: "subscribe", trades: syms, ...(quotes ? { quotes: syms } : {}) }),
  unsub: (syms) => ({ action: "unsubscribe", trades: syms, ...(quotes ? { quotes: syms } : {}) }),
  handle(m, w) {
    if (m.T === "success" && m.msg === "authenticated") { w.send(JSON.stringify(this.sub(LIVE.subs.map(this.wire)))); return "on"; }
    if (m.T === "t") trade(this.unwire(m.S), m.p);
    if (m.T === "q" && m.bp > 0 && m.ap > 0) trade(this.unwire(m.S), (m.bp + m.ap) / 2);
    if (m.T === "error") return `error:Alpaca ${m.code}: ${m.msg}${m.code === 406 ? " (another window is already streaming)" : ""}`;
  },
});
const IEX = alpacaFeed("IEX", "wss://stream.data.alpaca.markets/v2/iex", (s) => s.replace("-", "."), (s) => s.replace(".", "-"));
const ALPACA_CRYPTO = alpacaFeed("Alpaca", "wss://stream.data.alpaca.markets/v1beta3/crypto/us", (s) => s, (s) => s, true);
const PREF_STORE = "alphaforge.cryptofeed";  // "coinbase" | "alpaca"
function feedPref() { try { return localStorage.getItem(PREF_STORE) === "alpaca" ? "alpaca" : "coinbase"; } catch (e) { return "coinbase"; } }
function setFeedPref(v) { try { localStorage.setItem(PREF_STORE, v); } catch (e) {} }
const COINBASE = {
  name: "Coinbase", keyed: false, url: "wss://ws-feed.exchange.coinbase.com",
  wire: (s) => s.replace("/", "-"), unwire: (s) => s.replace("-", "/"),
  sub: (syms) => ({ type: "subscribe", product_ids: syms, channels: ["ticker"] }),
  unsub: (syms) => ({ type: "unsubscribe", product_ids: syms, channels: ["ticker"] }),
  handle(m) {
    if (m.type === "subscriptions") return "on";
    if (m.type === "ticker" && m.price) trade(this.unwire(m.product_id), +m.price);
    if (m.type === "error") return `error:Coinbase: ${m.message}${m.reason ? " (" + m.reason + ")" : ""}`;
  },
};
let FEED = CRYPTO ? COINBASE : IEX;
const MAX_SYMS = 30; // Alpaca free plan: 30 symbols per stream; the same rule on both pages
const KEY_STORE = "alphaforge.alpaca", TRACK_STORE = CRYPTO ? "alphaforge.tracked.crypto" : "alphaforge.tracked";
const LIVE = { status: "off", want: false, creds: null, ws: null, backup: "", subs: [], last: {}, prevTick: {}, hi: {}, lo: {}, open: {}, dirty: new Set(), started: false };

function savedCreds() { try { return JSON.parse(localStorage.getItem(KEY_STORE)); } catch (e) { return null; } }

function setLive(status, note = "") {
  LIVE.status = status;
  const b = $("livebtn");
  b.className = "badge live-" + status;
  b.textContent = { off: CRYPTO ? "Paused · click for live" : "Delayed · connect live", connecting: "LIVE · connecting",
    on: `LIVE · ${FEED.name}${LIVE.backup ? " (backup)" : ""}`, error: "LIVE · error" }[status];
  b.title = note || (LIVE.backup ? `Alpaca failed (${LIVE.backup}); streaming from Coinbase instead.`
    : FEED === COINBASE ? "Real-time prices from Coinbase's public feed. Click to stream from Alpaca with your key." : "");
  $("lerr").textContent = status === "error" ? note : "";
  if (status === "on") tick();
  renderFeedSel();
}

function renderFeedSel() {
  const el = $("feedsel");
  if (!el) return;
  const active = !LIVE.want ? "" : FEED === COINBASE ? "coinbase" : "alpaca";
  el.querySelectorAll("button").forEach((b) => {
    b.setAttribute("aria-pressed", b.dataset.f === active);
    b.title = b.dataset.f === "coinbase" ? "Coinbase public feed: no key, any number of windows"
      : "Alpaca crypto feed: needs your key, and uses your one Alpaca connection";
  });
}

function chooseFeed(f) {
  setFeedPref(f);
  if (f === "coinbase") return connectLive(null);
  const c = savedCreds() || LIVE.creds;
  if (c && c.key) return connectLive(c);
  openLiveDialog();  // need a key first
}

if ($("feedsel")) $("feedsel").querySelectorAll("button").forEach((b) => b.onclick = () => chooseFeed(b.dataset.f));

function prevClose(s) {
  const q = D.quotes[s] || (D.strip[s] ?? null);
  return q && (q.date === (CRYPTO ? utcDate() : nyDate()) ? q.last - q.chg : q.last);
}

function openLiveDialog() {
  const c = savedCreds() || LIVE.creds || {};
  $("lk").value = c.key || ""; $("ls").value = c.secret || ""; $("lremember").checked = !!savedCreds();
  $("livedlg").showModal();
}

$("livebtn").onclick = openLiveDialog;
$("livedlg").addEventListener("close", () => {
  const v = $("livedlg").returnValue;
  if (v === "disconnect") return disconnectLive();
  if (v !== "connect") return;
  const creds = { key: $("lk").value.trim(), secret: $("ls").value.trim() };
  if (!creds.key || !creds.secret) {
    if (CRYPTO) { setFeedPref("coinbase"); return connectLive(null); }  // no key: Coinbase
    return setLive("error", "Enter both the key ID and the secret.");
  }
  try { $("lremember").checked ? localStorage.setItem(KEY_STORE, JSON.stringify(creds)) : localStorage.removeItem(KEY_STORE); } catch (e) {}
  if (CRYPTO) setFeedPref("alpaca");
  connectLive(creds);
});

function disconnectLive() {
  LIVE.want = false;
  if (LIVE.ws) LIVE.ws.close();
  LIVE.ws = null;
  setLive("off");
}

function fallBack(reason) {
  // Crypto only: if Alpaca can't stream, keep the page live from Coinbase.
  if (!CRYPTO || FEED === COINBASE) return false;
  LIVE.backup = reason;
  connectLive(null, true);
  return true;
}

function connectLive(creds, keepBackup = false) {
  if (LIVE.ws) { LIVE.ws.onclose = null; LIVE.ws.close(); }
  if (!keepBackup) LIVE.backup = "";
  FEED = creds ? (CRYPTO ? ALPACA_CRYPTO : IEX) : COINBASE;
  LIVE.want = true; LIVE.creds = creds;
  setLive("connecting");
  const w = new WebSocket(FEED.url);
  const feed = FEED;
  let up = false;
  LIVE.ws = w;
  w.onopen = () => w.send(JSON.stringify(feed.keyed ? feed.hello(creds) : feed.sub(LIVE.subs.map(feed.wire))));
  w.onmessage = (e) => {
    for (const m of [].concat(JSON.parse(e.data))) {
      const r = feed.handle(m, w);
      if (r === "on") { up = true; if (LIVE.status !== "on") { setLive("on"); renderMon(); renderGP(); } }
      else if (r && r.startsWith("error:")) {
        const msg = r.slice(6);
        if (feed !== COINBASE && fallBack(msg)) return;
        if (/ 40[1246]| 409/.test(msg)) LIVE.want = false;  // bad key, plan, or connection limit: don't retry
        setLive("error", msg);
      }
    }
  };
  w.onclose = () => {
    if (!LIVE.want || LIVE.ws !== w) return;
    if (!up && feed !== COINBASE && fallBack("could not connect")) return;
    setLive("connecting", "Connection dropped; retrying");
    setTimeout(() => LIVE.want && LIVE.ws === w && connectLive(creds, true), 5000);
  };
}

function initTracked() {
  // Oldest first. Saved picks win; otherwise start with the strategy's names (SPY drops first if full).
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(TRACK_STORE)); } catch (e) {}
  const base = Array.isArray(saved) && saved.length ? saved : CRYPTO ? [...D.universe] : ["SPY", ...D.universe];
  LIVE.subs = [...new Set(base)].filter((x) => D.quotes[x]).slice(-MAX_SYMS);
}

function track(s) {
  // Most recently opened goes to the end; past the limit, the least recently opened is dropped.
  const had = LIVE.subs.includes(s);
  LIVE.subs = [...LIVE.subs.filter((x) => x !== s), s];
  const dropped = LIVE.subs.length > MAX_SYMS ? LIVE.subs.shift() : null;
  try { localStorage.setItem(TRACK_STORE, JSON.stringify(LIVE.subs)); } catch (e) {}
  const w = LIVE.ws;
  if (LIVE.status === "on" && w && w.readyState === 1) {
    if (dropped) w.send(JSON.stringify(FEED.unsub([FEED.wire(dropped)])));
    if (!had) w.send(JSON.stringify(FEED.sub([FEED.wire(s)])));
  }
  if (dropped) for (const k of ["last", "open", "hi", "lo"]) delete LIVE[k][dropped];
}

function trade(s, p) {
  LIVE.lastTick = Date.now();
  if (LIVE.open[s] == null) LIVE.open[s] = p;
  LIVE.hi[s] = Math.max(LIVE.hi[s] ?? p, p);
  LIVE.lo[s] = Math.min(LIVE.lo[s] ?? p, p);
  if (!LIVE.dirty.has(s)) LIVE.prevTick[s] = LIVE.last[s];
  LIVE.dirty.add(s);
  LIVE.last[s] = p;
}

function flash(el, dir) {
  if (!el || !dir) return;
  el.classList.remove("tick-up", "tick-dn");
  el.classList.add(dir > 0 ? "tick-up" : "tick-dn");
  setTimeout(() => el.classList.remove("tick-up", "tick-dn"), 600);
}

function applyLive(s, animate = true) {
  const p = LIVE.last[s], pc = prevClose(s);
  if (p == null) return false;
  const dir = animate ? Math.sign(p - (LIVE.prevTick[s] ?? p)) : 0;
  const chg = pc ? p - pc : null, r = pc ? p / pc - 1 : null;
  const tile = document.querySelector(`.tile[data-k="${CSS.escape(CRYPTO ? s.split("/")[0] : s)}"]`);
  if (tile && r != null) {
    tile.querySelector(".v").textContent = price(p);
    tile.querySelector(".c").textContent = `${price(chg, p)} ${pct(r)}`;
    tile.querySelector(".c").className = "c " + cls(r);
    flash(tile.querySelector(".v"), dir);
  }
  const tr = $("monb").querySelector(`tr[data-s="${CSS.escape(s)}"]`);
  if (tr && r != null) {
    tr.children[1].textContent = price(p);
    tr.children[2].textContent = pct(r);
    tr.children[2].className = cls(r);
    flash(tr.children[1], dir);
  }
  if (s === sym && r != null) {
    $("gpx").textContent = price(p);
    $("gchg").textContent = `${price(chg, p)} ${pct(r)}`;
    $("gchg").className = cls(r);
    flash($("gpx"), dir);
    if (gpSeries && gpBars.length) {
      const today = CRYPTO ? utcDate() : nyDate(), lb = gpBars[gpBars.length - 1], same = lb[0] === today;
      gpSeries.update({ time: today, open: same ? lb[1] : LIVE.open[s],
        high: Math.max(same ? lb[2] : -Infinity, LIVE.hi[s]), low: Math.min(same ? lb[3] : Infinity, LIVE.lo[s]), close: p });
    }
  }
  return bookLive(s, p);
}

setInterval(() => {
  if (!D || !LIVE.dirty.size) return;
  let book = false;
  for (const s of LIVE.dirty) book = applyLive(s) || book;
  LIVE.dirty.clear();
  if (book) { renderBook(); if (ptab === "sleeve") renderPerf(); }
}, 500);

// Re-fit a chart when its panel changes size (late layout, window resize, hidden tab): autoSize keeps the
// old zoom, which leaves the data squeezed into a corner if the first fit happened at zero width.
const refit = new ResizeObserver((entries) => {
  for (const e of entries) {
    const c = e.target.id === "gpc" ? gpChart : pChart;
    if (c && e.contentRect.width > 0) c.timeScale().fitContent();
  }
});
refit.observe($("gpc")); refit.observe($("pc"));

addEventListener("hashchange", () => D && loadSym(decodeURIComponent(location.hash.slice(1)).toUpperCase()));

// ---------------------------------------------------------------- data

async function load() {
  try {
    const r = await fetch(PAGE.data + "?t=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    D = await r.json();
  } catch (e) {
    $("asof").textContent = "unavailable";
    if (!D) $("monb").innerHTML = `<p class="empty">Market data could not be loaded (${esc(e.message)}). The page retries every five minutes.</p>`;
    return;
  }
  const h = decodeURIComponent(location.hash.slice(1)).toUpperCase();
  if (!sym || !D.ohlc[sym]) sym = D.ohlc[h] ? h : CRYPTO ? D.universe[0] : "SPY";
  if (!LIVE.subs.length) initTracked();
  renderStatus(); renderStrip(); renderMon(); renderGP(); renderPerf(); renderBook(); renderBltr(); renderSig(); renderRisk(); renderMth();
  renderPre(); renderDH(); renderAud();
  for (const k of Object.keys(LIVE.last)) applyLive(k, false);
  if (Object.keys(LIVE.last).length) renderBook();
  if (!LIVE.started) {
    LIVE.started = true;
    const c = savedCreds();
    if (CRYPTO) connectLive(feedPref() === "alpaca" && c ? c : null);  // Alpaca falls back to Coinbase if it fails
    else if (c) connectLive(c);
  }
}
tick(); setInterval(tick, 1000);
setInterval(() => D && renderDH(), 5000);
load(); setInterval(load, 5 * 60 * 1000);
