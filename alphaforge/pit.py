"""Pre-registered test 2 (docs/PREREGISTRATION_PIT.md): three signals on a point-in-time S&P 500.

    python -m alphaforge.pit            # writes docs/RESEARCH_PIT.md and alphaforge/calibration.json

Membership comes from data/sp500_ticker_start_end.csv (github.com/fja05680/sp500, MIT licence):
each ticker's index entry and exit dates. Prices are Yahoo daily adjusted closes, cached in
data/cache/ so a rerun doesn't download again.
"""
import json
import math
import os
from datetime import date
from statistics import NormalDist

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MEMBERS = os.path.join(ROOT, "data", "sp500_ticker_start_end.csv")
CACHE = os.path.join(ROOT, "data", "cache", "pit_prices.pkl")
START, TEST_FROM = "2010-01-01", "2012-01-01"
COST = 7 / 1e4          # per unit of sum |dw|, as in the backtest
TOP = 0.20              # top 20% by the signal
PERIODS = [(2012, 2015), (2016, 2019), (2020, 2022), (2023, 2100)]
PRIOR_TRIALS = 22       # configurations tried in this project before this test
N01 = NormalDist()


# ---------------------------------------------------------------- data

def yahoo(t):
    return t.replace(".", "-")


def membership(path=MEMBERS):
    """Ticker -> list of (start, end) membership spells; end None = still a member."""
    d = pd.read_csv(path, parse_dates=["start_date", "end_date"])
    spells = {}
    for t, s, e in d.itertuples(index=False):
        spells.setdefault(yahoo(t), []).append((s, None if pd.isna(e) else e))
    return spells


def member_mask(spells, dates, tickers):
    """Boolean frame: was ticker a member of the index on each date?"""
    m = pd.DataFrame(False, index=dates, columns=tickers)
    for t in tickers:
        for s, e in spells.get(t, []):
            m.loc[(dates >= s) & ((dates < e) if e is not None else True), t] = True
    return m


def load_prices(tickers, refresh=False):
    """Daily Close and Volume for every ticker, from 2010. Cached."""
    if os.path.exists(CACHE) and not refresh:
        c = pd.read_pickle(CACHE)  # our own cache file, written below; never loaded from elsewhere
        if set(tickers) <= set(c["Close"].columns) | set(c.attrs.get("missing", [])):
            return c
    import yfinance as yf
    parts, missing = [], []
    for i in range(0, len(tickers), 100):
        chunk = tickers[i:i + 100]
        raw = yf.download(chunk, start=START, auto_adjust=True, progress=False, threads=True)
        raw = raw[["Close", "Volume"]]
        got = [t for t in chunk if t in raw["Close"] and raw["Close"][t].notna().any()]
        missing += [t for t in chunk if t not in got]
        parts.append(raw.loc[:, (slice(None), got)])
    out = pd.concat(parts, axis=1).sort_index()
    out.attrs["missing"] = missing
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    out.to_pickle(CACHE)
    return out


# ---------------------------------------------------------------- signals (all known at month-end t)

def month_ends(close):
    """Last trading day of each month, and the last close of each ticker within each month."""
    me = close.groupby(close.index.to_period("M")).apply(lambda x: x.index[-1])
    monthly = close.groupby(close.index.to_period("M")).last()  # last non-missing close in the month
    monthly.index = pd.DatetimeIndex(me.values)
    return monthly


def momentum(monthly):
    return monthly.shift(1) / monthly.shift(12) - 1


