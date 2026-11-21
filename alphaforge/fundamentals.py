"""Pre-registered test 7 (docs/PREREGISTRATION_7.md): SEC EDGAR fundamentals on the point-in-time S&P 500.

    SEC_USER_AGENT="Name email" python -m alphaforge.fundamentals      # run by the research workflow

Every value counts from the day after its filing date, and for each fiscal period only the first filed value is
used, so restatements never leak backwards. Valuation ratios use the actual price of the day (Yahoo's
split-adjusted close multiplied back by later splits), so they match the share counts and per-share figures in
the filings.
"""
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from . import pit, research, sources

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.path.join(ROOT, "data", "cache")
EVENTS = os.path.join(ROOT, "data", "fundamental_events.csv.gz")
TEST_FROM = "2013-01-01"
PERIODS = [(2013, 2016), (2017, 2019), (2020, 2022), (2023, 2100)]
N_TRIALS = 43
SIGNALS = {"F1": "Book-to-market (value)", "F2": "Earnings yield (value)", "F3": "Profitability, ROA (quality)",
           "F4": "Earnings surprise, SUE (drift)"}


# ---------------------------------------------------------------- extraction from SEC company facts

def _facts(cf, taxonomy, concept, unit):
    try:
        rows = cf["facts"][taxonomy][concept]["units"][unit]
    except KeyError:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for c in ("end", "filed") + (("start",) if "start" in df else ()):
        df[c] = pd.to_datetime(df[c])
    return df


def first_filed(df, keys):
    """For each fiscal period (keys), the value as first filed."""
    return df.sort_values("filed").drop_duplicates(keys, keep="first") if len(df) else df


def durations(df, lo, hi):
    if not len(df) or "start" not in df:
        return df.iloc[0:0]
    d = (df["end"] - df["start"]).dt.days
    return df[(d >= lo) & (d <= hi)]


def company_events(cf):
    """Point-in-time fundamental events for one company: rows (field, value, available, period_end)."""
    ev = []
    add = lambda field, df, col="val": ev.extend(
        {"field": field, "value": float(r[col]), "available": r["filed"] + pd.Timedelta(days=1), "end": r["end"]}
        for _, r in df.iterrows())
    eq = _facts(cf, "us-gaap", "StockholdersEquity", "USD")
    if len(eq):
        add("equity", first_filed(eq[eq["form"].str.startswith("10-K")], ["end"]))
    sh = _facts(cf, "dei", "EntityCommonStockSharesOutstanding", "shares")
    if len(sh):  # several share classes are reported as separate facts in one filing: add them up
        sh = sh.groupby(["accn", "end", "filed"], as_index=False)["val"].sum()
        add("shares", first_filed(sh, ["end"]))
    eps = _facts(cf, "us-gaap", "EarningsPerShareDiluted", "USD/shares")
    if len(eps):
        annual = first_filed(durations(eps[eps["form"].str.startswith("10-K")], 350, 380), ["end"])
        add("eps_annual", annual)
        quarters = first_filed(durations(eps, 80, 100), ["start", "end"])
        q4 = []
        for _, a in annual.iterrows():  # fourth quarter = the year minus its first three quarters
            inside = quarters[(quarters["start"] >= a["start"] - pd.Timedelta(days=5)) & (quarters["end"] < a["end"] - pd.Timedelta(days=20))]
            if len(inside) == 3:
                q4.append({"val": a["val"] - inside["val"].sum(), "filed": a["filed"], "end": a["end"]})
        q = pd.concat([quarters[["val", "filed", "end"]], pd.DataFrame(q4, columns=["val", "filed", "end"])])
        add("eps_quarter", first_filed(q, ["end"]))
    ni = _facts(cf, "us-gaap", "NetIncomeLoss", "USD")
    assets = _facts(cf, "us-gaap", "Assets", "USD")
    if len(ni) and len(assets):
        ni_a = first_filed(durations(ni[ni["form"].str.startswith("10-K")], 350, 380), ["end"])
        a_f = first_filed(assets, ["end"]).set_index("end")["val"]
        for _, r in ni_a.iterrows():
            near = lambda d: a_f[(a_f.index >= d - pd.Timedelta(days=10)) & (a_f.index <= d + pd.Timedelta(days=10))]
            e, s = near(r["end"]), near(r["start"] - pd.Timedelta(days=1))
            if len(e) and len(s) and e.iloc[0] + s.iloc[0] > 0:
                ev.append({"field": "roa", "value": r["val"] / ((e.iloc[0] + s.iloc[0]) / 2),
                           "available": r["filed"] + pd.Timedelta(days=1), "end": r["end"]})
    return ev


