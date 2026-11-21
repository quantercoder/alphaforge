"use strict";
// AlphaForge Lab: renders site/lab.json. Every panel is tagged DATA (measured) or MODEL (estimated).

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
// Links from third-party feeds: only http(s), never javascript: or data: URLs.
const safeUrl = (u) => /^https?:\/\//i.test(String(u || "")) ? u : null;
const num = (v) => typeof v === "number" && isFinite(v);
const fmt = (v, d = 2) => !num(v) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1, sign = true) => !num(v) ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
const money = (v) => !num(v) ? "–" : (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
const cls = (v) => !num(v) || v === 0 ? "" : v > 0 ? "up" : "dn";
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const table = (head, rows, extra = "") => `<table ${extra}><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
const bar = (u, color) => `<div class="bar"><i style="left:0;width:${Math.max(0, Math.min(100, u * 100))}%;background:${color}"></i></div>`;
const sub = (t) => `<div class="sub">${t}</div>`;
const note = (t) => `<p class="note">${t}</p>`;
const empty = (t) => `<p class="empty">${t}</p>`;
const kpis = (items, n = 4) => `<div class="kpis" style="grid-template-columns:repeat(${n},minmax(0,1fr))">${
  items.map(([a, b]) => `<div class="kpi"><div>${a}</div><div>${b}</div></div>`).join("")}</div>`;
const pass = (ok) => ok ? '<b class="up">pass</b>' : '<b class="dn">fail</b>';
const SERIES = ["--amber", "--blue", "--aqua", "--violet", "--cmd", "--up", "--down"];

let L = null, horizon = "21", stab = "top", ptab = "now", charts = {}, picked = null;

function setTabs(id, items, cur, pick) {
  $(id).innerHTML = items.map(([k, l]) => `<button aria-pressed="${k === cur}" data-k="${k}">${l}</button>`).join("");
  $(id).querySelectorAll("button").forEach((b) => b.onclick = () => pick(b.dataset.k));
}

function chart(id) {
  if (charts[id]) charts[id].remove();
  charts[id] = LightweightCharts.createChart($(id), { autoSize: true,
    layout: { background: { color: css("--panel") }, textColor: css("--dim"), fontFamily: css("--f"), fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: "#15100b" }, horzLines: { color: "#15100b" } },
    rightPriceScale: { borderColor: css("--rule") }, timeScale: { borderColor: css("--rule") } });
  return charts[id];
}
const line = (c, color, title) => c.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true, title });

// ---------------------------------------------------------------- top strip

function renderStrip() {
  const I = L.intel, rg = I.regime, h = L.forecast_market.horizons["21"], r = L.risk;
  const tiles = [
    ["Regime", `<b class="${rg.label === "Stress" ? "dn" : rg.label === "Risk-on" ? "up" : ""}">${esc(rg.label)}</b>`, "MODEL"],
    ["VIX", `${fmt(rg.vix, 1)} <small class="${rg.vix_inverted ? "dn" : "mut"}">${rg.vix_inverted ? "curve inverted" : "normal curve"}</small>`, "DATA"],
    ["SPY vs 200-day", `<span class="${cls(rg.spy_vs_200d)}">${pct(rg.spy_vs_200d)}</span>`, "DATA"],
    ["SPY GARCH vol", `${pct(rg.garch_vol, 0, false)} <small class="mut">${pct(rg.vol_pct_10y, 0, false)} pctl</small>`, "MODEL"],
    ["Above 200-day", `${pct(I.breadth.above_200d, 0, false)} <small class="mut">of S&P 500</small>`, "DATA"],
    ["Adv / decl", `<span class="up">${I.breadth.advancing}</span> / <span class="dn">${I.breadth.declining}</span>`, "DATA"],
    ["SPY 1M ensemble", `<span class="${cls(h.today.Ensemble)}">${pct(h.today.Ensemble)}</span>`, "MODEL"],
    ["1M 80% range", `${pct(h.scenarios.lo80, 0)} … ${pct(h.scenarios.hi80, 0)}`, "MODEL"],
    ["Book VaR 99% 1d", r ? pct(r.methods["Filtered historical (GARCH)"]["99"].var1, 1, false) : "–", "MODEL"],
    ["Alerts", `<b class="${L.alerts.some((a) => a.level === "warn") ? "dn" : ""}">${L.alerts.filter((a) => a.level === "warn").length} warn</b>`, "MODEL"],
  ];
  $("lstrip").innerHTML = tiles.map(([n, v, k]) => `<div class="tile"><div class="n">${n} <span class="tag ${k === "DATA" ? "d" : "m"}">${k[0]}</span></div><div class="v">${v}</div></div>`).join("");
}

// ---------------------------------------------------------------- regime, macro, breadth

function renderRegime() {
  const rg = L.intel.regime;
  $("regdate").textContent = rg.date;
  $("regb").innerHTML = `${kpis([["Regime", `<b class="${rg.label === "Stress" ? "dn" : rg.label === "Risk-on" ? "up" : ""}">${esc(rg.label)}</b>`],
      ["Trend", rg.trend_up ? '<span class="up">above 200-day</span>' : '<span class="dn">below 200-day</span>'],
      ["GARCH vol", pct(rg.garch_vol, 1, false)], ["10-year pctl", pct(rg.vol_pct_10y, 0, false)]])}
    ${note(esc(rg.rule))}
    ${sub("Alerts (rule-based, research only)")}
    ${table(["", "Alert"], L.alerts.map((a) => `<tr><td><i class="light" style="background:${css(a.level === "warn" ? "--down" : "--blue")}"></i></td><td class="wrap">${esc(a.text)}</td></tr>`))}`;
}

function renderMacro() {
  const M = L.intel.macro;
  $("macdate").textContent = M.length ? `as of ${M[0].date}` : "";
  $("macb").innerHTML = table(["Indicator", "Now", "1m", "z (1y)", "10-year percentile"], M.map((m) => {
    const v = m.kind === "price" && m.value > 50 ? fmt(m.value, 0) : fmt(m.value, m.kind === "ratio" ? 3 : 2);
    const ch = m.kind === "price" ? pct(m.chg_1m) : (m.chg_1m > 0 ? "+" : "") + fmt(m.chg_1m, 2);
    const z = m.z_1y, col = !num(z) ? "--dim" : Math.abs(z) > 2 ? "--down" : Math.abs(z) > 1 ? "--cmd" : "--up";
    return `<tr><td class="l">${esc(m.name)}</td><td>${v}</td><td class="${cls(m.chg_1m)}">${ch}</td><td style="color:${css(col)}">${fmt(z, 1)}</td>
      <td style="width:28%">${bar(m.pct_10y, css("--amber"))}<small class="mut">${pct(m.pct_10y, 0, false)}</small></td></tr>`;
  })) + note("z = how many standard deviations today's value is from its 1-year average (|z| > 2 is unusual). Percentile = where today sits in 10 years of history.");
}

function renderBreadth() {
  const B = L.intel.breadth, S = L.intel.sectors;
  $("brddate").textContent = `as of ${B.date}`;
  $("brdb").innerHTML = `${kpis([["Above 200-day", pct(B.above_200d, 0, false)], ["Above 50-day", pct(B.above_50d, 0, false)],
      ["52-week highs / lows", `<span class="up">${B.new_high_52w}</span> / <span class="dn">${B.new_low_52w}</span>`],
      ["Advancing / declining", `<span class="up">${B.advancing}</span> / <span class="dn">${B.declining}</span>`]])}
    ${sub("Sector ETFs")}
    ${table(["Sector", "1w", "1m", "3m", "YTD"], S.map((s) => `<tr><td class="l">${esc(s.sector)} <small class="mut">${s.etf}</small></td>
      ${["w1", "m1", "m3", "ytd"].map((k) => `<td class="${cls(s[k])}">${pct(s[k])}</td>`).join("")}</tr>`))}
    ${note(`Breadth over today's ${B.members} S&P 500 members.`)}`;
}

// ---------------------------------------------------------------- market forecast

function renderMarket() {
  const A = L.forecast_market;
  setTabs("htabs", Object.keys(A.horizons).map((h) => [h, h === "5" ? "1 week" : h === "21" ? "1 month" : "3 months"]), horizon, (k) => { horizon = k; renderMarket(); });
  const H = A.horizons[horizon], S = H.scenarios, E = H.eval, hm = E["Historical mean"];
  const models = Object.keys(H.today);
  const rows = models.map((m) => {
    const e = E[m] || {}, ens = m === "Ensemble";
    return `<tr${ens ? ' class="on"' : ""}><td class="l">${ens ? "<b>Ensemble</b>" : esc(m)}</td><td class="${cls(H.today[m])}">${pct(H.today[m], 2)}</td>
      <td class="${cls(e.r2_oos)}">${m === "Historical mean" ? '<span class="mut">benchmark</span>' : pct(e.r2_oos, 1)}</td>
      <td class="mut">${e.dm_p == null ? "–" : fmt(e.dm_p, 2)}</td><td>${pct(e.hit, 0, false)}</td></tr>`;
  });
  $("fcmb").innerHTML = `${kpis([["Bear (10th pct)", `<span class="dn">${pct(S.bear)}</span>`], ["Base (median)", `<span class="${cls(S.base)}">${pct(S.base)}</span>`],
      ["Bull (90th pct)", `<span class="up">${pct(S.bull)}</span>`], ["95% interval", `${pct(S.lo95, 0)} … ${pct(S.hi95, 0)}`],
      ["GARCH σ over horizon", pct(H.sigma, 1, false)], ["Interval coverage", `${pct(S.coverage80, 0, false)} <small class="mut">of 80%</small>`],
      ["Rule: R² > 0, DM p < 0.05", pass(H.rules[0][1])], ["Verdict", H.passed ? '<b class="up">skill shown</b>' : '<b class="dn">no skill shown</b>']], 4)}
    ${table(["Model", "Forecast today", "Out-of-sample R²", "DM p", "Hit rate"], rows)}`;
  $("fcmnote").innerHTML = `Features: ${esc(A.feature_source || "Yahoo market prices")}. Out of sample since 2014: every model refitted each January on past data only. R² is measured against the historical mean; below 0 means worse than simply assuming the average return. The historical mean's own hit rate is ${pct(hm.hit, 0, false)} because markets mostly rise, so beating 50% proves nothing; the model has to beat ${pct(hm.hit, 0, false)}. Bull, base and bear come from this period's GARCH volatility and the spread of past forecast errors. Chart: ensemble forecast (amber) against what happened (blue), last 5 years.`;
  const c = chart("fcmc"), hs = H.history;
  line(c, css("--blue"), "Realized").setData(hs.dates.map((d, i) => ({ time: d, value: hs.realized[i] * 100 })));
  line(c, css("--amber"), "Forecast").setData(hs.dates.map((d, i) => ({ time: d, value: hs.forecast[i] * 100 })));
  c.timeScale().fitContent();
}

// ---------------------------------------------------------------- stock forecasts

function renderStocks() {
  const X = L.forecast_xs, S = L.stocks;
  setTabs("stabs", [["top", "Highest"], ["low", "Lowest"], ["models", "Models"], ["rules", "Test"]], stab, (k) => { stab = k; renderStocks(); });
  let h;
  if (stab === "top" || stab === "low") {
    const rows = (stab === "top" ? S.slice(0, 25) : S.slice(-25).reverse());
    h = table(["Stock", "1M forecast", "Bear / bull", "Risk/reward", "Model agreement"], rows.map((r) => `<tr title="${esc(r.name)} · ${esc(r.sector)}">
      <td class="s">${esc(r.sym)}</td><td class="${cls(r.fc)}">${pct(r.fc, 2)}</td><td class="mut">${pct(r.bear, 0)} / ${pct(r.bull, 0)}</td>
      <td>${fmt(r.rr, 2)}</td><td style="width:22%">${bar(r.agree, css("--violet"))}</td></tr>`))
      + note(`${L.stocks.length} current S&P 500 members. Forecast = IC × GARCH volatility × the ensemble's standardized rank (IC ${fmt(X.models.Ensemble.ic, 3)}). Bear and bull are the 10th and 90th percentiles; risk/reward = bull ÷ |bear|, about 1.0 when a forecast carries no information. Agreement: 1 when all five models rank the stock alike.`);
  } else if (stab === "models") {
    h = table(["Model", "Rank IC", "t", "Top 20% vs equal weight (IR)", "t"], Object.entries(X.models).map(([m, e]) =>
      `<tr><td class="l">${esc(m)}</td><td class="${cls(e.ic)}">${fmt(e.ic, 3)}</td><td>${fmt(e.ic_t, 1)}</td><td class="${cls(e.ir)}">${fmt(e.ir, 2)}</td><td>${fmt(e.t, 1)}</td></tr>`))
      + note("Out of sample from 2016 on the point-in-time S&P 500, refitted every January. Features: momentum 12-1 and 6-1, 1-month reversal, 52-week high, volatility, beta, residual momentum, largest daily return, dollar volume.");
  } else {
    h = table(["Pre-registered rule", "Result", "Evidence"], X.rules.map(([n, ok, ev]) => `<tr><td class="l">${esc(n)}</td><td>${pass(ok)}</td><td class="wrap mut">${esc(ev)}</td></tr>`))
      + note(`Verdict: <b class="${X.passed ? "up" : "dn"}">${X.passed ? "passes" : "no demonstrated edge"}</b>. The rules were committed before the run (PREREGISTRATION_4.md).`);
  }
  $("fcsb").innerHTML = h;
}

