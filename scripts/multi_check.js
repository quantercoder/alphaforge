// Runs site/multiasset.js in Node against site/multiasset.json with a stub DOM; fails on errors, "undefined" or "NaN".
//   node scripts/multi_check.js site/multiasset.js site/multiasset.json
const fs = require("fs"), vm = require("vm");
const [, , js, data] = process.argv;
const els = {};
const mk = (id) => ({ id, innerHTML: "", textContent: "", style: {}, dataset: {}, querySelectorAll: () => [] });
const chainable = () => new Proxy(function () {}, { get: () => chainable(), apply: () => chainable() });
const ctx = { document: { getElementById: (id) => (els[id] ||= mk(id)), documentElement: {} }, console, setInterval: () => 0,
  getComputedStyle: () => ({ getPropertyValue: () => "#000" }), LightweightCharts: { createChart: () => chainable() },
  Date, Math, JSON, Object, Array, Set, Number, String, Promise, isFinite,
  fetch: async () => ({ ok: true, json: async () => JSON.parse(fs.readFileSync(data, "utf8")) }) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(js, "utf8") + `;globalThis.__t = { get M() { return M; }, renderTarget, setT: (t, b) => { target = t; base = b; } };`, ctx);
(async () => {
  await new Promise((r) => setImmediate(r)); await new Promise((r) => setImmediate(r));
  const T = ctx.__t, bad = [];
  if (!T.M) throw new Error("data not loaded");
  const scan = (w) => { const h = Object.values(els).map((e) => e.innerHTML + e.textContent).join(""); if (/undefined|NaN/.test(h)) bad.push(w + ": " + (h.match(/.{60}(undefined|NaN).{30}/) || [""])[0]); };
  scan("load");
  for (const t of [0.05, 0.12, 0.2, 0.3]) for (const b of Object.keys(T.M.target)) { T.setT(t, b); T.renderTarget(); scan(`target ${t} ${b}`); }
  if (bad.length) { console.log("FAIL", bad.slice(0, 5)); process.exit(1); }
  console.log("ok multi-asset:", Object.keys(els).length, "elements rendered");
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
