"use strict";
// AlphaForge Multi-Asset: renders site/multiasset.json. Everything here is research; nothing is traded.

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const num = (v) => typeof v === "number" && isFinite(v);
const fmt = (v, d = 2) => !num(v) ? "–" : v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1, sign = true) => !num(v) ? "–" : (sign && v > 0 ? "+" : "") + (v * 100).toFixed(d) + "%";
const cls = (v) => !num(v) || v === 0 ? "" : v > 0 ? "up" : "dn";
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const table = (head, rows) => `<table><thead><tr>${head.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table>`;
const note = (t) => `<p class="note">${t}</p>`;
const sub = (t) => `<div class="sub">${t}</div>`;
const SERIES = ["--amber", "--blue", "--aqua", "--violet", "--cmd", "--up", "--down", "--dim"];

let M = null, target = 0.10, base = null, picked = null, chart = null;

function tick() {
  $("ny").textContent = new Date().toLocaleTimeString("en-GB", { timeZone: "America/New_York", hour12: false });
}

// ---------------------------------------------------------------- strip

function renderStrip() {
  const S = Object.fromEntries(M.strategies.map((s) => [s.name, s]));
  const best = [...M.strategies].sort((a, b) => b.sharpe - a.sharpe)[0];
  const spy = S["S&P 500 (SPY)"], combo = S["50% S&P 500 + 50% trend following"], tf = S["Trend following (TSMOM, candidate)"];
  const tiles = [
    ["Test 9 verdict", `<b class="${M.passed ? "up" : "dn"}">${M.passed ? "passes" : "fails"}</b>`],
    ["Best Sharpe", `${esc(best.name.split(" (")[0])} ${fmt(best.sharpe)}`],
    ["S&P 500", `${pct(spy.cagr)} <small class="mut">DD ${pct(spy.maxdd, 0)}</small>`],
    ["Trend following", `${pct(tf.cagr)} <small class="mut">DD ${pct(tf.maxdd, 0)}</small>`],
    ["50/50 S&P + trend", `${pct(combo.cagr)} <small class="mut">DD ${pct(combo.maxdd, 0)}</small>`],
    ["Trend holding now", `${Object.keys(M.allocation).length} of 16 ETFs`],
    ["Data since", M.since.slice(0, 4)],
    ["As of", M.asof],
  ];
  $("lstrip").innerHTML = tiles.map(([n, v]) => `<div class="tile"><div class="n">${n}</div><div class="v">${v}</div></div>`).join("");
}

// ---------------------------------------------------------------- return-target simulator

