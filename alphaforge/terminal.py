"""Builds site/data.json: everything the static terminal front end renders."""
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import backtest, metrics, signals
from .backtest import Config
from .data import MARKET_STRIP


def _clean(o):
    """JSON-safe: NaN/inf -> null, numpy scalars -> Python, floats rounded."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(o) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


def quote(raw, sym):
    c = raw["Close"][sym].dropna()
    if len(c) < 2:
        return None
    h, lo, v = raw["High"][sym].dropna(), raw["Low"][sym].dropna(), raw["Volume"][sym].dropna()
    prior_year = c[c.index.year < c.index[-1].year]
    return {
        "last": c.iloc[-1], "chg": c.iloc[-1] - c.iloc[-2], "pct": c.iloc[-1] / c.iloc[-2] - 1,
        "hi52": h.iloc[-252:].max(), "lo52": lo.iloc[-252:].min(),
        "ytd": c.iloc[-1] / prior_year.iloc[-1] - 1 if len(prior_year) else None,
        "vol20": v.iloc[-20:].mean() if len(v) else None,
        "spark": c.iloc[-30:].round(4).tolist(), "date": str(c.index[-1].date()),
    }


def ohlc(raw, sym, n=260):
    df = pd.DataFrame({k: raw[k][sym] for k in ["Open", "High", "Low", "Close", "Volume"]}).dropna().iloc[-n:]
    return [[str(i.date()), *np.round(r[:4], 4), int(r[4])] for i, r in zip(df.index, df.values)]


def build(raw, prices, bench, lc, broker, state_dir, out_path):
    strat = Config(**lc["strategy"])
    px = prices.iloc[-1]
    rets = prices.pct_change()
    universe = list(prices.columns)

    # Research: full-history backtest with the live configuration.
    res = backtest.run_backtest(prices, strat, bench)
    live = res.weights.abs().sum(axis=1) > 0
    t0 = live.idxmax()
    r, b = res.returns.loc[t0:], res.benchmark.loc[t0:]
    weekly = pd.DataFrame({"s": (1 + r).cumprod(), "b": (1 + b).cumprod(),
                           "dd": metrics.drawdown(r)}).resample("W-FRI").last()
    mt = metrics.monthly_table(r)

    # Signals as of the last close.
    scores = signals.factor_scores(prices)
    alpha = signals.combine(scores, strat.factor_weights)
    tgt = backtest.targets_at(alpha, rets, len(prices) - 1, strat)
    sig = [{"sym": s, "alpha": alpha.iloc[-1][s], "target": tgt[s],
            **{f: sc.iloc[-1][s] for f, sc in scores.items()}} for s in universe]
    sig.sort(key=lambda x: -(x["alpha"] if x["alpha"] == x["alpha"] else -9))

    # Book and account.
    equity = broker.equity(px)
    pos = broker.positions()
    book = []
    for s, p in pos.items():
        last = float(px.get(s, np.nan))
        mv = p["qty"] * last
        book.append({"sym": s, "qty": p["qty"], "avg": p["avg_cost"], "last": last, "mv": mv,
                     "weight": mv / equity, "upl": (last - p["avg_cost"]) * p["qty"],
                     "upl_pct": (last - p["avg_cost"]) * p["qty"] / abs(p["qty"] * p["avg_cost"]) if p["avg_cost"] else None})
    book.sort(key=lambda x: -abs(x["mv"]))
    w = pd.Series({x["sym"]: x["weight"] for x in book}, dtype=float).reindex(universe).fillna(0)

    eq_path = f"{state_dir}/equity.csv"
    curve = pd.read_csv(eq_path, index_col=0)["equity"] if os.path.exists(eq_path) else pd.Series(dtype=float)
    meta = json.load(open(f"{state_dir}/meta.json")) if os.path.exists(f"{state_dir}/meta.json") else {}
    blotter = []
    if os.path.exists(f"{state_dir}/orders.jsonl"):
        with open(f"{state_dir}/orders.jsonl") as f:
            blotter = [json.loads(line) for line in f.readlines()[-150:]][::-1]

    # Risk on the current book.
    hist = rets.iloc[-63:].fillna(0)
    cov = hist.cov().values
    ex_ante = math.sqrt(max(float(w.values @ cov @ w.values), 0) * 252)
    br = bench.pct_change().reindex(rets.index).iloc[-252:]
    betas = rets.iloc[-252:].apply(lambda c: c.cov(br) / br.var())
    expo = {f: float((w * sc.iloc[-1].fillna(0)).sum()) for f, sc in scores.items()}

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "as_of": str(prices.index[-1].date()),
        "status": {"broker": lc["broker"], "live_money": bool(lc["live_money"]) and lc["broker"] == "alpaca",
                   "mode": strat.mode, "halted": meta.get("halted", False),
                   "last_signal": meta.get("last_signal"),
                   "pending": (meta.get("pending") or {}).get("signal_date"),
                   "rebalance": "month-end", "target_vol": strat.target_vol},
        "strip": {k: quote(raw, v) for k, v in MARKET_STRIP.items() if v in raw["Close"]},
        "quotes": {s: quote(raw, s) for s in universe + ["SPY"]},
        "ohlc": {s: ohlc(raw, s) for s in universe + ["SPY"]},
        "backtest": {
            "summary": metrics.summary(res), "start": str(t0.date()),
            "dates": [str(i.date()) for i in weekly.index], "strategy": weekly["s"].tolist(),
            "bench": weekly["b"].tolist(), "drawdown": weekly["dd"].tolist(),
            "monthly": {"years": [int(y) for y in mt.index], "cols": list(mt.columns),
                        "values": mt.values.tolist()},
        },
        "signals": sig,
        "account": {"equity": equity, "cash": getattr(broker, "cash", None),
                    "high_water": meta.get("high_water"),
                    "dates": list(curve.index.astype(str)), "curve": curve.tolist()},
        "book": book,
        "blotter": blotter,
        "risk": {"ex_ante_vol": ex_ante, "beta": float((w * betas.fillna(0)).sum()),
                 "gross": float(w.abs().sum()), "net": float(w.sum()),
                 "var95": 1.645 * ex_ante / math.sqrt(252) * equity,
                 "exposures": expo, "corr_syms": universe,
                 "corr": hist.corr().round(2).values.tolist()},
    }
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(_clean(data), f, separators=(",", ":"), allow_nan=False)
