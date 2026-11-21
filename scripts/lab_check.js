// Runs site/lab.js in Node against site/lab.json with a stub DOM; renders every panel and tab and fails on
// an exception or on "undefined"/"NaN" in the output.   node scripts/lab_check.js site/lab.js site/lab.json
const fs = require("fs"), vm = require("vm");
const [, , js, data] = process.argv;
const els = {};
const mk = (id) => ({ id, innerHTML: "", textContent: "", style: {}, dataset: {},
  querySelectorAll(sel) {
    if (sel === "button") return [...this.innerHTML.matchAll(/data-k="([^"]+)"/g)].map((m) => ({ dataset: { k: m[1] } }));
    if (sel === "tr.click") return [...this.innerHTML.matchAll(/data-n="([^"]+)"/g)].map((m) => ({ dataset: { n: m[1] } }));
    return [];
  } });
const chainable = () => new Proxy(function () {}, { get: () => chainable(), apply: () => chainable() });
const ctx = { document: { getElementById: (id) => (els[id] ||= mk(id)), documentElement: {} }, console, setInterval: () => 0,
  getComputedStyle: () => ({ getPropertyValue: () => "#000" }), LightweightCharts: { createChart: () => chainable() },
  Date, Math, JSON, Object, Array, Set, Number, String, Promise, isFinite,
  fetch: async () => ({ ok: true, json: async () => JSON.parse(fs.readFileSync(data, "utf8")) }) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(js, "utf8") + `
;globalThis.__t = { get L() { return L; }, renderMarket, renderStocks, renderPortfolio, renderStrategies,
  set: (k, v) => { if (k === "h") horizon = v; if (k === "s") stab = v; if (k === "p") ptab = v; } };`, ctx);
(async () => {
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  const T = ctx.__t, bad = [];
  if (!T.L) throw new Error("lab.json not loaded");
  const scan = (w) => {
    const html = Object.values(els).map((e) => e.innerHTML + e.textContent).join("");
    if (/undefined|NaN/.test(html)) bad.push(w + ": " + (html.match(/.{60}(undefined|NaN).{30}/) || [""])[0]);
  };
  scan("load");
  for (const h of Object.keys(T.L.forecast_market.horizons)) { T.set("h", h); T.renderMarket(); scan("horizon " + h); }
  for (const s of ["top", "low", "models", "rules"]) { T.set("s", s); T.renderStocks(); scan("stocks " + s); }
  for (const p of ["now", "weights", "bt"]) { T.set("p", p); T.renderPortfolio(); scan("portfolio " + p); }
  T.renderStrategies(); scan("strategies");
  if (bad.length) { console.log("FAIL", bad); process.exit(1); }
  console.log("ok lab:", Object.keys(els).length, "elements rendered");
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