// ---------------------------------------------------------------- strategy lab

function renderStrategies() {
  const T = L.strategies;
  if (!picked) picked = new Set([T[0].name, "Buy and hold SPY", "Equal weight S&P 500 (benchmark)", "Momentum, long-only top 20%"].filter((n) => L.curves[n]));
  $("stlb").innerHTML = table(["", "Strategy", "Universe", "Sharpe", "Sortino", "CAGR", "Max DD", "Calmar", "Win", "Cost / yr", "PSR", "Sharpe <2020", "≥2020"],
    T.map((r, i) => `<tr class="click${picked.has(r.name) ? " on" : ""}" data-n="${esc(r.name)}"><td class="mut">${i + 1}</td><td class="l">${esc(r.name)}</td>
      <td class="mut wrap">${esc(r.universe)}</td><td><b>${fmt(r.sharpe)}</b></td><td>${fmt(r.sortino)}</td><td class="${cls(r.cagr)}">${pct(r.cagr)}</td>
      <td class="dn">${pct(r.maxdd)}</td><td>${fmt(r.calmar)}</td><td>${pct(r.win, 0, false)}</td><td class="mut">${r.cost_drag == null ? "–" : pct(r.cost_drag, 1, false)}</td>
      <td>${pct(r.psr, 0, false)}</td><td>${fmt(r.sharpe_pre2020)}</td><td>${fmt(r.sharpe_2020on)}</td></tr>`))
    + note("Ranked by Sharpe (excess of T-bills where cash is held). PSR = probability that the true Sharpe is above 0 given the sample length, skew and fat tails (Bailey & López de Prado). Each universe and its biases are named; cross-sectional strategies use the S&P 500 as it was at each date. Nothing here is traded except the crypto sleeve and the stock strategy on the other pages.");
  $("stlb").querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => {
    const n = tr.dataset.n; picked.has(n) ? picked.delete(n) : picked.add(n); renderStrategies();
  });
  const c = chart("stlc");
  c.priceScale("right").applyOptions({ mode: 1 });
  const legend = [];
  [...picked].forEach((n, i) => {
    const cv = L.curves[n], col = css(SERIES[i % SERIES.length]);
    if (!cv) return;
    line(c, col, "").setData(cv.dates.map((d, j) => ({ time: d, value: cv.v[j] })));
    legend.push(`<span><i style="background:${col}"></i>${esc(n)}</span>`);
  });
  $("stlleg").innerHTML = legend.join("") + "<span>growth of 1, log scale, monthly</span>";
  c.timeScale().fitContent();
}

