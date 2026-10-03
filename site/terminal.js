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
const FUNCS = {
  MON: ["mon", "Monitor: every ticker with price and change"], GP: ["gp", "Price chart of the selected ticker"],
  PORT: ["book", "Paper book: positions and live P&L"], BLTR: ["bltr", "Order blotter: orders, fills, slippage"],
  SIG: ["sig", "Signals: model scores and targets"], RISK: ["risk", "Risk: volatility, VaR, stress, correlation"],
  BT: ["perf", "Backtest and benchmarks"], MTH: ["mth", "Monthly returns"],
};
const EXTRA = {
  HELP: "List of commands", LIVE: "Connect real-time prices", "LIVE OFF": "Disconnect real-time prices",
  ...(CRYPTO ? {} : { "LIVE LIST": "Live-tracked tickers" }),
  EQUITY: "Open the equities page", CRYPTO: "Open the crypto page",
};
const PAGES = { EQUITY: "index.html", EQ: "index.html", STOCKS: "index.html", CRYPTO: "crypto.html", CRY: "crypto.html" };
const FKEYS = [["F1", "HELP"], ["F2", "MON"], ["F3", "GP"], ["F4", "PORT"], ["F5", "BLTR"], ["F6", "SIG"], ["F7", "RISK"], ["F8", "BT"]];
const SERIES = ["--amber", "--blue", "--aqua", "--violet"];

