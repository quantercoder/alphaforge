"""Pre-registered test 3 (docs/PREREGISTRATION_3.md): fewer sells into dips, and GARCH volatility.

    python -m alphaforge.improve        # writes docs/RESEARCH_3.md and prints the decisions

C1 no two-week swap; C2 rank buffer (top 30% in, top 50% out); C3 GARCH(1,1) volatility in the
volatility target; C4 crypto exit buffer (sell only when all three trend lookbacks are negative).
"""
import json
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from . import metrics, pit
from .backtest import Config, run_backtest
from .data import DEFAULT_UNIVERSE, SP100, download, load_prices, risk_free
from .live import load_config, load_crypto
from .vol import garch_vol, qlike

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TURNOVER_CUT, SHARPE_SLACK, DD_SLACK = 0.15, 0.05, 0.02


def summarize(res, rf, ann, target=None):
    t0 = metrics.first_trade(res)
    r = res.returns.loc[t0:]
    st = metrics.stats(r, None if rf is None else rf.loc[t0:], ann)
    years = len(r) / ann
    out = {"sharpe": st["Sharpe"], "cagr": st["CAGR"], "vol": st["Ann. Vol"], "maxdd": st["Max Drawdown"],
           "turnover": float(res.turnover.loc[t0:].sum() / years), "trades": int((res.turnover.loc[t0:] > 0).sum() / years)}
    if target:
        rv = (r.rolling(63).std() * math.sqrt(ann)).dropna()
        out["vol_gap"] = float((rv - target).abs().mean())
    return out


def trading_rules(new, cur):
    """C1, C2, C4: turnover down >= 15%, Sharpe within 0.05, max drawdown within 2 points."""
    return [
        ("Turnover down at least 15%", new["turnover"] <= (1 - TURNOVER_CUT) * cur["turnover"],
         f"{cur['turnover']:.1f}× → {new['turnover']:.1f}× a year ({new['turnover'] / cur['turnover'] - 1:+.0%})"),
        ("Sharpe within 0.05", new["sharpe"] >= cur["sharpe"] - SHARPE_SLACK, f"{cur['sharpe']:.2f} → {new['sharpe']:.2f}"),
        ("Max drawdown within 2 points", new["maxdd"] >= cur["maxdd"] - DD_SLACK, f"{cur['maxdd']:.1%} → {new['maxdd']:.1%}"),
    ]


def forecast_test(rets, months, horizon=21, window=756):
    """Out-of-sample volatility forecasts at each month-end: GARCH(1,1) vs the 63-day sample."""
    rows = []
    idx = rets.index
    for t in months:
        i = idx.get_loc(t)
        if i < window or i + horizon >= len(idx):
            continue
        past, fut = rets.iloc[i - window + 1:i + 1], rets.iloc[i + 1:i + 1 + horizon]
        ok = [c for c in rets.columns if past[c].notna().all() and fut[c].notna().all()]
        if len(ok) < 10:
            continue
        g = garch_vol(past[ok], horizon, window, min_obs=window) ** 2 * horizon
        s = past[ok].iloc[-63:].var() * horizon
        real = (fut[ok] ** 2).sum()
        move = fut[ok].add(1).prod() - 1
        for c in ok:
            rows.append({"t": t, "sym": c, "real": real[c], "garch": g[c], "sample": s[c], "move": move[c]})
    return pd.DataFrame(rows)


def mz_r2(real, fc):
    x, y = np.asarray(fc), np.asarray(real)
    return float(np.corrcoef(x, y)[0, 1] ** 2)