// ---------------------------------------------------------------- risk

function renderRisk() {
  const R = L.risk;
  if (!R) { $("rskb").innerHTML = empty("No paper-book positions recorded yet."); return; }
  $("rskdate").textContent = `positions ${R.asof}`;
  const nav = R.nav, M = R.methods, T = R.tail;
  const rows = Object.entries(M).map(([m, v]) => `<tr><td class="l">${esc(m)}</td>
    ${["95", "99"].map((l) => `<td>${pct(v[l].var1, 2, false)}<small class="mut"> ${money(v[l].var1 * nav)}</small></td><td class="mut">${v[l].es1 == null ? "–" : pct(v[l].es1, 2, false)}</td><td>${pct(v[l].var10, 1, false)}</td>`).join("")}</tr>`);
  const D = R.dist10, mx = Math.max(...D.counts);
  const hist = `<svg viewBox="0 0 400 90" width="100%" height="90" role="img" aria-label="Distribution of 10-day profit and loss">${D.counts.map((n, i) => {
    const x = i * 10, h = n / mx * 80, mid = (D.edges[i] + D.edges[i + 1]) / 2;
    return `<rect x="${x}" y="${88 - h}" width="9" height="${h}" fill="${css(mid < 0 ? "--down" : "--up")}" opacity=".75"><title>${pct(D.edges[i], 1)} to ${pct(D.edges[i + 1], 1)}: ${n} paths</title></rect>`;
  }).join("")}</svg>`;
  const C = R.corr, n = C.syms.length;
  const corr = `<div class="corr" style="grid-template-columns:38px repeat(${n},1fr)"><span></span>${C.syms.map((s) => `<span class="cl">${esc(s)}</span>`).join("")}${
    C.m.map((row, i) => `<span class="rl">${esc(C.syms[i])}</span>` + row.map((v, j) => `<i style="background:${v >= 0 ? `rgba(255,159,28,${0.06 + 0.85 * Math.abs(v)})` : `rgba(74,158,255,${0.06 + 0.85 * Math.abs(v)})`}" title="${esc(C.syms[i])} / ${esc(C.syms[j])}: ${fmt(v)}"></i>`).join("")).join("")}</div>`;
  $("rskb").innerHTML = `${kpis([["Book value", money(nav)], ["Gross / net", `${pct(R.exposure.gross, 0, false)} / ${pct(R.exposure.net, 0, false)}`],
      ["Beta to SPY", fmt(T.beta_spy)], ["GARCH vol now", pct(T.garch.vol_now, 1, false)], ["Max DD (3y, today's weights)", `<span class="dn">${pct(T.max_drawdown_3y)}</span>`],
      ["Skew / excess kurtosis", `${fmt(T.skew)} / ${fmt(T.excess_kurtosis, 1)}`], ["Worst / best day", `<span class="dn">${pct(T.worst_day)}</span> / <span class="up">${pct(T.best_day)}</span>`],
      ["Tail ratio", fmt(T.tail_ratio)]], 4)}
    ${sub("Value at Risk and Expected Shortfall (loss, share of the book)")}
    ${table(["Method", "VaR 95% 1d", "ES 95%", "VaR 95% 10d", "VaR 99% 1d", "ES 99%", "VaR 99% 10d"], rows)}
    ${sub("10-day P&L distribution (filtered historical simulation, 5,000 paths)")}${hist}
    ${sub("Correlation, last 252 days")}${corr}
    ${note("Five VaR methods side by side, because each fails differently: historical misses what hasn't happened in 2 years, normal ignores fat tails, Cornish-Fisher adjusts for skew and kurtosis, filtered historical rescales past shocks to today's GARCH volatility, and Monte Carlo uses Student-t shocks (5 degrees of freedom) with GARCH volatilities and the correlation matrix. The book is today's equity positions held over the past 3 years.")}`;
}

