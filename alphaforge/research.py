"""Research report: is there an edge? Writes docs/RESEARCH.md.

    python -m alphaforge.research

1. Each factor on its own: rank IC against forward returns, decay, turnover.
2. The live strategy against honest benchmarks (equal weight, momentum only, SPY), excess of T-bills.
3. Walk-forward: a fixed grid of settings; each year is traded with the setting that had the best
   Sharpe on all earlier years only. Every setting in the grid counts as a trial.
4. Deflated Sharpe ratio for the best in-sample setting, given the number of trials.
5. Breadth: the same strategy on the S&P 100 instead of 30 names.
6. The crypto trend sleeve against buy-and-hold.

Every universe here is today's membership, so every result is survivorship-biased upward.
"""
import itertools
import json
import math
from datetime import date
from statistics import NormalDist

import numpy as np
import pandas as pd

from . import metrics, signals
from .backtest import Config, run_backtest
from .data import DEFAULT_UNIVERSE, SP100, download, load_prices, risk_free
from .live import load_config, load_crypto

N01 = NormalDist()
EULER = 0.5772156649


def factor_ic(prices, horizons=(5, 21, 63)):
    """Monthly cross-sectional Spearman IC of each factor z-score vs forward returns."""
    scores = signals.factor_scores(prices)
    month_ends = prices.resample("ME").last().index
    rows = prices.index.searchsorted(month_ends, side="right") - 1
    rows = [r for r in rows if r >= 252]
    out = {}
    for name, z in scores.items():
        res = {}
        for h in horizons:
            fwd = prices.shift(-h) / prices - 1
            ics = []
            for r in rows:
                if r + h >= len(prices):
                    continue
                a, b = z.iloc[r], fwd.iloc[r]
                ok = a.notna() & b.notna()
                if ok.sum() > 5:
                    ics.append(a[ok].rank().corr(b[ok].rank()))
            ics = pd.Series(ics)
            res[h] = (ics.mean(), ics.mean() / ics.std() * math.sqrt(len(ics)) if len(ics) > 2 else np.nan, len(ics))
        # Turnover of the top third, month to month (1 = completely new names each month).
        tops = [set(z.iloc[r].dropna().nlargest(max(1, int(z.iloc[r].notna().sum() / 3))).index) for r in rows]
        churn = np.mean([1 - len(a & b) / len(a) for a, b in zip(tops, tops[1:]) if a])
        out[name] = {"ic": res, "top_third_turnover": churn}
    return out


def deflated_sharpe(r, trial_srs, n_trials):
    """Bailey & Lopez de Prado (2014). r: daily returns of the chosen strategy (excess).
    trial_srs: daily (non-annualized) Sharpe ratios of all trials. Returns (DSR, SR0 annualized)."""
    sr = r.mean() / r.std()
    t = len(r)
    skew, kurt = r.skew(), r.kurt() + 3
    v = np.var(trial_srs, ddof=1)
    sr0 = math.sqrt(v) * ((1 - EULER) * N01.inv_cdf(1 - 1 / n_trials) + EULER * N01.inv_cdf(1 - 1 / (n_trials * math.e)))
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(1 - skew * sr + (kurt - 1) / 4 * sr ** 2)
    return N01.cdf(z), sr0 * math.sqrt(252)


PRESETS = {
    "default 40/20/20/20": {"momentum": 0.4, "reversal": 0.2, "low_vol": 0.2, "quality_trend": 0.2},
    "momentum only": {"momentum": 1, "reversal": 0, "low_vol": 0, "quality_trend": 0},
    "no reversal 50/0/25/25": {"momentum": 0.5, "reversal": 0, "low_vol": 0.25, "quality_trend": 0.25},
    "equal 25 each": {"momentum": 0.25, "reversal": 0.25, "low_vol": 0.25, "quality_trend": 0.25},
    "low-vol tilt 30/10/40/20": {"momentum": 0.3, "reversal": 0.1, "low_vol": 0.4, "quality_trend": 0.2},
}