def residual_momentum(monthly, members, window=36, min_obs=24):
    """Blitz, Huij & Martens (2011): residuals from a regression of monthly returns on the equal-weighted
    member return over the prior 36 months; sum of the last 12-to-1 residuals over their std."""
    R = monthly.pct_change(fill_method=None)
    mkt = R.where(members).mean(axis=1)
    out = pd.DataFrame(np.nan, index=R.index, columns=R.columns)
    Rv, mv = R.values, mkt.values
    for t in range(window, len(R)):
        y, x = Rv[t - window + 1:t + 1], mv[t - window + 1:t + 1]
        ok = np.isfinite(y) & np.isfinite(x)[:, None]
        n = ok.sum(axis=0)
        xm = np.where(ok, x[:, None], 0).sum(0) / np.maximum(n, 1)
        ym = np.where(ok, y, 0).sum(0) / np.maximum(n, 1)
        dx, dy = np.where(ok, x[:, None] - xm, 0), np.where(ok, y - ym, 0)
        beta = (dx * dy).sum(0) / np.maximum((dx * dx).sum(0), 1e-12)
        e = np.where(ok, dy - beta * dx, np.nan)
        form = e[-12:-1]  # months t-11 .. t-1: skip the latest month, like 12-1 momentum
        sd = np.nanstd(form, axis=0, ddof=1)
        s = np.nansum(form, axis=0) / np.where(sd > 0, sd, np.nan)
        s[(n < min_obs) | (np.isfinite(form).sum(0) < 9)] = np.nan
        out.iloc[t] = s
    return out


def high52(close, monthly):
    return (close / close.rolling(252, min_periods=200).max()).reindex(monthly.index)


# ---------------------------------------------------------------- portfolio and statistics

def simulate(signal, fwd, eligible):
    """Monthly long-only top-20% equal weight vs equal weight of all eligible members, with costs.
    Returns (strategy, benchmark, monthly IC, top-half and bottom-half-by-liquidity active returns)."""
    strat, bench, ic, w_s, w_b = [], [], [], None, None
    for t in signal.index:
        el = eligible.loc[t] & signal.loc[t].notna()
        names = el[el].index
        if len(names) < 50:
            continue
        r = fwd.loc[t, names].fillna(0.0)  # priced at t, no price after: return unknown, counted as 0
        s = signal.loc[t, names]
        top = s.rank(ascending=False) <= max(1, round(TOP * len(names)))
        ws = pd.Series(np.where(top, 1 / top.sum(), 0.0), index=names)
        wb = pd.Series(1 / len(names), index=names)
        cs = (ws - (w_s.reindex(names).fillna(0) if w_s is not None else 0)).abs().sum() if w_s is not None else 1.0
        cb = (wb - (w_b.reindex(names).fillna(0) if w_b is not None else 0)).abs().sum() if w_b is not None else 1.0
        rs, rb = float(ws @ r), float(wb @ r)
        strat.append((t, rs - cs * COST))
        bench.append((t, rb - cb * COST))
        ic.append((t, s.rank().corr(fwd.loc[t, names].rank()) if fwd.loc[t, names].notna().sum() > 20 else np.nan))
        w_s, w_b = ws * (1 + r) / (1 + rs), wb * (1 + r) / (1 + rb)  # drift to the next rebalance
    f = lambda xs: pd.Series(dict(xs)).sort_index()
    return f(strat), f(bench), f(ic).dropna()


def ir(a):
    a = a.dropna()
    return a.mean() / a.std() * math.sqrt(12) if len(a) > 6 and a.std() > 0 else float("nan")


def prior_grid_irs():
    """Annual IRs vs equal weight of the 20-setting grid already tried (RESEARCH.md section 3), so the
    deflation sees the dispersion of every earlier trial, not only these three."""
    from . import research
    from .backtest import Config, run_backtest
    from .data import DEFAULT_UNIVERSE, download, load_prices as lp, risk_free
    from .live import load_config
    base = {k: v for k, v in load_config(os.path.join(ROOT, "live.json"))["strategy"].items() if k not in research.OPTIMIZER_KEYS}
    raw = download(DEFAULT_UNIVERSE + ["SPY", "^IRX"], "2014-01-01")
    p30, bench = lp(DEFAULT_UNIVERSE, None, raw=raw)
    rf = risk_free(raw, 252).reindex(p30.index).fillna(0)
    c = Config(**base)
    ew = run_backtest(p30, Config(model="equal", mode="equal", target_vol=None, max_weight=1, max_leverage=1,
                                  cost_bps=c.cost_bps, slippage_bps=c.slippage_bps, warmup=c.warmup), None, rf)
    return list(research.walk_forward(p30, bench, rf, base, ew.returns)["ir"].values())


# ---------------------------------------------------------------- the test