// ---------------------------------------------------------------- portfolio, leverage

function renderPortfolio() {
  setTabs("ptabs", [["now", "Today"], ["weights", "Weights"], ["bt", "Walk-forward"]], ptab, (k) => { ptab = k; renderPortfolio(); });
  const A = L.allocations;
  let h;
  if (ptab === "now") {
    h = table(["Method", "Forecast vol", "Diversification ratio", "Effective names", "Largest risk share"], A.map((a) =>
      `<tr><td class="l">${esc(a.method)}</td><td>${pct(a.vol, 1, false)}</td><td>${fmt(a.div_ratio)}</td><td>${fmt(a.eff_n, 1)}</td><td>${pct(a.max_rc, 0, false)}</td></tr>`))
      + note("The strategy's 30 stocks, long-only, at most 10% each, with GARCH volatilities and the 252-day correlation. Diversification ratio = weighted average volatility ÷ portfolio volatility (higher = more diversification). Effective names = 1 ÷ sum of squared weights. Mean-variance uses the ML ensemble's forecasts, which are close to zero, so it lands near minimum variance.");
  } else if (ptab === "weights") {
    const syms = [...new Set(A.flatMap((a) => Object.keys(a.weights)))].sort();
    h = `<div style="overflow:auto">${table(["Stock", ...A.map((a) => esc(a.method.split(" (")[0]))], syms.map((s) => `<tr><td class="s">${esc(s)}</td>${
      A.map((a) => { const w = a.weights[s] || 0; return `<td style="background:rgba(255,159,28,${Math.min(0.8, w * 6)})">${w ? pct(w, 1, false) : ""}</td>`; }).join("")}</tr>`))}</div>`;
  } else {
    h = table(["Method", "Sharpe", "CAGR", "Vol", "Max DD", "Sharpe <2020", "≥2020"], L.allocation_backtest.map((a) =>
      `<tr><td class="l">${esc(a.method)}</td><td><b>${fmt(a.sharpe)}</b></td><td class="${cls(a.cagr)}">${pct(a.cagr)}</td><td>${pct(a.vol, 1, false)}</td>
       <td class="dn">${pct(a.maxdd)}</td><td>${fmt(a.sharpe_pre2020)}</td><td>${fmt(a.sharpe_2020on)}</td></tr>`))
      + note("Each method rebalanced monthly from 2016 on today's 30 names, net of 7 bp per unit of turnover. Survivorship-biased (today's names), so compare the methods with each other, not with the market.");
  }
  $("pfob").innerHTML = h;
  const K = L.kelly;
  $("levb").innerHTML = table(["Leverage", "CAGR", "Vol", "Max DD", "P(lose >20% in a year)", "P(lose >50%)", "Median year"], L.leverage.map((x) =>
    `<tr><td><b>${fmt(x.leverage, 1)}×</b></td><td class="${cls(x.cagr)}">${pct(x.cagr)}</td><td>${pct(x.vol, 1, false)}</td><td class="dn">${pct(x.maxdd)}</td>
     <td>${pct(x.p_loss_20, 1, false)}</td><td>${pct(x.p_loss_50, 1, false)}</td><td class="${cls(x.median_1y)}">${pct(x.median_1y)}</td></tr>`))
    + note("The live stock strategy's backtest, levered by borrowing at T-bills + 1%; probabilities from 2,000 one-year paths resampled in 21-day blocks. A backtest overstates future returns (survivorship, and the fair-universe tests found no edge), so read these as upper bounds.")
    + sub("Position sizing (Kelly)")
    + kpis([["Backtest Sharpe", `${fmt(K.sharpe)} <small class="mut">± ${fmt(K.sharpe_se)}</small>`], ["Full Kelly", `${fmt(K.full, 1)}×`], ["Half Kelly", `${fmt(K.half, 1)}×`],
            ["Kelly at lower 95% Sharpe", `${fmt(K.low, 1)}×`]])
    + note(esc(K.note));
}