function renderTarget() {
  const T = M.target, bases = Object.keys(T);
  if (!base) base = bases[0];
  const rows = bases.map((b) => {
    const g = T[b], hit = g.find((r) => r.cagr >= target), best = g.reduce((a, r) => r.cagr > a.cagr ? r : a, g[0]);
    const r = hit || best;
    return `<tr class="click${b === base ? " on" : ""}" data-b="${esc(b)}"><td class="l wrap">${esc(b)}</td>
      <td>${hit ? `<b>${fmt(r.L, 2)}×</b>` : `<b class="dn">never</b> <small class="mut">best ${pct(best.cagr)} at ${fmt(best.L, 2)}×</small>`}</td>
      <td class="${cls(r.cagr)}">${pct(r.cagr)}</td><td class="dn">${pct(r.maxdd, 0)}</td><td class="dn">${pct(r.worst_year, 0)}</td>
      <td>${pct(r.loss1, 0, false)}</td><td>${pct(r.loss3, 0, false)}</td><td>${r.loss5 == null ? "–" : pct(r.loss5, 0, false)}</td><td class="mut">${fmt(r.years, 0)}</td></tr>`;
  });
  const g = T[base];
  $("tgtb").innerHTML = `<div class="slider"><label for="tgtin">Target return a year: <b id="tgtv">${pct(target, 0, false)}</b></label>
      <input type="range" id="tgtin" min="0.04" max="0.30" step="0.01" value="${target}" aria-label="Target annual return"></div>
    ${table(["Portfolio", "Leverage needed", "Return a year", "Worst drawdown", "Worst year", "Down after 1 year", "after 3", "after 5", "Years of data"], rows)}
    ${note("Each portfolio levered from 0.5× to 3× (borrowing above 1× at T-bills + 2%, a realistic retail margin rate), on its whole history. \"Never\" means no leverage up to 3× reached the target: past about 2×, crashes cost more than leverage adds. \"Down after N years\" is the share of all N-year windows that ended with a loss. Click a portfolio to see every leverage level.")}
    ${sub(`${esc(base)}: every leverage level`)}
    ${table(["Leverage", "Return a year", "Volatility", "Sharpe", "Worst drawdown", "Worst year", "Down after 1 / 3 / 5 years"], g.map((r) =>
      `<tr${r.cagr >= target ? ' class="on"' : ""}><td>${fmt(r.L, 2)}×</td><td class="${cls(r.cagr)}">${pct(r.cagr)}</td><td>${pct(r.vol, 0, false)}</td><td>${fmt(r.sharpe)}</td>
       <td class="dn">${pct(r.maxdd, 0)}</td><td class="dn">${pct(r.worst_year, 0)}</td><td class="mut">${pct(r.loss1, 0, false)} / ${pct(r.loss3, 0, false)} / ${r.loss5 == null ? "–" : pct(r.loss5, 0, false)}</td></tr>`))}`;
  $("tgtin").oninput = (e) => { target = +e.target.value; renderTarget(); };
  $("tgtb").querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => { base = tr.dataset.b; renderTarget(); });
}

// ---------------------------------------------------------------- universe

function renderUniverse() {
  $("unidate").textContent = `as of ${M.asof}`;
  $("unib").innerHTML = table(["ETF", "Class", "1m", "3m", "12m", "Trend", "GARCH vol", "Trend weight now"], M.universe.map((u) =>
    `<tr title="${esc(u.name)}"><td class="s">${esc(u.sym)}</td><td class="l mut">${esc(u.class)}</td><td class="${cls(u.m1)}">${pct(u.m1)}</td>
     <td class="${cls(u.m3)}">${pct(u.m3)}</td><td class="${cls(u.m12)}">${pct(u.m12)}</td>
     <td class="${cls(u.trend)}">${u.trend == null ? "–" : fmt(u.trend, 2)}</td><td>${pct(u.vol, 0, false)}</td>
     <td>${u.weight ? `<b>${pct(u.weight, 1, false)}</b>` : '<span class="mut">cash</span>'}</td></tr>`))
    + note("Trend = average sign of the 1, 3, 6 and 12-month returns over T-bills (+1 all up, −1 all down). The trend-following strategy holds only positive trends, sized by GARCH volatility to a 10% target, at most 25% per ETF; the rest is cash. Shown for research; not traded.");
}

// ---------------------------------------------------------------- strategies, crises, test

