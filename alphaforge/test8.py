"""Pre-registered test 8 (docs/PREREGISTRATION_8.md): risk-targeted SPY against buying and holding it.

    python -m alphaforge.test8      # writes docs/RESEARCH_8.md

R1: w = min(1.5, 0.20 / GARCH vol). R2: R1 above the 200-day average, half of it (at most 1.0) below.
Decided at the close, traded at the next close; the weight only changes when the target moves by more than 0.10.
"""
import json
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from . import models
from .data import download, risk_free

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TARGET_VOL, MAX_LEV, BAND, COST, SPREAD = 0.20, 1.5, 0.10, 2 / 1e4, 0.01
START = "1998-01-01"
ERAS = [(1998, 2007), (2008, 2015), (2016, 2100)]


def target_weights(spy, garch, trend_filter):
    w = (TARGET_VOL / garch).clip(upper=MAX_LEV)
    if trend_filter:
        below = spy < spy.rolling(200).mean()
        w = w.where(~below, (w / 2).clip(upper=1.0))
    return w


def banded(target, band=BAND):
    """Hold the weight until the target has moved more than `band` away."""
    out, cur = [], np.nan
    for x in target.values:
        if np.isfinite(x) and (not np.isfinite(cur) or abs(x - cur) > band):
            cur = x
        out.append(cur)
    return pd.Series(out, index=target.index)


def simulate(w, ret, rf):
    """Daily returns: w decided at close t-1 earns SPY's return at t; cash earns rf; borrowing costs rf + 1%."""
    held = w.shift(1)
    borrow = (held - 1).clip(lower=0)
    cash = (1 - held).clip(lower=0)
    r = held * ret + cash * rf - borrow * (rf + SPREAD / 252) - held.diff().abs().fillna(0) * COST
    return r.dropna(), held.diff().abs().fillna(0)


def stats(r, rf):
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    ex = r - rf.reindex(r.index).fillna(0)
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * math.sqrt(252), "sharpe": ex.mean() / ex.std() * math.sqrt(252),
            "maxdd": (eq / eq.cummax() - 1).min(), "worst_year": float((1 + r).resample("YE").prod().sub(1).min()),
            "best_year": float((1 + r).resample("YE").prod().sub(1).max())}


def rolling_wins(r, b, years=10):
    """Share of rolling 10-year windows (monthly steps) in which r's CAGR beats b's."""
    m = (1 + r).resample("ME").prod(), (1 + b).resample("ME").prod()
    n = years * 12
    wins = [(m[0].iloc[i:i + n].prod() > m[1].iloc[i:i + n].prod()) for i in range(0, len(m[0]) - n + 1)]
    return float(np.mean(wins)), len(wins)


def run():
    raw = download(["SPY", "^IRX"], "1993-01-01")
    spy = raw["Close"]["SPY"].dropna()
    rf = risk_free(raw, 252).reindex(spy.index).fillna(0)
    ret = spy.pct_change().fillna(0)
    garch = models.garch_filtered_vol(np.log(spy).diff(), start_year=1997)
    res = {}
    bench = ret.loc[START:]
    res["SPY buy and hold"] = {"r": bench, "turnover": 0.0}
    for name, tf in (("R1 risk-targeted", False), ("R2 risk-targeted + trend filter", True)):
        w = banded(target_weights(spy, garch, tf))
        r, turn = simulate(w, ret, rf)
        r = r.loc[START:]
        res[name] = {"r": r, "turnover": float(turn.loc[START:].sum() / (len(r) / 252)), "w": w.loc[START:],
                     "avg_w": float(w.loc[START:].mean()), "levered": float((w.loc[START:] > 1).mean())}
    b = stats(bench, rf)
    for name, v in res.items():
        v["stats"] = stats(v["r"], rf)
        v["eras"] = {f"{y0}–{str(y1)[2:] if y1 < 2100 else 'now'}": stats(v["r"][(v["r"].index.year >= y0) & (v["r"].index.year <= y1)], rf)["cagr"]
                     for y0, y1 in ERAS}
        if name != "SPY buy and hold":
            s = v["stats"]
            win, n = rolling_wins(v["r"], bench)
            era_wins = sum(v["eras"][k] > res["SPY buy and hold"]["eras"][k] for k in v["eras"]) if "eras" in res["SPY buy and hold"] else None
            v["rules"] = [
                ("1. Higher return", s["cagr"] > b["cagr"], f"CAGR {s['cagr']:.1%} vs SPY {b['cagr']:.1%}"),
                ("2. Consistently (rolling 10 years)", win >= 0.70, f"beat SPY in {win:.0%} of {n} windows"),
                ("3. In each era", None, ""),
                ("4. Not a worse crash", s["maxdd"] >= b["maxdd"], f"max drawdown {s['maxdd']:.1%} vs SPY {b['maxdd']:.1%}"),
                ("5. Not just leverage", s["sharpe"] >= b["sharpe"], f"Sharpe {s['sharpe']:.2f} vs SPY {b['sharpe']:.2f}"),
            ]
    for name, v in res.items():
        if "rules" in v:
            wins = sum(v["eras"][k] > res["SPY buy and hold"]["eras"][k] for k in v["eras"])
            v["rules"][2] = ("3. In each era", wins >= 2, ", ".join(f"{k} {v['eras'][k]:.1%} vs {res['SPY buy and hold']['eras'][k]:.1%}" for k in v["eras"]))
            v["passed"] = all(x[1] for x in v["rules"])
    return res


def main():
    res = run()
    L = ["# Research report 8: beating the S&P 500 by taking more risk, with control", "",
         f"Generated {date.today()} by `python -m alphaforge.test8`. Rules committed before the run: "
         "[PREREGISTRATION_8.md](PREREGISTRATION_8.md). This is a choice to carry more market risk, managed by GARCH "
         "volatility and a trend filter. It is not a forecasting edge.", "",
         f"SPY from {START[:4]}, daily, net of 2 bp per unit of turnover; borrowing at T-bills + 1%; cash earns T-bills.", "",
         "| | CAGR | Vol | Sharpe | Max DD | Worst year | Best year | Avg weight | Days levered | Turnover / yr |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for name, v in res.items():
        s = v["stats"]
        L.append(f"| {name} | {s['cagr']:.1%} | {s['vol']:.1%} | {s['sharpe']:.2f} | {s['maxdd']:.1%} | {s['worst_year']:.1%} | "
                 f"{s['best_year']:.1%} | {v.get('avg_w', 1.0):.2f} | {v.get('levered', 0.0):.0%} | {v['turnover']:.1f}× |")
    L.append("")
    for name, v in res.items():
        if "rules" not in v:
            continue
        L += [f"## {name}: {'pass' if v['passed'] else 'fail'}", "", "| Rule | Result | Evidence |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if ok else '**fail**'} | {e} |" for n, ok, e in v["rules"]] + [""]
    winners = [n for n, v in res.items() if v.get("passed")]
    if len(winners) > 1:
        winners = sorted(winners, key=lambda n: -res[n]["stats"]["maxdd"])
    L += ["## Decision", "", (f"**{winners[0]}** passes: it goes live on the paper account as the equity sleeve's strategy."
                              if winners else "Neither passes: nothing changes."), ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_8.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(json.dumps({n: v.get("passed") for n, v in res.items()}))


if __name__ == "__main__":
    main()