// ---------------------------------------------------------------- anomalies, earnings, news, integrity

function renderActivity() {
  const A = L.intel.anomalies;
  $("anmb").innerHTML = sub("Unusual moves today (|move| > 3 standard deviations or volume > 3 standard deviations)")
    + (A.length ? table(["Stock", "Move", "Move z", "Volume z"], A.slice(0, 15).map((a) => `<tr><td class="s">${esc(a.sym)}</td><td class="${cls(a.ret)}">${pct(a.ret)}</td>
        <td class="${cls(a.ret_z)}">${fmt(a.ret_z, 1)}</td><td>${fmt(a.vol_z, 1)}</td></tr>`)) : empty("Nothing unusual today."))
    + sub("Upcoming earnings (strategy names)")
    + (L.earnings.length ? table(["Stock", "Date"], L.earnings.map((e) => `<tr><td class="s">${esc(e.sym)}</td><td>${esc(e.date)}</td></tr>`)) : empty("No upcoming dates returned by the source."))
    + sub("Headlines (Yahoo Finance, third-party, not verified here)")
    + (L.news.length ? table(["Time", "Headline", "Source"], L.news.map((n) => `<tr><td class="mut">${esc((n.time || "").slice(0, 16).replace("T", " "))}</td>
        <td class="wrap">${safeUrl(n.url) ? `<a href="${esc(safeUrl(n.url))}" target="_blank" rel="noopener noreferrer">${esc(n.title)}</a>` : esc(n.title)}</td><td class="mut">${esc(n.publisher)}</td></tr>`))
      : empty("Unavailable: the headline source returned nothing at build time."))
    + note("Volume is not institutional flow: real flow data isn't available free, and none is estimated here.");
}