function renderStrategies() {
  const S = M.strategies;
  if (!picked) picked = new Set(["Trend following (TSMOM, candidate)", "S&P 500 (SPY)", "50% S&P 500 + 50% trend following", "60/40 (SPY / IEF)"]);
  $("strb").innerHTML = table(["Strategy", "Return a year", "Vol", "Sharpe", "Sortino", "Worst drawdown", "Worst year", "Best year", "Up years", "Turnover / yr"],
    [...S].sort((a, b) => b.sharpe - a.sharpe).map((s) => `<tr class="click${picked.has(s.name) ? " on" : ""}" data-n="${esc(s.name)}">
      <td class="l">${esc(s.name)}</td><td class="${cls(s.cagr)}">${pct(s.cagr)}</td><td>${pct(s.vol, 1, false)}</td><td><b>${fmt(s.sharpe)}</b></td>
      <td>${fmt(s.sortino)}</td><td class="dn">${pct(s.maxdd)}</td><td class="dn">${pct(s.worst_year)}</td><td class="up">${pct(s.best_year)}</td>
      <td>${pct(s.pos_years, 0, false)}</td><td class="mut">${s.turnover == null ? "–" : fmt(s.turnover, 1) + "×"}</td></tr>`))
    + note(`From ${M.since.slice(0, 4)}, monthly rebalancing at a close and trading at the next one, 3 bp per unit of turnover, cash at T-bills. Total returns (dividends included).`);
  $("strb").querySelectorAll("tr.click").forEach((tr) => tr.onclick = () => {
    const n = tr.dataset.n; picked.has(n) ? picked.delete(n) : picked.add(n); renderStrategies();
  });
  if (chart) chart.remove();
  chart = LightweightCharts.createChart($("strc"), { autoSize: true,
    layout: { background: { color: css("--panel") }, textColor: css("--dim"), fontFamily: css("--f"), fontSize: 11, attributionLogo: false },
    grid: { vertLines: { color: "#15100b" }, horzLines: { color: "#15100b" } }, rightPriceScale: { borderColor: css("--rule"), mode: 1 },
    timeScale: { borderColor: css("--rule") } });
  const legend = [];
  [...picked].forEach((n, i) => {
    const c = M.curves[n], col = css(SERIES[i % SERIES.length]);
    if (!c) return;
    chart.addLineSeries({ color: col, lineWidth: 2, priceLineVisible: false, lastValueVisible: true })
      .setData(c.dates.map((d, j) => ({ time: d, value: c.v[j] })));
    legend.push(`<span><i style="background:${col}"></i>${esc(n)}</span>`);
  });
  $("strleg").innerHTML = legend.join("") + "<span>growth of 1, log scale</span>";
  chart.timeScale().fitContent();
}

function renderCrises() {
  $("crib").innerHTML = table(["Strategy", ...M.crises.map(esc)], M.strategies.map((s) =>
    `<tr><td class="l">${esc(s.name)}</td>${M.crises.map((c) => `<td class="${cls(s.crises[c])}">${pct(s.crises[c])}</td>`).join("")}</tr>`))
    + note("Return during each stock-market crisis window. Positive numbers are where a strategy protected the portfolio.");
}

function renderTest() {
  const C = M.corr;
  $("tstb").innerHTML = table(["Rule", "Result", "Evidence"], M.rules.map(([n, ok, e]) =>
    `<tr><td class="l">${esc(n)}</td><td>${ok ? '<b class="up">pass</b>' : '<b class="dn">fail</b>'}</td><td class="wrap mut">${esc(e)}</td></tr>`))
    + note(`Verdict: <b class="${M.passed ? "up" : "dn"}">${M.passed ? "passes: the 50/50 mix is proposed for the paper account, live only with your approval" : "fails, so nothing changes in trading"}</b>. Rules were committed before the run (docs/PREREGISTRATION_9.md).`)
    + sub("Correlation of monthly returns")
    + table(["", ...C.names.map((n) => esc(n.split(" (")[0].slice(0, 14)))], C.m.map((row, i) => `<tr><td class="l">${esc(C.names[i].split(" (")[0])}</td>${
      row.map((v) => `<td style="background:${v >= 0 ? `rgba(255,159,28,${0.06 + 0.6 * Math.abs(v)})` : `rgba(74,158,255,${0.06 + 0.6 * Math.abs(v)})`}">${fmt(v)}</td>`).join("")}</tr>`));
}

async function load() {
  try {
    const r = await fetch("multiasset.json?t=" + Date.now());
    if (!r.ok) throw new Error("HTTP " + r.status);
    M = await r.json();
  } catch (e) {
    $("tgtb").innerHTML = `<p class="empty">The data could not be loaded (${esc(e.message)}).</p>`;
    return;
  }
  $("built").textContent = M.built.replace("T", " ").slice(0, 16) + " UTC";
  renderStrip(); renderTarget(); renderUniverse(); renderStrategies(); renderCrises(); renderTest();
}
tick(); setInterval(tick, 1000);
load();