def run_test(refresh=False):
    spells = membership()
    tickers = sorted(t for t, sp in spells.items() if any(e is None or e >= pd.Timestamp(START) for _, e in sp))
    px = load_prices(tickers, refresh)
    close, vol = px["Close"].reindex(columns=tickers), px["Volume"].reindex(columns=tickers)
    monthly = month_ends(close)
    members = member_mask(spells, monthly.index, tickers)
    priced = monthly.notna()
    fwd = monthly.shift(-1) / monthly - 1
    test = monthly.index[(monthly.index >= TEST_FROM) & (monthly.index < monthly.index[-1])]
    eligible = (members & priced).loc[test]
    coverage = float((members & priced).loc[test].values.sum() / members.loc[test].values.sum())
    gone = float(((members & priced) & fwd.isna()).loc[test].values.sum() / (members & priced).loc[test].values.sum())

    sigs = {"A. Momentum 12-1": momentum(monthly), "B. Residual momentum": residual_momentum(monthly, members & priced),
            "C. 52-week high": high52(close, monthly)}
    dv = (close * vol).rolling(63, min_periods=40).mean().reindex(monthly.index)
    liquid = dv.ge(dv.where(members & priced).median(axis=1), axis=0)

    from . import research
    results = {}
    for name, sig in sigs.items():
        sig = sig.loc[test]
        s, b, ic = simulate(sig, fwd.loc[test], eligible)
        a = (s - b).dropna()
        half = {h: simulate(sig, fwd.loc[test], eligible & m)[:2] for h, m in (("liquid", liquid.loc[test]), ("less liquid", ~liquid.loc[test]))}
        results[name] = {"s": s, "b": b, "a": a, "ic": ic, "half": {h: ir(x[0] - x[1]) for h, x in half.items()}}
    trial_srs = [r["a"].mean() / r["a"].std() for r in results.values()]
    trial_srs += [v / math.sqrt(12) for v in prior_grid_irs()]
    n_trials = PRIOR_TRIALS + len(sigs)
    for name, r in results.items():
        a, ic = r["a"], r["ic"]
        yrs = len(a) / 12
        dsr, sr0 = research.deflated_sharpe(a, trial_srs, n_trials)
        per = {f"{y0}–{str(y1)[2:] if y1 < 2100 else 'now'}": ir(a[(a.index.year >= y0) & (a.index.year <= y1)]) for y0, y1 in PERIODS}
        ic_t = ic.mean() / ic.std() * math.sqrt(len(ic))
        r["rules"] = [
            ("1. Signal", ic.mean() > 0 and ic_t >= 2, f"IC {ic.mean():+.3f}, t {ic_t:+.1f} over {len(ic)} months"),
            ("2. Edge vs equal weight", ir(a) * math.sqrt(yrs) >= 2, f"IR {ir(a):+.2f}, t {ir(a) * math.sqrt(yrs):+.1f} over {yrs:.1f} years"),
            ("3. Deflated", dsr >= 0.95, f"{dsr:.0%} after {n_trials} trials"),
            ("4. Stability", sum(v > 0 for v in per.values()) >= 3, ", ".join(f"{k} {v:+.2f}" for k, v in per.items())),
            ("5. Breadth", all(v > 0 for v in r["half"].values()), ", ".join(f"{k} {v:+.2f}" for k, v in r["half"].items())),
            ("6. Coverage", coverage >= 0.90, f"{coverage:.1%} of member-months priced"),
        ]
        r["passed"], r["dsr"], r["ic_t"] = all(x[1] for x in r["rules"]), dsr, ic_t
    return {"results": results, "coverage": coverage, "gone": gone, "n_tickers": len(tickers),
            "n_priced": int(priced.any().sum()), "test": (test[0], test[-1]), "sigs": sigs, "monthly": monthly,
            "fwd": fwd, "eligible": eligible, "close": close}


# ---------------------------------------------------------------- forecast calibration