def walk_forward(prices, bench, rf, base, ew, first_test_year=2018):
    grid = list(itertools.product(PRESETS, (0, 10), (0.10, 0.15)))
    runs = {}
    for preset, swap, cap in grid:
        cfg = Config(**{**base, "factor_weights": PRESETS[preset], "swap_every": swap, "max_weight": cap})
        res = run_backtest(prices, cfg, bench, rf)
        runs[(preset, swap, cap)] = res.returns.loc[metrics.first_trade(res):]
    ex = {k: v - rf.reindex(v.index).fillna(0) for k, v in runs.items()}
    years = sorted({d.year for d in next(iter(runs.values())).index})
    oos, picks = [], []
    for y in years:
        if y < first_test_year:
            continue
        train = {k: v[v.index.year < y] for k, v in ex.items()}
        best = max(train, key=lambda k: train[k].mean() / train[k].std())
        oos.append(runs[best][runs[best].index.year == y])
        picks.append((y, best, metrics.sharpe(train[best], ann=252)))
    oos = pd.concat(oos)
    full_sr = {k: metrics.sharpe(v, rf, 252) for k, v in runs.items()}
    best_full = max(full_sr, key=full_sr.get)
    trial_daily = [v.mean() / v.std() for v in ex.values()]
    dsr, sr0 = deflated_sharpe(ex[best_full], trial_daily, len(grid))
    # The question that matters: does any setting beat simply holding the same names equally?
    act = {k: (v - ew.reindex(v.index)).dropna() for k, v in runs.items()}
    ir = {k: v.mean() / v.std() * math.sqrt(252) for k, v in act.items()}
    best_ir = max(ir, key=ir.get)
    dsr_act, ir0 = deflated_sharpe(act[best_ir], [v.mean() / v.std() for v in act.values()], len(grid))
    return {"grid": len(grid), "oos": oos, "picks": picks, "full_sr": full_sr, "best_full": best_full,
            "dsr": dsr, "sr0": sr0, "ir": ir, "best_ir": best_ir, "dsr_act": dsr_act, "ir0": ir0,
            "years": len(next(iter(act.values()))) / 252}


def _row(name, r, rf, ann=252, bench=None):
    s = metrics.stats(r, rf, ann, bench)
    return (f"| {name} | {s['CAGR']:.1%} | {s['Ann. Vol']:.1%} | {s['Sharpe']:.2f} ± {s['Sharpe SE']:.2f} | "
            f"{s['Max Drawdown']:.1%} |")