function renderIntegrity() {
  $("dqb").innerHTML = `<div class="fcgrid"><div>${sub("Sources and timestamps")}${table(["", "Data", "Source", "As of"], L.sources.map((s) =>
      `<tr><td><span class="tag ${s.kind === "DATA" ? "d" : "m"}">${s.kind}</span></td><td class="l wrap">${esc(s.data)}</td><td class="mut wrap">${esc(s.source)}</td><td class="mut">${esc(s.asof)}</td></tr>`))}
    ${sub("Bias controls")}<ul class="ul">${L.controls.map((c) => `<li>${esc(c)}</li>`).join("")}</ul></div>
    <div>${sub("Unavailable, and not replaced by estimates")}${table(["Item", "Why"], L.unavailable.map((u) => `<tr><td class="l wrap"><b class="dn">✕</b> ${esc(u.item)}</td><td class="mut wrap">${esc(u.why)}</td></tr>`))}
    ${sub("What the tests found")}<ul class="ul">
      <li>Seven pre-registered tests: no stock signal or model shows an edge over equal weight on the fair, point-in-time S&amp;P 500.</li>
      <li>No market-forecasting model beats the historical mean out of sample at 1 week, 1 month or 3 months, with Yahoo stand-ins (test 4) or point-in-time FRED / ALFRED macro data (test 6).</li>
      <li>No fundamental signal from SEC filings (book-to-market, earnings yield, profitability, earnings surprises) shows an edge (test 7).</li>
      <li>Volatility <i>is</i> forecastable: GARCH beat the 63-day sample for 96% of stocks, and the live strategy uses it.</li>
      <li>Every report is in the repository: docs/RESEARCH*.md, with the rules in docs/PREREGISTRATION*.md.</li></ul></div></div>`;
}

// ---------------------------------------------------------------- load

function tick() {
  $("ny").textContent = new Date().toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour12: false });
}

async function load() {
  try {
    const r = await fetch("lab.json?t=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    L = await r.json();
  } catch (e) {
    $("regb").innerHTML = empty(`The lab data could not be loaded (${esc(e.message)}).`);
    return;
  }
  $("built").textContent = L.built.replace("T", " ").slice(0, 16) + " UTC";
  renderStrip(); renderRegime(); renderMacro(); renderBreadth(); renderMarket(); renderStocks();
  renderStrategies(); renderRisk(); renderPortfolio(); renderActivity(); renderIntegrity();
}
tick(); setInterval(tick, 1000);
load();