def sue_events(q):
    """Standardized unexpected earnings from first-filed quarterly EPS of one company (sorted by quarter end)."""
    q = q.sort_values("end").drop_duplicates("end")
    out, changes = [], []
    ends, vals, avail = list(q["end"]), list(q["value"]), list(q["available"])
    for i in range(len(q)):
        prior = [j for j in range(i) if abs((ends[i] - ends[j]).days - 364) <= 25]
        if not prior:
            continue
        ch = vals[i] - vals[prior[-1]]
        hist = changes[-8:]
        if len(hist) >= 4 and np.std(hist, ddof=1) > 0:
            out.append({"value": ch / np.std(hist, ddof=1), "available": avail[i], "end": ends[i]})
        changes.append(ch)
    return out


def download_events(tickers):
    """Fundamental events for every ticker the SEC's ticker file can match. Cached as a compact CSV."""
    if os.path.exists(EVENTS):
        return pd.read_csv(EVENTS, parse_dates=["available", "end"])
    cik = sources.sec_tickers()
    rows, matched = [], 0
    for t in tickers:
        c = cik.get(t) or cik.get(t.replace("-", ".")) or cik.get(t.replace(".", "-"))
        if not c:
            continue
        try:
            cf = sources.sec_company_facts(c)
        except RuntimeError:
            continue
        matched += 1
        ev = pd.DataFrame(company_events(cf))
        if ev.empty:
            continue
        ev["ticker"] = t
        q = ev[ev["field"] == "eps_quarter"]
        sue = pd.DataFrame(sue_events(q))
        if len(sue):
            sue["field"], sue["ticker"] = "sue", t
            ev = pd.concat([ev, sue])
        rows.append(ev)
    out = pd.concat(rows, ignore_index=True)
    out.to_csv(EVENTS, index=False, compression="gzip")
    print(f"SEC: matched {matched} of {len(tickers)} tickers")
    return out


def raw_prices(tickers):
    """Actual historical closes: Yahoo's split-adjusted, not dividend-adjusted close times every later split."""
    import yfinance as yf
    closes = []
    for i in range(0, len(tickers), 100):
        d = yf.download(tickers[i:i + 100], start=pit.START, auto_adjust=False, actions=True, progress=False, threads=True)
        close, splits = d["Close"], d["Stock Splits"].replace(0, np.nan).fillna(1.0)
        later = splits[::-1].cumprod()[::-1].shift(-1).fillna(1.0)  # product of splits after each day
        closes.append(close * later)
    return pd.concat(closes, axis=1)


def asof_panel(ev, field, months, tickers, max_age_days=None):
    """Month-end panel of the latest available value of a field (and its age limit, for SUE)."""
    e = ev[ev["field"] == field].sort_values("available")
    out = pd.DataFrame(np.nan, index=months, columns=tickers)
    for t, g in e.groupby("ticker"):
        if t not in out.columns:
            continue
        s = g.set_index("available")["value"]
        s = s[~s.index.duplicated(keep="last")]
        v = s.reindex(months, method="ffill")
        if max_age_days:
            when = pd.Series(s.index, index=s.index).reindex(months, method="ffill")
            v[(months - when).dt.days > max_age_days] = np.nan
        out[t] = v.values
    return out


# ---------------------------------------------------------------- the test

