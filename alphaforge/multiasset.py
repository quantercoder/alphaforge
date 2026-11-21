"""Multi-asset strategies (pre-registered test 9) and the return-target simulator.

    python -m alphaforge.multiasset      # writes site/multiasset.json and docs/RESEARCH_9.md

16 ETFs across six asset classes; every strategy rebalances at a month-end close, trades at the next close, pays
3 bp per unit of turnover and earns T-bills on cash. Weights drift with prices between rebalances.
"""
import json
import math
import os
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from .data import download, risk_free
from .terminal import _write
from .vol import garch_vol

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UNIVERSE = {
    "SPY": ("US stocks", "S&P 500"), "IWM": ("US stocks", "Russell 2000 small caps"),
    "EFA": ("International stocks", "Developed markets"), "EEM": ("International stocks", "Emerging markets"),
    "SHY": ("Government bonds", "Treasuries 1–3 years"), "IEF": ("Government bonds", "Treasuries 7–10 years"),
    "TLT": ("Government bonds", "Treasuries 20+ years"), "TIP": ("Government bonds", "Inflation-linked Treasuries"),
    "LQD": ("Credit", "Investment-grade corporate"), "HYG": ("Credit", "High-yield corporate"),
    "VNQ": ("Real assets", "US real estate (REITs)"), "GLD": ("Real assets", "Gold"), "SLV": ("Real assets", "Silver"),
    "DBC": ("Real assets", "Commodities"), "UUP": ("Currencies", "US dollar"), "FXY": ("Currencies", "Japanese yen"),
}
COST, TARGET_VOL, CAP = 3 / 1e4, 0.10, 0.25
TEST_FROM = "2005-01-01"
CRISES = [("Global financial crisis", "2007-10-09", "2009-03-09"), ("2011 euro crisis", "2011-07-01", "2011-09-30"),
          ("Q4 2018 selloff", "2018-10-01", "2018-12-24"), ("COVID crash", "2020-02-19", "2020-03-23"),
          ("2022 rates shock", "2022-01-03", "2022-12-30")]
PERIODS = [(2005, 2012), (2013, 2019), (2020, 2100)]


# ---------------------------------------------------------------- simulation

def simulate(rets, rf, decide, dates):
    """Daily returns of a strategy that decides target weights at each date in `dates` (a close) with
    decide(t) -> Series, and trades them at the next close."""
    idx, cols = rets.index, list(rets.columns)
    R = rets.fillna(0).values
    w = np.zeros(len(cols))
    out, turn, pending = np.zeros(len(idx)), np.zeros(len(idx)), None
    dset = set(dates)
    for i, t in enumerate(idx):
        g = float(w @ R[i]) + (1 - w.sum()) * rf.iloc[i]
        w = w * (1 + R[i]) / (1 + g) if 1 + g > 0 else w * 0
        if pending is not None:
            tgt = pending.reindex(cols).fillna(0).values
            turn[i] = np.abs(tgt - w).sum()
            g -= turn[i] * COST
            w, pending = tgt, None
        out[i] = g
        if t in dset:
            pending = decide(t)
    return pd.Series(out, index=idx), pd.Series(turn, index=idx)


def month_ends(idx, start):
    s = pd.Series(idx, index=idx)
    me = s.groupby(idx.to_period("M")).last()
    return [d for d in me.values if pd.Timestamp(d) >= pd.Timestamp(start)]


def cov_matrix(rets, names, shrink=0.3):
    R = rets[names].iloc[-756:]
    g = garch_vol(R, 21).fillna(R.iloc[-63:].std()).values * math.sqrt(252)
    C = R.iloc[-252:].fillna(0).corr().fillna(0).values
    C = (1 - shrink) * C + shrink * np.eye(len(names))
    np.fill_diagonal(C, 1)
    return g[:, None] * C * g[None, :], g


# ---------------------------------------------------------------- strategies

