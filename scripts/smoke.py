"""End-to-end check on real data without touching the broker.

    python scripts/smoke.py OUT_DIR

Downloads today's data, runs two simulated trading days with live.json's settings (broker switched to
the simulator), and builds both terminal data files into OUT_DIR/site. Then check the pages with
    node scripts/fe_check.js site/terminal.js OUT_DIR/site/data.json equity
"""
import json
import os
import shutil
import sys

import pandas as pd

REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, REPO)
from alphaforge import terminal  # noqa: E402
from alphaforge.data import MARKET_STRIP, download, load_prices  # noqa: E402
from alphaforge.live import load_config, load_crypto, make_broker, run  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
cfg = json.load(open(os.path.join(REPO, "live.json")))
cfg["broker"] = "sim"
json.dump(cfg, open(os.path.join(out, "live_sim.json"), "w"))
lc = load_config(os.path.join(out, "live_sim.json"))

state, site = os.path.join(out, "state"), os.path.join(out, "site")
shutil.rmtree(state, ignore_errors=True)
core = lc["universe"] + ["SPY", "^IRX"] + list(MARKET_STRIP.values())
raw = download(core, lc["history_start"])
extra = [s for s in lc["watchlist"] if s not in core]
raw = pd.concat([raw, download(extra, (pd.Timestamp.now() - pd.Timedelta(days=800)).strftime("%Y-%m-%d"))], axis=1)
prices, bench = load_prices(lc["universe"], None, raw=raw)
cp, craw = load_crypto(lc) if lc["crypto"]["enabled"] else (None, None)
print("day 1", run(lc, prices.iloc[:-1], state, make_broker(lc, state), crypto_prices=None if cp is None else cp.iloc[:-1])["events"])
r = run(lc, prices, state, make_broker(lc, state), crypto_prices=cp)
print("day 2", r["events"], "fills", len(r["fills"]), "alerts", r["alerts"])
terminal.build(raw, prices, bench, lc, make_broker(lc, state), state, site, craw=craw, cprices=cp)
for f in ("data.json", "crypto.json"):
    if os.path.exists(os.path.join(site, f)):
        d = json.load(open(os.path.join(site, f)))
        print(f, "as of", d["as_of"], "| positions", len(d["book"]), "| forecasts", len((d.get("forecast") or {}).get("rows", [])))