def run():
    spells = pit.membership()
    tick = sorted(t for t, sp in spells.items() if any(e is None or e >= pd.Timestamp(pit.START) for _, e in sp))
    px = pit.load_prices(tick)
    close = px["Close"].reindex(columns=tick)
    monthly = pit.month_ends(close)
    members = pit.member_mask(spells, monthly.index, tick)
    fwd = monthly.shift(-1) / monthly - 1
    test = monthly.index[(monthly.index >= TEST_FROM) & (monthly.index < monthly.index[-1])]
    ev = download_events(tick)
    rp = raw_prices(tick).reindex(columns=tick)
    raw_m = rp.groupby(rp.index.to_period("M")).last()
    raw_m.index = monthly.index[:len(raw_m)] if len(raw_m) == len(monthly) else pd.DatetimeIndex(
        [monthly.index[monthly.index.to_period("M") == p][0] for p in raw_m.index if (monthly.index.to_period("M") == p).any()])
    raw_m = raw_m.reindex(monthly.index)
    sig = {
        "F1": asof_panel(ev, "equity", test, tick) / (raw_m.loc[test] * asof_panel(ev, "shares", test, tick)),
        "F2": asof_panel(ev, "eps_annual", test, tick) / raw_m.loc[test],
        "F3": asof_panel(ev, "roa", test, tick),
        "F4": asof_panel(ev, "sue", test, tick, max_age_days=122),
    }
    sig["F1"] = sig["F1"].where(sig["F1"] > 0)  # negative book equity: not a value signal
    priced = (members & monthly.notna()).loc[test]
    vol = px["Volume"].reindex(columns=tick)
    dv = (close * vol).rolling(63, min_periods=40).mean().reindex(monthly.index).loc[test]
    liquid = dv.ge(dv.where(priced).median(axis=1), axis=0)
    results = {}
    for k, s in sig.items():
        el = priced & s.notna()
        a_s, a_b, ic = pit.simulate(s, fwd.loc[test], el)
        a = (a_s - a_b).dropna()
        halves = {}
        for h, m in (("liquid", liquid), ("less liquid", ~liquid)):
            hs, hb, _ = pit.simulate(s, fwd.loc[test], el & m)
            halves[h] = pit.ir(hs - hb)
        results[k] = {"s": a_s, "b": a_b, "a": a, "ic": ic, "halves": halves,
                      "coverage": float(el.values.sum() / priced.values.sum())}
    trial_srs = [r["a"].mean() / r["a"].std() for r in results.values()] + [v / math.sqrt(12) for v in pit.prior_grid_irs()]
    for k, r in results.items():
        a, ic = r["a"], r["ic"]
        yrs = len(a) / 12
        dsr, _ = research.deflated_sharpe(a, trial_srs, N_TRIALS)
        per = {f"{y0}–{str(y1)[2:] if y1 < 2100 else 'now'}": pit.ir(a[(a.index.year >= y0) & (a.index.year <= y1)]) for y0, y1 in PERIODS}
        ic_t = ic.mean() / ic.std() * math.sqrt(len(ic))
        r["rules"] = [
            ("1. Signal", ic.mean() > 0 and ic_t >= 2, f"IC {ic.mean():+.3f}, t {ic_t:+.1f}"),
            ("2. Edge vs equal weight", pit.ir(a) * math.sqrt(yrs) >= 2, f"IR {pit.ir(a):+.2f}, t {pit.ir(a) * math.sqrt(yrs):+.1f} over {yrs:.1f} years"),
            ("3. Deflated", dsr >= 0.95, f"{dsr:.0%} after {N_TRIALS} trials"),
            ("4. Stability", sum(v > 0 for v in per.values()) >= 3, ", ".join(f"{p} {v:+.2f}" for p, v in per.items())),
            ("5. Breadth", all(v > 0 for v in r["halves"].values()), ", ".join(f"{h} {v:+.2f}" for h, v in r["halves"].items())),
            ("6. Coverage", r["coverage"] >= 0.70, f"{r['coverage']:.0%} of priced member-months have the signal"),
        ]
        r["passed"] = all(x[1] for x in r["rules"])
    return results, ev


def main():
    res, ev = run()
    L = ["# Research report 7: SEC EDGAR fundamentals", "",
         f"Generated {date.today()} by `python -m alphaforge.fundamentals`. Rules committed before the run: "
         "[PREREGISTRATION_7.md](PREREGISTRATION_7.md).", "",
         f"{ev['ticker'].nunique()} companies matched to SEC filings; {len(ev):,} point-in-time events "
         "(each usable from the day after its filing). Events: `data/fundamental_events.csv.gz`.", "",
         "| Signal | Coverage | IC | IR vs equal weight | t | Rules passed |", "|---|---|---|---|---|---|"]
    for k, r in res.items():
        yrs = len(r["a"]) / 12
        L.append(f"| {k} {SIGNALS[k]} | {r['coverage']:.0%} | {r['ic'].mean():+.3f} | {pit.ir(r['a']):+.2f} | "
                 f"{pit.ir(r['a']) * math.sqrt(yrs):+.1f} | {sum(x[1] for x in r['rules'])} of 6 |")
    L.append("")
    for k, r in res.items():
        L += [f"## {k}. {SIGNALS[k]}", "", "| Rule | Result | Evidence |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if ok else '**fail**'} | {e} |" for n, ok, e in r["rules"]] + [""]
    win = [k for k, r in res.items() if r["passed"]]
    L += ["## Verdict", "", (f"{', '.join(win)} passes every rule: provisionally demonstrated; proposed for the live strategy "
                             "only with your approval and after its own paper period." if win else
                             "No fundamental signal passes all six rules: no demonstrated edge from fundamentals either."), ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_7.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote docs/RESEARCH_7.md;", {k: r["passed"] for k, r in res.items()})


if __name__ == "__main__":
    main()