def tsmom(px, rets, rf_cum):
    """M1: average sign of 1/3/6/12-month excess returns, long or cash, inverse-volatility sized, portfolio at 10%
    volatility, at most 25% per ETF and 100% in total."""
    def decide(t):
        i = px.index.get_loc(t)
        avail = [c for c in px.columns if px[c].iloc[:i + 1].notna().sum() >= 273]
        if not avail:
            return pd.Series(dtype=float)
        sig = {}
        for c in avail:
            s = []
            for m in (21, 63, 126, 252):
                ex = px[c].iloc[i] / px[c].iloc[i - m] - 1 - (rf_cum.iloc[i] / rf_cum.iloc[i - m] - 1)
                s.append(np.sign(ex))
            sig[c] = max(0.0, float(np.mean(s)))
        names = [c for c in avail if sig[c] > 0]
        if not names:
            return pd.Series(dtype=float)
        S, g = cov_matrix(rets.iloc[:i + 1], names)
        w = np.array([sig[c] * TARGET_VOL / g[k] for k, c in enumerate(names)]) / len(avail)
        w *= TARGET_VOL / math.sqrt(max(w @ S @ w, 1e-12))
        w = np.minimum(w, CAP)
        if w.sum() > 1:
            w /= w.sum()
        return pd.Series(w, index=names)
    return decide


def risk_parity(rets, names=("SPY", "EFA", "EEM", "IEF", "TLT", "TIP", "GLD", "DBC")):
    def decide(t):
        i = rets.index.get_loc(t)
        avail = [c for c in names if rets[c].iloc[:i + 1].notna().sum() >= 273]
        if not avail:
            return pd.Series(dtype=float)  # not enough history yet: cash
        S, _ = cov_matrix(rets.iloc[:i + 1], avail)
        w = np.full(len(avail), 1 / len(avail))
        for _ in range(500):  # equal risk contribution, fixed-point iteration
            rc = w * (S @ w)
            w = w * (rc.mean() / np.maximum(rc, 1e-12)) ** 0.5
            w /= w.sum()
        return pd.Series(w, index=avail)
    return decide


def dual_momentum(px, rf_cum):
    def decide(t):
        i = px.index.get_loc(t)
        if i < 252 or px["EFA"].iloc[:i + 1].notna().sum() < 253:
            return pd.Series(dtype=float)
        r = lambda c: px[c].iloc[i] / px[c].iloc[i - 252] - 1
        tb = rf_cum.iloc[i] / rf_cum.iloc[i - 252] - 1
        if r("SPY") > tb:
            return pd.Series({("SPY" if r("SPY") >= r("EFA") else "EFA"): 1.0})
        return pd.Series({"IEF": 1.0})
    return decide


def fixed(weights):
    return lambda t: pd.Series(weights)


def equal_weight(px):
    def decide(t):
        i = px.index.get_loc(t)
        avail = [c for c in px.columns if px[c].iloc[:i + 1].notna().sum() >= 273]
        return pd.Series(1 / len(avail), index=avail) if avail else pd.Series(dtype=float)
    return decide


# ---------------------------------------------------------------- statistics

def perf(r, rf):
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    ex = r - rf.reindex(r.index).fillna(0)
    down = np.sqrt((ex.clip(upper=0) ** 2).mean())
    yr = (1 + r).resample("YE").prod() - 1
    return {"cagr": eq.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * math.sqrt(252), "sharpe": ex.mean() / ex.std() * math.sqrt(252),
            "sortino": ex.mean() / down * math.sqrt(252) if down > 0 else None, "maxdd": (eq / eq.cummax() - 1).min(),
            "worst_year": float(yr.min()), "best_year": float(yr.max()), "pos_years": float((yr > 0).mean())}


def crisis_returns(r):
    return {n: float((1 + r.loc[a:b]).prod() - 1) for n, a, b in CRISES}


def loss_odds(r, years):
    """Share of all rolling windows of `years` (daily steps, monthly sampled) that ended with a loss."""
    m = (1 + r).resample("ME").prod()
    n = int(years * 12)
    if len(m) <= n:
        return None
    vals = [m.iloc[i:i + n].prod() - 1 for i in range(len(m) - n + 1)]
    return float(np.mean(np.array(vals) < 0))


def levered(r, rf, L, spread=0.02):
    """Daily returns at leverage L (borrowing at T-bills + 2% above 1x; below 1x the rest earns T-bills)."""
    rf = rf.reindex(r.index).fillna(0)
    return L * r - (L - 1) * rf - max(L - 1, 0) * spread / 252


# ---------------------------------------------------------------- build