def main():
    lc = load_config("live.json")
    base = {**lc["strategy"]}
    raw = download(sorted(set(DEFAULT_UNIVERSE + SP100 + ["SPY", "^IRX"])), lc["history_start"])
    rf = risk_free(raw, 252)
    p30, bench = load_prices(DEFAULT_UNIVERSE, None, raw=raw)
    p100, _ = load_prices([s for s in SP100 if s in raw["Close"]], None, raw=raw)
    rf = rf.reindex(p30.index).fillna(0)

    L = [f"# Research report", "",
         f"Generated {date.today()} by `python -m alphaforge.research`. Live configuration: `{json.dumps(base)}`.", "",
         "**Read every number here as an upper bound.** Each universe is today's membership projected backward "
         "(survivorship bias), and this report itself is one more trial.", ""]

    # 1. factors
    ic = factor_ic(p30)
    L += ["## 1. Each factor on its own", "",
          "Monthly cross-sectional rank IC (Spearman correlation between the factor z-score and the next *h* days' "
          "return) on the 30-stock universe. t-stat = mean / sd × √n. |t| above about 2 is the usual bar.", "",
          "| Factor | IC 5d | IC 21d (t) | IC 63d (t) | Top-third turnover / month |", "|---|---|---|---|---|"]
    for f, v in ic.items():
        i5, i21, i63 = v["ic"][5], v["ic"][21], v["ic"][63]
        L.append(f"| {f} | {i5[0]:+.3f} | {i21[0]:+.3f} ({i21[1]:+.1f}) | {i63[0]:+.3f} ({i63[1]:+.1f}) | "
                 f"{v['top_third_turnover']:.0%} |")
    L.append("")

    # 2. benchmarks
    live = run_backtest(p30, Config(**base), bench, rf)
    t0 = metrics.first_trade(live)
    k = dict(cost_bps=live.config.cost_bps, slippage_bps=live.config.slippage_bps, warmup=live.config.warmup)
    ew = run_backtest(p30, Config(model="equal", mode="equal", target_vol=None, max_weight=1, max_leverage=1, **k), None, rf)
    mom = run_backtest(p30, Config(**{**base, "swap_every": 0, "factor_weights": PRESETS["momentum only"]}), None, rf)
    noswap = run_backtest(p30, Config(**{**base, "swap_every": 0}), None, rf)
    rft = rf.loc[t0:]
    L += ["## 2. Live strategy against benchmarks", "",
          f"From {t0.date()}, net of costs; Sharpe is excess of T-bills, ± one standard error.", "",
          "| Series | CAGR | Vol | Sharpe | Max DD |", "|---|---|---|---|---|",
          _row("Live strategy (30 names)", live.returns.loc[t0:], rft),
          _row("Same, without the 2-week swap", noswap.returns.loc[t0:], rft),
          _row("Momentum only", mom.returns.loc[t0:], rft),
          _row("Equal weight, same 30 names", ew.returns.loc[t0:], rft),
          _row("SPY", live.benchmark.loc[t0:], rft), ""]
    b, a = metrics.beta_alpha(live.returns.loc[t0:], ew.returns.loc[t0:], rft)
    L += [f"Against the equal-weight portfolio of the same names, the strategy's beta is {b:.2f} and its annual alpha "
          f"is {a:+.1%}. That alpha is what the factors add beyond simply owning these winners.", ""]

    # 3-4. walk-forward + DSR
    wf = walk_forward(p30, bench, rf, base, ew.returns)
    oos = wf["oos"]
    rfo = rf.reindex(oos.index).fillna(0)
    best = wf["best_full"]
    L += ["## 3. Walk-forward", "",
          f"Grid of {wf['grid']} settings: 5 factor-weight presets × swap on/off × 10% or 15% position cap. "
          "Each calendar year from 2018 is traded with the setting that had the best Sharpe on all earlier years.", "",
          "| Year | Setting chosen (preset, swap days, cap) | Train Sharpe | Year return |", "|---|---|---|---|"]
    for y, k_, sr in wf["picks"]:
        yr = (1 + oos[oos.index.year == y]).prod() - 1
        L.append(f"| {y} | {k_[0]}, {k_[1]}, {k_[2]:.0%} | {sr:.2f} | {yr:+.1%} |")
    L += ["", "| | CAGR | Vol | Sharpe | Max DD |", "|---|---|---|---|---|",
          _row("Walk-forward, out of sample (2018 on)", oos, rfo),
          _row(f"Best setting chosen with hindsight: {best[0]}, {best[1]}, {best[2]:.0%}",
               (live.returns * 0 + 0).loc[oos.index] + run_backtest(p30, Config(**{**base, "factor_weights": PRESETS[best[0]],
                                                                                    "swap_every": best[1], "max_weight": best[2]}),
                                                                       bench, rf).returns.loc[oos.index], rfo), ""]
    srs = sorted(wf["full_sr"].values())
    L += ["## 4. Deflated Sharpe ratio", "",
          f"Across the {wf['grid']} trials, full-period Sharpe ratios range from {srs[0]:.2f} to {srs[-1]:.2f}. "
          f"With that many tries, the best Sharpe expected from luck alone is about **{wf['sr0']:.2f}**. "
          f"The probability that the best setting's true Sharpe is above zero, after correcting for the number of trials "
          f"and for skew and fat tails, is **{min(wf['dsr'], 0.999):.1%}** (deflated Sharpe ratio; 95% is the usual bar).", "",
          "That clears the bar, but zero is a low bar: almost any long-only stock portfolio from 2015 to 2026 does. "
          "The harder test is whether a setting beats **holding the same 30 names in equal weight**. On daily returns "
          "in excess of the equal-weight portfolio:", "",
          "| Setting | Information ratio vs equal weight | t-stat |", "|---|---|---|"]
    for k_, v in sorted(wf["ir"].items(), key=lambda kv: -kv[1])[:5]:
        L.append(f"| {k_[0]}, swap {k_[1]}, cap {k_[2]:.0%} | {v:+.2f} | {v * math.sqrt(wf['years']):+.1f} |")
    live_k = next((k_ for k_ in wf["ir"] if PRESETS[k_[0]] == base.get("factor_weights", PRESETS["default 40/20/20/20"])
                   and k_[1] == base.get("swap_every", 0) and k_[2] == base.get("max_weight", 0.10)), None)
    if live_k:
        L.append(f"| **live setting** ({live_k[0]}, swap {live_k[1]}, cap {live_k[2]:.0%}) | {wf['ir'][live_k]:+.2f} | "
                 f"{wf['ir'][live_k] * math.sqrt(wf['years']):+.1f} |")
    L += ["", f"Corrected for {wf['grid']} trials, the probability that even the best setting truly beats equal weight "
          f"is **{wf['dsr_act']:.0%}**. Below 95%, the honest reading is: **no demonstrated edge over equal weight**; "
          "the factors mostly trade return for lower volatility and drawdown.", ""]

    # 5. breadth
    wide = run_backtest(p100, Config(**base), bench, rf)
    tw = metrics.first_trade(wide)
    L += ["## 5. Breadth: 100 names instead of 30", "",
          "| Universe | CAGR | Vol | Sharpe | Max DD |", "|---|---|---|---|---|",
          _row(f"S&P 100 ({p100.shape[1]} names with full history)", wide.returns.loc[tw:], rf.loc[tw:]),
          _row("30 mega caps (live)", live.returns.loc[tw:], rf.loc[tw:]), "",
          "Wider universes need a point-in-time constituent list (Norgate, Sharadar or CRSP) before the comparison "
          "means much; today's S&P 100 is just as survivorship-biased as today's top 30.", ""]

    # 6. crypto
    cc = load_config("live.json")
    cc["crypto"]["enabled"] = True
    cp, _ = load_crypto(cc)
    cs = Config(**cc["crypto"]["strategy"])
    cr = run_backtest(cp, cs, cp["BTC/USD"])
    tc = metrics.first_trade(cr)
    cew = run_backtest(cp, Config(model="equal", mode="equal", target_vol=None, max_weight=1, max_leverage=1,
                                  rebalance="W-SUN", cost_bps=cs.cost_bps, slippage_bps=cs.slippage_bps, warmup=cs.warmup, ann=365))
    L += ["## 6. Crypto trend sleeve", "",
          f"From {tc.date()}, {cp.shape[1]} coins, 365-day annualization, no risk-free rate.", "",
          "| Series | CAGR | Vol | Sharpe | Max DD |", "|---|---|---|---|---|",
          _row("Trend sleeve (live settings)", cr.returns.loc[tc:], None, 365),
          _row("Bitcoin buy and hold", cr.benchmark.loc[tc:], None, 365),
          _row("Equal weight, same coins", cew.returns.loc[tc:], None, 365), "",
          "Trend-following's case in crypto is drawdown control, not a higher Sharpe ratio.", ""]
    with open("docs/RESEARCH.md", "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote docs/RESEARCH.md")


if __name__ == "__main__":
    main()
