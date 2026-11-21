// Runs site/terminal.js in Node against a built data file with a stub DOM, renders every tab and runs
// every command, and fails on an exception or on "undefined"/"NaN" in the output.
//   node scripts/fe_check.js site/terminal.js path/to/data.json equity|crypto
const fs = require("fs"), vm = require("vm");
const [, , siteJs, dataFile, kind] = process.argv;
const els = {};
const mkEl = (id) => ({
  id, innerHTML: "", textContent: "", value: "", style: {}, className: "", dataset: {}, hidden: false, checked: false,
  classList: { add() {}, remove() {} }, setAttribute() {}, removeAttribute() {}, addEventListener() {}, showModal() {},
  scrollIntoView() {}, querySelector: () => null, offsetWidth: 1,
  querySelectorAll(sel) {
    if (sel !== "button") return [];
    return [...this.innerHTML.matchAll(/data-k="([^"]+)"/g)].map((m) => ({ dataset: { k: m[1] }, onclick: null, setAttribute() {} }));
  },
});
const document = {
  getElementById: (id) => (els[id] ||= mkEl(id)), querySelector: () => null, addEventListener() {},
  documentElement: {}, activeElement: { tagName: "BODY" },
};
const chainable = () => new Proxy(function () {}, { get: () => chainable(), apply: () => chainable() });
const ctx = {
  window: { PAGE: { kind, data: "x" } }, document, console, setInterval: () => 0, setTimeout: () => 0,
  getComputedStyle: () => ({ getPropertyValue: () => "#000" }), LightweightCharts: { createChart: () => chainable() },
  ResizeObserver: class { observe() {} }, WebSocket: class { send() {} close() {} },
  localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, matchMedia: () => ({ matches: true }),
  history: { replaceState() {} }, location: { hash: "", pathname: "/index.html" }, addEventListener() {},
  CSS: { escape: (s) => s }, Intl, Date, Math, JSON, Object, Array, Set, Number, String, Promise, Proxy,
  fetch: async () => ({ ok: true, json: async () => JSON.parse(fs.readFileSync(dataFile, "utf8")) }),
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(siteJs, "utf8") + `
;globalThis.__t = { get D() { return D; }, renderPerf, renderRisk, renderBook, renderBltr, renderSig, renderPre, renderDH, renderAud,
  renderFc, renderGP, loadSym, run,
  set: (k, v) => { if (k === "ptab") ptab = v; if (k === "rtab") rtab = v; if (k === "btab") btab = v; if (k === "otab") otab = v; if (k === "stab") stab = v; if (k === "atab") atab = v; } };`, ctx);
(async () => {
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  const T = ctx.__t;
  if (!T.D) throw new Error("data not loaded");
  const tabs = { ptab: ["growth", "dd", "attr", "sleeve", "compare"], rtab: ["sum", "model", "stress", "liq", "lim"], btab: ["pos", "exp", "pend"],
    otab: ["ord", "tca"], stab: ["scores", "ic", "corr", "cap"], atab: ["alerts", "audit", "ctl"] };
  const render = { ptab: T.renderPerf, rtab: T.renderRisk, btab: T.renderBook, otab: T.renderBltr, stab: T.renderSig, atab: T.renderAud };
  const bad = [];
  const scan = (where) => {
    const html = Object.values(els).map((e) => e.innerHTML).join("");
    if (/undefined|NaN/.test(html)) bad.push(where + ": " + (html.match(/.{60}(undefined|NaN).{40}/) || [""])[0]);
  };
  for (const [k, vs] of Object.entries(tabs)) for (const v of vs) { T.set(k, v); render[k](); scan(`${k}=${v}`); }
  T.renderPre(); T.renderDH(); T.renderFc(); scan("panels");
  if (T.D.forecast) for (const r of T.D.forecast.rows.slice(0, 3)) { T.loadSym(r.sym); scan("chart " + r.sym); }
  for (const c of ["ATTR", "FACT", "STRESS", "LIQ", "LIM", "EXP", "TCA", "IC", "PREV", "DATA", "AUD", "FCST", "HELP"]) T.run(c);
  if (bad.length) { console.log("FAIL", kind, bad); process.exit(1); }
  console.log("ok", kind, T.D.forecast ? `${T.D.forecast.rows.length} forecasts` : "no forecasts");
})().catch((e) => { console.error("FAIL", e); process.exit(1); });