def main():
    tick = list(UNIVERSE)
    raw = download(tick + ["^IRX"], "2003-01-01")
    px = raw["Close"][tick].ffill(limit=5)
    rets = px.pct_change(fill_method=None)
    rf = risk_free(raw, 252).reindex(px.index).fillna(0)
    rf_cum = (1 + rf).cumprod()
    dates = month_ends(px.index, "2004-01-01")
    strat = {
        "Trend following (TSMOM, candidate)": tsmom(px, rets, rf_cum),
        "Risk parity": risk_parity(rets),
        "Dual momentum": dual_momentum(px, rf_cum),
        "60/40 (SPY / IEF)": fixed({"SPY": 0.6, "IEF": 0.4}),
        "Permanent portfolio": fixed({"SPY": 0.25, "TLT": 0.25, "GLD": 0.25, "SHY": 0.25}),
        "Equal weight, all ETFs": equal_weight(px),
        "S&P 500 (SPY)": fixed({"SPY": 1.0}),
    }
    R, T = {}, {}
    for name, fn in strat.items():
        r, t = simulate(rets, rf, fn, dates)
        R[name], T[name] = r.loc[TEST_FROM:], t.loc[TEST_FROM:]
    cand, spy, sixty = R["Trend following (TSMOM, candidate)"], R["S&P 500 (SPY)"], R["60/40 (SPY / IEF)"]
    combo_fn = lambda t: pd.Series({"SPY": 0.5}).add(strat["Trend following (TSMOM, candidate)"](t) * 0.5, fill_value=0)
    combo, _ = simulate(rets, rf, combo_fn, dates)
    R["50% S&P 500 + 50% trend following"] = combo.loc[TEST_FROM:]

    P = {n: perf(r, rf) for n, r in R.items()}
    cr = {n: crisis_returns(r) for n, r in R.items()}
    corr = float((1 + cand).resample("ME").prod().corr((1 + spy).resample("ME").prod()))
    per = {f"{a}–{str(b)[2:] if b < 2100 else 'now'}": perf(cand[(cand.index.year >= a) & (cand.index.year <= b)], rf)["sharpe"] for a, b in PERIODS}
    pc = P["50% S&P 500 + 50% trend following"]
    rules = [
        ("1. Risk-adjusted", P["Trend following (TSMOM, candidate)"]["sharpe"] >= max(P["S&P 500 (SPY)"]["sharpe"], P["60/40 (SPY / IEF)"]["sharpe"]),
         f"Sharpe {P['Trend following (TSMOM, candidate)']['sharpe']:.2f} vs SPY {P['S&P 500 (SPY)']['sharpe']:.2f}, 60/40 {P['60/40 (SPY / IEF)']['sharpe']:.2f}"),
        ("2. Crisis protection", sum(v > 0 for v in cr["Trend following (TSMOM, candidate)"].values()) >= 3,
         ", ".join(f"{k} {v:+.1%}" for k, v in cr["Trend following (TSMOM, candidate)"].items())),
        ("3. Diversifying", corr <= 0.5, f"monthly correlation with SPY {corr:.2f}"),
        ("4. Better together", pc["sharpe"] > P["S&P 500 (SPY)"]["sharpe"] and pc["maxdd"] >= P["S&P 500 (SPY)"]["maxdd"] + 0.10,
         f"50/50: Sharpe {pc['sharpe']:.2f} vs {P['S&P 500 (SPY)']['sharpe']:.2f}, max drawdown {pc['maxdd']:.1%} vs {P['S&P 500 (SPY)']['maxdd']:.1%}"),
        ("5. Stable", sum(v > 0 for v in per.values()) >= 2, ", ".join(f"{k} {v:+.2f}" for k, v in per.items())),
    ]
    passed = all(x[1] for x in rules)

    # Return-target simulator: each base portfolio at leverage 0.5x to 3x (borrowing at T-bills + 2%).
    from .live import load_config, load_crypto
    from .backtest import Config, run_backtest
    from . import metrics
    lc = load_config(os.path.join(ROOT, "live.json"))
    cp, _ = load_crypto({**lc, "crypto": {**lc["crypto"], "enabled": True}})
    cres = run_backtest(cp, Config(**lc["crypto"]["strategy"]), cp["BTC/USD"])
    crypto = cres.returns.loc[metrics.first_trade(cres):]
    crypto.index = pd.DatetimeIndex(crypto.index)
    crypto = crypto[crypto.index.dayofweek < 5]  # weekdays, to sit on the same calendar as the ETFs
    bases = {"S&P 500": spy, "60/40": sixty, "Trend following": cand, "50% S&P 500 + 50% trend": R["50% S&P 500 + 50% trend following"],
             "Risk parity": R["Risk parity"], "Crypto trend sleeve (from 2019, 8 surviving coins)": crypto}
    grid = {}
    for b, r in bases.items():
        rows = []
        for L in np.round(np.arange(0.5, 3.01, 0.25), 2):
            lr = levered(r, rf, L)
            p = perf(lr, rf)
            rows.append({"L": float(L), "cagr": p["cagr"], "vol": p["vol"], "maxdd": p["maxdd"], "worst_year": p["worst_year"],
                         "sharpe": p["sharpe"], "loss1": loss_odds(lr, 1), "loss3": loss_odds(lr, 3), "loss5": loss_odds(lr, 5),
                         "years": len(lr) / 252})
        grid[b] = rows

    # Today's trend-following allocation and the universe table.
    last = px.index[-1]
    today = strat["Trend following (TSMOM, candidate)"](last)
    uni = []
    for c, (cls, desc) in UNIVERSE.items():
        s = px[c].dropna()
        ret = lambda m: float(s.iloc[-1] / s.iloc[-1 - m] - 1) if len(s) > m else None
        ex = [np.sign((s.iloc[-1] / s.iloc[-1 - m] - 1) - (rf_cum.iloc[-1] / rf_cum.iloc[-1 - m] - 1)) for m in (21, 63, 126, 252) if len(s) > m]
        gv = garch_vol(rets[[c]].iloc[-756:], 21).iloc[0] * math.sqrt(252)
        uni.append({"sym": c, "class": cls, "name": desc, "price": float(s.iloc[-1]), "m1": ret(21), "m3": ret(63), "m12": ret(252),
                    "trend": float(np.mean(ex)) if ex else None, "vol": float(gv), "weight": float(today.get(c, 0.0))})
    curves = {}
    for n, r in R.items():
        eq = (1 + r).cumprod().resample("ME").last()
        curves[n] = {"dates": [str(d.date()) for d in eq.index], "v": eq.round(4).tolist()}
    mcorr = pd.DataFrame({n: (1 + r).resample("ME").prod() - 1 for n, r in R.items()}).corr().round(2)
    out = {"built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "asof": str(last.date()),
           "universe": uni, "strategies": [{"name": n, **P[n], "turnover": float(T[n].sum() / (len(T[n]) / 252)) if n in T else None,
                                            "crises": cr[n]} for n in R], "crises": [c[0] for c in CRISES],
           "curves": curves, "corr": {"names": list(mcorr.columns), "m": mcorr.values.tolist()},
           "rules": rules, "passed": passed, "allocation": {k: float(v) for k, v in today.items()},
           "target": grid, "since": TEST_FROM}
    _write(os.path.join(ROOT, "site", "multiasset.json"), out)

    L = ["# Research report 9: multi-asset strategies", "",
         f"Generated {date.today()} by `python -m alphaforge.multiasset`. Rules committed before the run: "
         "[PREREGISTRATION_9.md](PREREGISTRATION_9.md).", "",
         f"16 ETFs, from {TEST_FROM[:4]}, monthly rebalancing, 3 bp per unit of turnover, cash at T-bills.", "",
         "| Strategy | CAGR | Vol | Sharpe | Max DD | Worst year | " + " | ".join(c[0] for c in CRISES) + " |",
         "|---|---|---|---|---|---|" + "---|" * len(CRISES)]
    for n, p in P.items():
        L.append(f"| {n} | {p['cagr']:.1%} | {p['vol']:.1%} | {p['sharpe']:.2f} | {p['maxdd']:.1%} | {p['worst_year']:.1%} | "
                 + " | ".join(f"{v:+.1%}" for v in cr[n].values()) + " |")
    L += ["", "## Rules for trend following", "", "| Rule | Result | Evidence |", "|---|---|---|"]
    L += [f"| {n} | {'pass' if ok else '**fail**'} | {e} |" for n, ok, e in rules]
    L += ["", "## Verdict", "", ("Trend following passes every rule: the 50/50 combination with the S&P 500 is proposed as a multi-asset "
                                 "sleeve on the paper account, live only with your approval." if passed else
                                 "Trend following does not pass every rule; nothing changes."), ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_9.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote site/multiasset.json and docs/RESEARCH_9.md; passed:", passed)
    for n, ok, e in rules:
        print(" ", n, ok, e)


if __name__ == "__main__":
    main()
