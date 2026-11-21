"""Pre-registered test 5 (docs/PREREGISTRATION_5.md): maximum diversification, a daily VaR limit, stress de-risking.

    python -m alphaforge.test5        # writes docs/RESEARCH_5.md and prints the decisions
"""
import json
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from . import metrics, models, pit
from .backtest import Config, run_backtest
from .data import DEFAULT_UNIVERSE, download, load_prices, risk_free
from .live import load_config
from .portfolio import max_div_weights
from .vol import garch_fit

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
COST = 7 / 1e4
VAR_LIMIT, Z99, BAND = 0.03, 2.326, 0.10
STRESS_SCALE, CALM_DAYS = 0.5, 5


# ---------------------------------------------------------------- overlays on a daily backtest

def apply_overlay(res, m, rf):
    """Scale the whole book by m (decided at close t, held from t+1). The freed cash earns rf; changing m
    costs 7 bp per unit of the book traded."""
    idx = res.returns.index
    m = m.reindex(idx).ffill().fillna(1.0)
    held = m.shift(1).fillna(1.0)
    gross_w = res.weights.shift(1).sum(axis=1).fillna(0)
    risky = res.gross_returns - (1 - gross_w) * rf.reindex(idx).fillna(0)       # W_{t-1} . R_t
    g = held * risky + (1 - held * gross_w) * rf.reindex(idx).fillna(0)
    trade = (m - m.shift(1).fillna(1.0)).abs() * res.weights.sum(axis=1)
    turnover = held * res.turnover + trade
    return g - held * res.costs - trade * COST, turnover


def var_scale(res, asset_rets):
    """C6: daily 99% VaR = 2.326 x GARCH volatility of the book; scale to a 3% limit, with a 10-point band.
    GARCH is refitted each month on the book's last 756 days at that month's weights, then updated daily
    with the book's realized return."""
    idx = res.returns.index
    W = res.weights
    risky = (W.shift(1).fillna(0) * asset_rets.reindex(idx).fillna(0)).sum(axis=1)
    month_end = idx.to_series().groupby(idx.to_period("M")).transform("max") == idx.to_series()
    m, cur, h, params = [], 1.0, None, None
    for i, t in enumerate(idx):
        if month_end.iloc[i] and i > 300:
            w = W.iloc[i]
            hist = (asset_rets.iloc[max(1, i - 755):i + 1].fillna(0) * w).sum(axis=1)
            if w.abs().sum() > 0 and hist.std() > 0:
                f = garch_fit(hist.values[:, None])
                params = (f["a"][0], f["b"][0], f["s2"][0])
                h = f["h_next"][0]
        elif params is not None:
            a, b, s2 = params
            h = s2 * (1 - a - b) + a * risky.iloc[i] ** 2 + b * h
        if params is None or W.iloc[i].abs().sum() == 0:
            m.append(cur)
            continue
        target = min(1.0, VAR_LIMIT / (Z99 * math.sqrt(h)))
        if abs(target - cur) > BAND or (target == 1.0 and cur < 1.0 and 1.0 - cur > BAND / 2):
            cur = target
        m.append(cur)
    return pd.Series(m, index=idx)


def stress_scale(close):
    """C7: 50% of the book while VIX > VIX3M or SPY's GARCH volatility is in its top 10% of the prior 10 years;
    back to 100% after 5 days in a row out of Stress."""
    g = models.garch_filtered_vol(np.log(close["SPY"]).diff())
    pct = g.rolling(2520, min_periods=750).apply(lambda x: (x[:-1] < x[-1]).mean() if np.isfinite(x[-1]) else np.nan, raw=True)
    stress = (close["^VIX"] > close["^VIX3M"]) | (pct > 0.9)
    m, cur, calm = [], 1.0, 0
    for s in stress.fillna(False):
        if s:
            cur, calm = STRESS_SCALE, 0
        else:
            calm += 1
            if cur < 1 and calm >= CALM_DAYS:
                cur = 1.0
        m.append(cur)
    return pd.Series(m, index=stress.index), stress


# ---------------------------------------------------------------- point-in-time check for C5