def calibration(res, name):
    """What a forecast from signal `name` has been worth: IC per month (for the forecast's size) and
    realized next-month excess return by forecast quintile (for the screen's track record)."""
    sig, fwd, el = res["sigs"][name], res["fwd"], res["eligible"]
    rows = []
    for t in el.index:
        names = el.columns[el.loc[t] & sig.loc[t].notna() & fwd.loc[t].notna()]
        if len(names) < 50:
            continue
        x = fwd.loc[t, names] - fwd.loc[t, names].mean()
        q = pd.qcut(sig.loc[t, names].rank(method="first"), 5, labels=False)
        rows.append(x.groupby(q).mean())
    by_q = pd.DataFrame(rows).mean()
    ic = res["results"][name]["ic"]
    return {"signal": name, "ic_mean": float(ic.mean()), "ic_t": float(ic.mean() / ic.std() * math.sqrt(len(ic))),
            "ic_last36": float(ic.iloc[-36:].mean()), "hit_rate": float((ic > 0).mean()), "months": len(ic),
            "quintile_excess": [float(v) for v in by_q.values], "built": str(date.today())}


# ---------------------------------------------------------------- report

def _stats(r):
    cagr = (1 + r).prod() ** (12 / len(r)) - 1
    vol = r.std() * math.sqrt(12)
    dd = ((1 + r).cumprod() / (1 + r).cumprod().cummax() - 1).min()
    return cagr, vol, dd


def main():
    res = run_test()
    R = res["results"]
    t0, t1 = res["test"]
    L = ["# Research report 2: point-in-time S&P 500", "",
         f"Generated {date.today()} by `python -m alphaforge.pit`. Rules committed before the run: "
         "[PREREGISTRATION_PIT.md](PREREGISTRATION_PIT.md).", "",
         f"Universe: S&P 500 members at each month-end, {t0:%B %Y} to {t1:%B %Y}. {res['n_tickers']} tickers were members "
         f"at some point since 2010; Yahoo has prices for {res['n_priced']}. **{res['coverage']:.1%}** of member-months are "
         f"priced; for {res['gone']:.1%} the stock has a price at the month-end but none a month later (delisted or "
         "taken over mid-month), and that month's return is counted as 0 for both the strategy and the benchmark.", "",
         "Strategy: top 20% by the signal, equal weight, rebalanced monthly. Benchmark: equal weight of all priced "
         "members. Both pay 7 bp per unit of turnover.", "",
         "| Signal | CAGR | Vol | Max DD | Benchmark CAGR | Active / yr | IR | t |", "|---|---|---|---|---|---|---|---|"]
    for name, r in R.items():
        c, v, d = _stats(r["s"])
        cb, *_ = _stats(r["b"])
        yrs = len(r["a"]) / 12
        L.append(f"| {name} | {c:.1%} | {v:.1%} | {d:.1%} | {cb:.1%} | {r['a'].mean() * 12:+.1%} | {ir(r['a']):+.2f} | "
                 f"{ir(r['a']) * math.sqrt(yrs):+.1f} |")
    L.append("")
    for name, r in R.items():
        L += [f"## {name}", "", "| Rule | Result | Evidence |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if ok else '**fail**'} | {ev} |" for n, ok, ev in r["rules"]]
        L.append("")
    winners = [n for n, r in R.items() if r["passed"]]
    best = max(winners, key=lambda n: R[n]["dsr"]) if winners else None
    L += ["## Verdict", "",
          (f"**{best}** passes every rule: provisionally demonstrated, pending 6–12 months of paper trading. "
           "It becomes the live signal." if best else
           "**No demonstrated edge.** No candidate passes all six rules, so the live strategy stays as it is. "
           "The forecast screen on the terminal uses the candidate with the strongest IC and shows how weak "
           "that forecast is."), ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_PIT.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    chosen = best or max(R, key=lambda n: R[n]["ic_t"])
    with open(os.path.join(ROOT, "alphaforge", "calibration.json"), "w") as f:
        json.dump({**calibration(res, chosen), "verdict": "provisional" if best else "no demonstrated edge"}, f, indent=1)
    print("wrote docs/RESEARCH_PIT.md and alphaforge/calibration.json")
    for n, r in R.items():
        print(n, "PASS" if r["passed"] else "fail", [ok for _, ok, _ in r["rules"]])


if __name__ == "__main__":
    main()