def main():
    lc = load_config(os.path.join(ROOT, "live.json"))
    base = dict(lc["strategy"])
    raw = download(sorted(set(DEFAULT_UNIVERSE + SP100 + ["SPY", "^IRX"])), "2014-01-01")
    p30, bench = load_prices(DEFAULT_UNIVERSE, None, raw=raw)
    rf = risk_free(raw, 252).reindex(p30.index).fillna(0)
    target = base.get("target_vol", 0.12)

    variants = {"current": base, "C1": {**base, "swap_every": 0}, "C2": {**base, "hold_buffer": 0.5},
                "C3": {**base, "vol_model": "garch"}}
    S = {k: summarize(run_backtest(p30, Config(**v), bench, rf), rf, 252, target) for k, v in variants.items()}
    cur = S["current"]
    rules = {"C1": trading_rules(S["C1"], cur), "C2": trading_rules(S["C2"], cur)}

    # C2 on the point-in-time S&P 500: top 20% in, keep while in the top 40%.
    spells = pit.membership()
    tick = sorted(t for t, sp in spells.items() if any(e is None or e >= pd.Timestamp(pit.START) for _, e in sp))
    px = pit.load_prices(tick)
    close = px["Close"].reindex(columns=tick)
    monthly = pit.month_ends(close)
    members = pit.member_mask(spells, monthly.index, tick)
    fwd = monthly.shift(-1) / monthly - 1
    test = monthly.index[(monthly.index >= pit.TEST_FROM) & (monthly.index < monthly.index[-1])]
    el = (members & monthly.notna()).loc[test]
    sig = pit.momentum(monthly).loc[test]
    pit_stats = {}
    for name, kf in (("current", None), ("C2", 0.40)):
        to = []
        s, _, _ = pit.simulate(sig, fwd.loc[test], el, keep_frac=kf, turnover=to)
        dd = ((1 + s).cumprod() / (1 + s).cumprod().cummax() - 1).min()
        pit_stats[name] = {"sharpe": s.mean() / s.std() * math.sqrt(12), "maxdd": dd, "turnover": float(np.mean(to[1:]) * 12)}
    rules["C2 point-in-time"] = trading_rules(pit_stats["C2"], pit_stats["current"])

    # C3: out-of-sample volatility forecasts on every terminal stock with 4+ years of prices.
    names = [s for s in dict.fromkeys(DEFAULT_UNIVERSE + SP100) if s in raw["Close"]]
    rets = raw["Close"][names].pct_change(fill_method=None)
    me = rets.groupby(rets.index.to_period("M")).apply(lambda x: x.index[-1])
    months = [d for d in me.values if pd.Timestamp(d) >= pd.Timestamp("2016-01-01")]
    F = forecast_test(rets, months)
    F["q_garch"], F["q_sample"] = qlike(F["real"], F["garch"]), qlike(F["real"], F["sample"])
    per = F.groupby("sym")[["q_garch", "q_sample"]].mean()
    share = float((per["q_garch"] < per["q_sample"]).mean())
    cover = {m: float((F["move"].abs() <= np.sqrt(F[m])).mean()) for m in ("garch", "sample")}
    fc = {"names": len(per), "obs": len(F), "q_garch": float(F["q_garch"].mean()), "q_sample": float(F["q_sample"].mean()),
          "share": share, "mz_garch": mz_r2(F["real"], F["garch"]), "mz_sample": mz_r2(F["real"], F["sample"]), "cover": cover}
    rules["C3"] = [
        ("Lower QLIKE in aggregate", fc["q_garch"] < fc["q_sample"], f"{fc['q_sample']:.3f} → {fc['q_garch']:.3f}"),
        ("Lower QLIKE for at least 70% of stocks", share >= 0.70, f"{share:.0%} of {fc['names']} stocks"),
        ("Closer to the 12% volatility target", S["C3"]["vol_gap"] < cur["vol_gap"],
         f"average gap {cur['vol_gap']:.1%} → {S['C3']['vol_gap']:.1%}"),
        ("Sharpe within 0.05", S["C3"]["sharpe"] >= cur["sharpe"] - SHARPE_SLACK, f"{cur['sharpe']:.2f} → {S['C3']['sharpe']:.2f}"),
    ]

    # C4: crypto exit buffer.
    cc = lc["crypto"]
    cp, _ = load_crypto({**lc, "crypto": {**cc, "enabled": True}})
    cbase = dict(cc["strategy"])
    CS = {k: summarize(run_backtest(cp, Config(**v), cp["BTC/USD"]), None, 365)
          for k, v in (("current", cbase), ("C4", {**cbase, "trend_exit": -1.0}))}
    rules["C4"] = trading_rules(CS["C4"], CS["current"])

    passed = {k: all(ok for _, ok, _ in v) for k, v in rules.items()}
    adopt = [k for k in ("C1", "C2", "C3") if passed[k] and (k != "C2" or passed["C2 point-in-time"])]
    combo_cfg = {**base}
    for k in adopt:
        combo_cfg.update({k_: v for k_, v in variants[k].items() if base.get(k_) != v})
    combo = summarize(run_backtest(p30, Config(**combo_cfg), bench, rf), rf, 252, target) if len(adopt) > 1 else None
    combo_ok = combo is None or all(ok for _, ok, _ in trading_rules(combo, cur)[1:])
    if not combo_ok:
        best = max(adopt, key=lambda k: S[k]["sharpe"])
        combo_cfg = {**base, **{k_: v for k_, v in variants[best].items() if base.get(k_) != v}}
        adopt = [best]

    L = ["# Research report 3: fewer sells into dips, and GARCH volatility", "",
         f"Generated {date.today()} by `python -m alphaforge.improve`. Rules committed before the run: "
         "[PREREGISTRATION_3.md](PREREGISTRATION_3.md). None of these changes claims an edge (see "
         "[RESEARCH_PIT.md](RESEARCH_PIT.md)); they change how the book trades and how it forecasts risk.", "",
         "## Stocks (30 names, 2015 on, net of costs)", "",
         "| Configuration | Sharpe | CAGR | Vol | Max DD | Turnover / yr | Trade days / yr | Gap to 12% vol |",
         "|---|---|---|---|---|---|---|---|"]
    labels = {"current": "Current (momentum, 2-week swap, optimizer)", "C1": "C1 no swap", "C2": "C2 rank buffer",
              "C3": "C3 GARCH volatility"}
    for k, v in S.items():
        L.append(f"| {labels[k]} | {v['sharpe']:.2f} | {v['cagr']:.1%} | {v['vol']:.1%} | {v['maxdd']:.1%} | "
                 f"{v['turnover']:.1f}× | {v['trades']} | {v['vol_gap']:.1%} |")
    if combo:
        L.append(f"| Adopted together ({', '.join(adopt)}) | {combo['sharpe']:.2f} | {combo['cagr']:.1%} | {combo['vol']:.1%} | "
                 f"{combo['maxdd']:.1%} | {combo['turnover']:.1f}× | {combo['trades']} | {combo['vol_gap']:.1%} |")
    L += ["", "## Point-in-time S&P 500 (momentum, top 20%)", "", "| | Sharpe | Max DD | Turnover / yr |", "|---|---|---|---|"]
    L += [f"| {'Current' if k == 'current' else 'C2 rank buffer (keep while top 40%)'} | {v['sharpe']:.2f} | {v['maxdd']:.1%} | "
          f"{v['turnover']:.1f}× |" for k, v in pit_stats.items()]
    L += ["", "## Volatility forecasts (out of sample, 21 days ahead)", "",
          f"{fc['obs']:,} forecasts: {fc['names']} stocks at every month-end from 2016, each GARCH fitted on the prior 3 years only.", "",
          "| Model | QLIKE (lower is better) | Mincer-Zarnowitz R² | 68% range coverage |", "|---|---|---|---|",
          f"| 63-day sample (current) | {fc['q_sample']:.3f} | {fc['mz_sample']:.2f} | {fc['cover']['sample']:.0%} |",
          f"| GARCH(1,1) | {fc['q_garch']:.3f} | {fc['mz_garch']:.2f} | {fc['cover']['garch']:.0%} |", "",
          "A well-calibrated 68% range contains the next month's move 68% of the time.", "",
          "## Crypto (8 coins, 2019 on)", "", "| | Sharpe | CAGR | Max DD | Turnover / yr | Trade days / yr |", "|---|---|---|---|---|---|"]
    L += [f"| {'Current' if k == 'current' else 'C4 exit buffer (sell only when all three lookbacks are negative)'} | "
          f"{v['sharpe']:.2f} | {v['cagr']:.1%} | {v['maxdd']:.1%} | {v['turnover']:.1f}× | {v['trades']} |" for k, v in CS.items()]
    L += ["", "## Rules", ""]
    for k, rs in rules.items():
        L += [f"**{k}: {'pass' if passed[k] else 'fail'}**", "", "| Rule | Result | Evidence |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if ok else '**fail**'} | {ev} |" for n, ok, ev in rs] + [""]
    L += ["## Decision", "",
          f"Stocks: {'adopt ' + ', '.join(adopt) if adopt else 'no change'}"
          + ("" if combo_ok else " (the combination failed, so only the best single change)") + ". "
          f"Crypto: {'adopt C4' if passed['C4'] else 'no change'}.", ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_3.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    decision = {"stocks": {k: v for k, v in combo_cfg.items() if base.get(k) != v}, "crypto": {"trend_exit": -1.0} if passed["C4"] else {},
                "passed": passed}
    print(json.dumps(decision, default=bool))


if __name__ == "__main__":
    main()