def pit_max_div(top_n=100, q=0.2, start="2014-01-01"):
    """Each month, the 100 most-traded S&P 500 members at that date: maximum diversification vs the current
    signal (momentum, top 20%, equal weight). Monthly returns net of costs."""
    spells = pit.membership()
    tick = sorted(t for t, sp in spells.items() if any(e is None or e >= pd.Timestamp(pit.START) for _, e in sp))
    px = pit.load_prices(tick)
    close, vol = px["Close"].reindex(columns=tick), px["Volume"].reindex(columns=tick)
    monthly = pit.month_ends(close)
    members = pit.member_mask(spells, monthly.index, tick)
    fwd = monthly.shift(-1) / monthly - 1
    mom = pit.momentum(monthly)
    dv = (close * vol).rolling(63, min_periods=40).mean().reindex(monthly.index)
    rets = close.pct_change(fill_method=None)
    out = {"Maximum diversification": [], "Momentum top 20% (current signal)": []}
    prev = {k: None for k in out}
    for t in monthly.index[(monthly.index >= start) & (monthly.index < monthly.index[-1])]:
        el = members.loc[t] & monthly.loc[t].notna() & mom.loc[t].notna()
        names = dv.loc[t, el[el].index].nlargest(top_n).index
        i = rets.index.get_loc(t)
        hist = rets.iloc[max(1, i - 755):i + 1][names]
        names = [s for s in names if hist[s].notna().sum() >= 300]
        r = fwd.loc[t, names].fillna(0.0)
        k = max(1, int(round(q * len(names))))
        weights = {"Maximum diversification": max_div_weights(hist[names], names, 0.10),
                   "Momentum top 20% (current signal)": pd.Series(1 / k, index=mom.loc[t, names].nlargest(k).index)}
        for k_, w in weights.items():
            w = w.reindex(names).fillna(0)
            cost = (w.sub(prev[k_], fill_value=0).abs().sum() if prev[k_] is not None else 1.0) * COST
            rp = float(w @ r)
            out[k_].append((t, rp - cost))
            prev[k_] = (w * (1 + r) / (1 + rp)).reindex(names)
    return {k: pd.Series(dict(v)) for k, v in out.items()}


# ---------------------------------------------------------------- statistics and rules

def summarize(r, turnover=None, ppy=252, rf=None):
    st = metrics.stats(r, None if rf is None else rf.reindex(r.index).fillna(0), ppy)
    post = r[r.index >= "2020-01-01"]
    rf_post = None if rf is None else rf.reindex(post.index).fillna(0)
    return {"sharpe": st["Sharpe"], "cagr": st["CAGR"], "vol": st["Ann. Vol"], "maxdd": st["Max Drawdown"],
            "sharpe_2020": metrics.sharpe(post, rf_post, ppy), "worst_month": float((1 + r).resample("ME").prod().sub(1).min()),
            "turnover": float(turnover.sum() / (len(r) / ppy)) if turnover is not None else None}


def rules(new, cur, turnover_cap=None):
    out = [("Max drawdown at least 2 points smaller", new["maxdd"] >= cur["maxdd"] + 0.02, f"{cur['maxdd']:.1%} → {new['maxdd']:.1%}"),
           ("Sharpe within 0.05", new["sharpe"] >= cur["sharpe"] - 0.05, f"{cur['sharpe']:.2f} → {new['sharpe']:.2f}")]
    if "sharpe_2020" in cur and cur.get("sharpe_2020") is not None and new.get("sharpe_2020") is not None:
        out.append(("Sharpe from 2020 within 0.05", new["sharpe_2020"] >= cur["sharpe_2020"] - 0.05,
                    f"{cur['sharpe_2020']:.2f} → {new['sharpe_2020']:.2f}"))
    if turnover_cap:
        out.append(("Turnover up at most 25%", new["turnover"] <= cur["turnover"] * (1 + turnover_cap),
                    f"{cur['turnover']:.1f}× → {new['turnover']:.1f}× a year"))
    return out