function chartOpts(el) {
  return { width: el.clientWidth, height: el.clientHeight,
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
  if (CRYPTO) {
    $("mtabs").innerHTML = "";
    $("livecount").textContent = LIVE.status === "on" ? "● streaming" : "";
  } else {
    $("mtabs").innerHTML = [["all", `All ${Object.keys(D.quotes).length}`], ["strat", "Strategy"], ["live", "Live"]].map(([k, l]) =>
      `<button aria-pressed="${k === mtab}" data-k="${k}">${l}</button>`).join("");
    $("mtabs").querySelectorAll("button").forEach((b) => b.onclick = () => { mtab = b.dataset.k; renderMon(); });
    $("livecount").textContent = `● ${LIVE.subs.length}/${MAX_SYMS} live`;
  }
  const keep = mtab === "strat" ? (s) => uni.has(s) : mtab === "live" ? (s) => trk.has(s) : () => true;
  const rows = Object.entries(D.quotes).filter(([s, q]) => q && (CRYPTO || keep(s)));
  if (!CRYPTO && mtab === "live") rows.sort((a, b) => LIVE.subs.indexOf(b[0]) - LIVE.subs.indexOf(a[0]));
  else rows.sort((a, b) => b[1].pct - a[1].pct);
  $("monb").innerHTML = `<table><thead><tr><th>${CRYPTO ? "Coin" : "Ticker"}</th><th>Last</th><th>Chg%</th><th>YTD</th><th>30d</th></tr></thead><tbody>${
    rows.map(([s, q]) => `<tr class="click ${s === sym ? "on" : ""}" data-s="${esc(s)}" tabindex="0" title="${esc(nm(s))}">
      <td class="s">${esc(s)}${!CRYPTO && trk.has(s) ? '<span class="dot" title="Live tracked" aria-label="live tracked">●</span>' : ""}</td>
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
    ${LIVE.status === "on" && (CRYPTO || LIVE.subs.includes(sym)) ? `<span class="trk">● live</span>` : ""}
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
  $("ptabs").innerHTML = [["growth", "Growth"], ["dd", "Drawdown"], ["sleeve", "Paper sleeve"], ["compare", "Compare"]].map(([k, l]) =>
    `<button aria-pressed="${k === ptab}" data-k="${k}">${l}</button>`).join("");
  $("ptabs").querySelectorAll("button").forEach((b) => b.onclick = () => { ptab = b.dataset.k; renderPerf(); });
  const el = $("pc"), names = Object.keys(B.lines);
  if (pChart) { pChart.remove(); pChart = null; }
  el.style.display = ptab === "compare" ? "none" : "";
  $("pcompare").innerHTML = "";
  const kp = (rows) => $("kpis").innerHTML = rows.map(([a, b]) => `<div class="kpi"><div>${a}</div><div>${b}</div></div>`).join("");
  const bench = names[1];
  if (ptab === "sleeve") {
    const c = D.sleeve_curve, st = D.status, t = D.totals;
    const first = c.curve[0], last = c.curve[c.curve.length - 1];
    kp([["Sleeve NAV", money(st.nav)], ["Today", `<span class="${cls(t.day_pl)}">${smoney(t.day_pl)}</span>`],
      ["Since start", first ? pct(last / first - 1) : "–"], ["Unrealized", `<span class="${cls(t.upl)}">${smoney(t.upl)}</span>`],
      ["Drawdown", pct(st.drawdown)], ["Days", c.curve.length]]);
    $("plegend").innerHTML = `<span><i style="background:${css("--amber")}"></i>${CRYPTO ? "Crypto" : "Equities"} sleeve NAV at each daily run</span>`;
    if (c.curve.length < 2) { el.style.display = "none"; $("pcompare").innerHTML = `<p class="empty">The sleeve curve fills in after a few daily runs.</p>`; return; }
    pChart = LightweightCharts.createChart(el, chartOpts(el));
    pChart.addAreaSeries({ lineColor: css("--amber"), topColor: "rgba(255,159,28,.25)", bottomColor: "rgba(255,159,28,0)", lineWidth: 2 })
      .setData(c.dates.map((d, i) => ({ time: d, value: c.curve[i] })));
    pChart.timeScale().fitContent();
    return;
  }
  kp([["CAGR", pct(s.CAGR, 1)], ["Sharpe", `${fmt(s.Sharpe)} <span class="mut">±${fmt(s["Sharpe SE"])}</span>`],
    ["Max DD", pct(s["Max Drawdown"], 1)], ["Vol", pct(s["Ann. Vol"], 1, false)], [`Beta (${bench.split(" ")[0]})`, fmt(s.Beta)],
    ["Alpha", pct(s["Alpha (ann.)"], 1)]]);
  $("plegend").innerHTML = names.map((n, i) => `<span><i style="background:${css(SERIES[i % 4])}"></i>${esc(n)}</span>`).join("") +
    `<span>since ${B.start}, weekly${ptab === "growth" ? ", log scale" : ""}</span>`;
  if (ptab === "compare") {
    $("pcompare").innerHTML = `<table><thead><tr><th>Series</th><th>CAGR</th><th>Vol</th><th>Sharpe</th><th>Max DD</th></tr></thead><tbody>${
      B.compare.map((r) => `<tr><td class="s">${esc(r.name)}</td><td class="${cls(r.CAGR)}">${pct(r.CAGR, 1)}</td><td>${pct(r["Ann. Vol"], 1, false)}</td>
      <td>${fmt(r.Sharpe)}</td><td class="dn">${pct(r["Max Drawdown"], 1)}</td></tr>`).join("")}</tbody></table>`;
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

function renderBook() {
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
  if (!D.book.length) {
    const p = st.pending;
    $("bookb").innerHTML = `<p class="empty">No positions yet. ${p ? `The ${p} rebalance fills at the next close.`
      : D.blotter.some((o) => ["new", "accepted", "pending_new", "partially_filled"].includes(o.status)) ? "Orders are queued at the broker."
      : CRYPTO ? "The sleeve buys at its next weekly signal." : "The book opens at the next month-end signal."}</p>`;
    return;
  }
  $("bookb").innerHTML = `<table><thead><tr><th>${CRYPTO ? "Coin" : "Ticker"}</th><th>Qty</th><th>Avg</th><th>Last</th><th>Value</th><th>Wt</th><th>Today</th><th>Unrealized</th></tr></thead><tbody>${
    D.book.map((p) => `<tr class="click" data-s="${esc(p.sym)}" title="${esc(p.name)}"><td class="s">${esc(p.sym)}</td><td>${qty(p.qty)}</td>
      <td>${price(p.avg)}</td><td class="lv" data-f="last">${price(p.last)}</td><td data-f="mv">${money(p.mv)}</td><td data-f="w">${pct(p.weight, 1, false)}</td>
      <td data-f="day" class="${cls(p.day_pl)}">${smoney(p.day_pl)} <small class="mut">${pct(p.day_pct, 1)}</small></td>
      <td data-f="upl" class="${cls(p.upl)}">${smoney(p.upl)} <small class="mut">${pct(p.upl_pct, 1)}</small></td></tr>`).join("")}</tbody>
    <tfoot><tr><td>Total</td><td></td><td></td><td></td><td>${money(t.mv)}</td><td>${pct(t.weight, 1, false)}</td>
      <td class="${cls(t.day_pl)}">${smoney(t.day_pl)}</td><td class="${cls(t.upl)}">${smoney(t.upl)} <small class="mut">${pct(t.upl_pct, 1)}</small></td></tr></tfoot></table>`;
  bindRows($("bookb"));
}

function bookLive(s, p) {
  // Recompute one position's P&L from a live price, the way Alpaca does: unrealized vs cost, today vs last close.
  const r = D.book.find((x) => x.sym === s);
  if (!r) return false;
  r.last = p; r.mv = r.qty * p; r.upl = r.mv - r.cost; r.upl_pct = r.cost ? r.upl / Math.abs(r.cost) : null;
  if (r.lastday) { r.day_pl = (p - r.lastday) * r.qty; r.day_pct = p / r.lastday - 1; }
  r.weight = D.status.nav ? r.mv / D.status.nav : null;
  const t = D.totals;
  ["mv", "cost", "upl", "day_pl"].forEach((k) => t[k] = D.book.reduce((a, x) => a + (x[k] || 0), 0));
  t.upl_pct = t.cost ? t.upl / Math.abs(t.cost) : null; t.weight = D.status.nav ? t.mv / D.status.nav : null;
  return true;
}

function renderBltr() {
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
  const r = D.risk, st = D.status, a = D.account, nav = st.nav;
  const sleeve = CRYPTO ? "Crypto sleeve" : "Equities sleeve";
  $("risklabel").textContent = sleeve;
  const share = (v) => a.equity ? pct(v / a.equity, 0, false) : "–";
  const used = st.halt_at ? Math.min(1, Math.max(0, st.drawdown / st.halt_at)) : 0;
  const n = r.corr_syms.length;
  $("riskb").innerHTML = `
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
  const mins = ny.getHours() * 60 + ny.getMinutes(), wd = ny.getDay();
  const open = CRYPTO || (wd > 0 && wd < 6 && mins >= 570 && mins < 960);
  $("mkt").innerHTML = CRYPTO ? `<b class="open">Crypto 24/7</b>` : open ? `<b class="open">NYSE open</b>` : `<b class="closed">NYSE closed</b>`;
  if (LIVE.status === "on") $("livebtn").textContent = open ? `LIVE · ${CRYPTO ? "Alpaca" : "IEX"}` : "LIVE · market closed";
}

function loadSym(s) {
  if (!D.ohlc[s]) return false;
  sym = s; if (!CRYPTO) track(s); renderGP(); renderMon();
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
  if (t[0] === "LIVE" && t[1] === "LIST" && !CRYPTO) { mtab = "live"; renderMon(); return focusPanel("mon"); }
  if (t[0] === "LIVE") return t[1] === "OFF" ? disconnectLive() : openLiveDialog();
  if (FUNCS[t[0]]) return focusPanel(FUNCS[t[0]][0]);
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
addEventListener("resize", () => {
  for (const [c, el] of [[gpChart, $("gpc")], [pChart, $("pc")]]) if (c) c.applyOptions({ width: el.clientWidth });
});

// ---------------------------------------------------------------- live prices (Alpaca market data; keys stay in this browser)

const STREAM = CRYPTO ? "wss://stream.data.alpaca.markets/v1beta3/crypto/us" : "wss://stream.data.alpaca.markets/v2/iex";
const MAX_SYMS = 30; // Alpaca free plan: 30 stock symbols per stream
const KEY_STORE = "alphaforge.alpaca", TRACK_STORE = "alphaforge.tracked";
const toAlpaca = (s) => CRYPTO ? s : s.replace("-", "."), fromAlpaca = (s) => CRYPTO ? s : s.replace(".", "-");
const LIVE = { status: "off", creds: null, ws: null, subs: [], last: {}, prevTick: {}, hi: {}, lo: {}, open: {}, dirty: new Set(), started: false };

function savedCreds() { try { return JSON.parse(localStorage.getItem(KEY_STORE)); } catch (e) { return null; } }

function setLive(status, note = "") {
  LIVE.status = status;
  const b = $("livebtn");
  b.className = "badge live-" + status;
  b.textContent = { off: "Delayed · connect live", connecting: "LIVE · connecting", on: "LIVE", error: "LIVE · error" }[status];
  b.title = note;
  $("lerr").textContent = status === "error" ? note : "";
  if (status === "on") tick();
}

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
  if (!creds.key || !creds.secret) return setLive("error", "Enter both the key ID and the secret.");
  try { $("lremember").checked ? localStorage.setItem(KEY_STORE, JSON.stringify(creds)) : localStorage.removeItem(KEY_STORE); } catch (e) {}
  connectLive(creds);
});

function disconnectLive() {
  LIVE.creds = null;
  if (LIVE.ws) LIVE.ws.close();
  LIVE.ws = null;
  setLive("off");
}

function connectLive(creds) {
  if (LIVE.ws) { LIVE.ws.onclose = null; LIVE.ws.close(); }
  LIVE.creds = creds;
  setLive("connecting");
  if (CRYPTO) LIVE.subs = Object.keys(D.quotes);
  const w = new WebSocket(STREAM);
  LIVE.ws = w;
  w.onopen = () => w.send(JSON.stringify({ action: "auth", key: creds.key, secret: creds.secret }));
  w.onmessage = (e) => {
    for (const m of JSON.parse(e.data)) {
      if (m.T === "success" && m.msg === "authenticated") {
        w.send(JSON.stringify({ action: "subscribe", trades: LIVE.subs.map(toAlpaca) }));
        setLive("on"); renderMon(); renderGP();
      } else if (m.T === "t") trade(fromAlpaca(m.S), m.p);
      else if (m.T === "error") {
        // 402 bad keys, 406 another connection open, 409 plan lacks this feed: retrying won't help.
        if ([401, 402, 404, 406, 409].includes(m.code)) LIVE.creds = null;
        setLive("error", `Alpaca ${m.code}: ${m.msg}${m.code === 406 ? " (another window is already streaming)" : ""}`);
      }
    }
  };
  w.onclose = () => {
    if (!LIVE.creds || LIVE.creds !== creds) return;
    setLive("connecting", "Connection dropped; retrying");
    setTimeout(() => LIVE.creds === creds && connectLive(creds), 5000);
  };
}

function initTracked() {
  if (CRYPTO) { LIVE.subs = Object.keys(D.quotes); return; }
  // Oldest first. Saved picks win; otherwise start with the strategy's names (SPY drops first if full).
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(TRACK_STORE)); } catch (e) {}
  const base = Array.isArray(saved) && saved.length ? saved : ["SPY", ...D.universe];
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
    if (dropped) w.send(JSON.stringify({ action: "unsubscribe", trades: [toAlpaca(dropped)] }));
    if (!had) w.send(JSON.stringify({ action: "subscribe", trades: [toAlpaca(s)] }));
  }
  if (dropped) for (const k of ["last", "open", "hi", "lo"]) delete LIVE[k][dropped];
}

function trade(s, p) {
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
  for (const k of Object.keys(LIVE.last)) applyLive(k, false);
  if (Object.keys(LIVE.last).length) renderBook();
  if (!LIVE.started) { LIVE.started = true; const c = savedCreds(); if (c) connectLive(c); }
}
tick(); setInterval(tick, 1000);
load(); setInterval(load, 5 * 60 * 1000);