def main():
    lc = load_config(os.path.join(ROOT, "live.json"))
    base = dict(lc["strategy"])
    raw = download(sorted(set(DEFAULT_UNIVERSE + ["SPY", "^IRX", "^VIX", "^VIX3M"])), "2005-01-01")
    p30, bench = load_prices(DEFAULT_UNIVERSE, None, raw=raw)
    p30, bench = p30.loc["2014-01-01":], bench.loc["2014-01-01":]
    rf = risk_free(raw, 252).reindex(p30.index).fillna(0)
    asset = p30.pct_change(fill_method=None)

    def run(cfg):
        res = run_backtest(p30, Config(**cfg), bench, rf)
        return res, metrics.first_trade(res)

    cur_res, t0 = run(base)
    S, R = {}, {}
    S["current"] = summarize(cur_res.returns.loc[t0:], cur_res.turnover.loc[t0:], rf=rf)
    md_res, _ = run({**base, "mode": "max_div", "swap_every": 0})
    S["C5"] = summarize(md_res.returns.loc[t0:], md_res.turnover.loc[t0:], rf=rf)
    R["C5"] = rules(S["C5"], S["current"])
    v_m = var_scale(cur_res, asset)
    v_r, v_t = apply_overlay(cur_res, v_m, rf)
    S["C6"] = summarize(v_r.loc[t0:], v_t.loc[t0:], rf=rf)
    R["C6"] = rules(S["C6"], S["current"], 0.25)
    close = raw["Close"].ffill()
    s_m, stress = stress_scale(close)
    s_r, s_t = apply_overlay(cur_res, s_m.reindex(p30.index).ffill().fillna(1.0), rf)
    S["C7"] = summarize(s_r.loc[t0:], s_t.loc[t0:], rf=rf)
    R["C7"] = rules(S["C7"], S["current"], 0.25)
    stress_share = float(stress.reindex(p30.index).loc[t0:].fillna(False).mean())
    var_share = float((v_m.loc[t0:] < 1).mean())

    P = pit_max_div()
    rf_m = (1 + rf).resample("ME").prod() - 1
    PS = {k: {"sharpe": metrics.stats(v, None, 12)["Sharpe"], "maxdd": metrics.stats(v, None, 12)["Max Drawdown"],
              "cagr": metrics.stats(v, None, 12)["CAGR"]} for k, v in P.items()}
    R["C5 point-in-time"] = rules(PS["Maximum diversification"], PS["Momentum top 20% (current signal)"])

    passed = {k: all(ok for _, ok, _ in v) for k, v in R.items()}
    adopt = [k for k in ("C5", "C6", "C7") if passed[k] and (k != "C5" or passed["C5 point-in-time"])]
    combo = None
    if len(adopt) > 1:
        res_c, _ = run({**base, "mode": "max_div", "swap_every": 0}) if "C5" in adopt else (cur_res, t0)
        m = pd.Series(1.0, index=p30.index)
        if "C6" in adopt:
            m = m * var_scale(res_c, asset)
        if "C7" in adopt:
            m = m * s_m.reindex(p30.index).ffill().fillna(1.0)
        c_r, c_t = apply_overlay(res_c, m, rf) if ("C6" in adopt or "C7" in adopt) else (res_c.returns, res_c.turnover)
        combo = summarize(c_r.loc[t0:], c_t.loc[t0:], rf=rf)
        if not all(ok for _, ok, _ in rules(combo, S["current"])):
            adopt = [max(adopt, key=lambda k: S[k]["maxdd"])]

    labels = {"current": "Current (momentum, swap, optimizer, GARCH)", "C5": "C5 maximum diversification",
              "C6": "C6 daily VaR limit (3%)", "C7": "C7 stress de-risking (50%)"}
    L = ["# Research report 5: maximum diversification, VaR limit, stress de-risking", "",
         f"Generated {date.today()} by `python -m alphaforge.test5`. Rules committed before the run: "
         "[PREREGISTRATION_5.md](PREREGISTRATION_5.md). These are risk controls: a pass means smaller losses at about "
         "the same return, not an edge.", "",
         "## The 30 names, 2015 on, net of costs", "",
         "| Configuration | Sharpe | Sharpe from 2020 | CAGR | Vol | Max DD | Worst month | Turnover / yr |", "|---|---|---|---|---|---|---|---|"]
    for k, v in S.items():
        L.append(f"| {labels[k]} | {v['sharpe']:.2f} | {v['sharpe_2020']:.2f} | {v['cagr']:.1%} | {v['vol']:.1%} | {v['maxdd']:.1%} | "
                 f"{v['worst_month']:.1%} | {v['turnover']:.1f}× |")
    if combo:
        L.append(f"| Adopted together ({', '.join(adopt)}) | {combo['sharpe']:.2f} | {combo['sharpe_2020']:.2f} | {combo['cagr']:.1%} | "
                 f"{combo['vol']:.1%} | {combo['maxdd']:.1%} | {combo['worst_month']:.1%} | {combo['turnover']:.1f}× |")
    L += ["", f"The VaR limit was binding on {var_share:.0%} of days; the stress rule was on for {stress_share:.0%} of days.", "",
          "## Point-in-time check for C5 (100 most-traded S&P 500 members each month, 2014 on)", "",
          "| Weighting | Sharpe | CAGR | Max DD |", "|---|---|---|---|"]
    L += [f"| {k} | {v['sharpe']:.2f} | {v['cagr']:.1%} | {v['maxdd']:.1%} |" for k, v in PS.items()]
    L += ["", "## Rules", ""]
    for k, rs in R.items():
        L += [f"**{k}: {'pass' if passed[k] else 'fail'}**", "", "| Rule | Result | Evidence |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if ok else '**fail**'} | {ev} |" for n, ok, ev in rs] + [""]
    L += ["## Decision", "", f"Adopt: {', '.join(adopt) if adopt else 'nothing; the live strategy is unchanged'}.", ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_5.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print(json.dumps({"passed": passed, "adopt": adopt}, default=bool))


if __name__ == "__main__":
    main()
