"""Pre-registered test 6 (docs/PREREGISTRATION_6.md): SPY forecasts with point-in-time FRED / ALFRED macro data.

    FRED_API_KEY=... python -m alphaforge.macro      # writes docs/RESEARCH_6.md (run by the research workflow)

Macro series are taken as they were known on each forecast date: for every observation, the ALFRED vintage whose
publication window contains that date. Revisions published later never reach the model.
"""
import math
import os
from datetime import date

import numpy as np
import pandas as pd

from . import models, sources
from .data import download

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
CACHE = os.path.join(ROOT, "data", "cache")
MARKET = {"DGS10": "DGS10", "DGS3MO": "DGS3MO", "BAA10Y": "BAA10Y", "VIXCLS": "VIXCLS", "DTWEXBGS": "DTWEXBGS",
          "DCOILWTICO": "DCOILWTICO"}
VINTAGED = ("PAYEMS", "UNRATE", "CPIAUCSL", "INDPRO", "ICSA", "NFCI", "PERMIT")
TECHNICAL = ["ret_5d", "ret_21d", "ret_63d", "ret_252d", "vs_200d_avg", "realized_vol_21d", "garch_vol"]
DM_BAR = 0.05 / 3


# ---------------------------------------------------------------- data

def _cached(name, fetch):
    path = os.path.join(CACHE, f"fred_{name}.pkl")
    if os.path.exists(path) and (pd.Timestamp.now() - pd.Timestamp(os.path.getmtime(path), unit="s")).days < 1:
        return pd.read_pickle(path)  # our own cache, written below (restored only from this repo's Actions cache)
    obj = fetch()
    os.makedirs(CACHE, exist_ok=True)
    obj.to_pickle(path)
    return obj


def load_fred():
    market = {k: _cached(k, lambda s=s: sources.fred_latest(s)) for k, s in MARKET.items()}
    vint = {k: _cached(f"{k}_vintages", lambda k=k: sources.fred_vintages(k)) for k in VINTAGED}
    return market, vint


def known_on(vint, t):
    """The series as it was known on day t: for each observation date, the vintage published by t."""
    v = vint[(vint["realtime_start"] <= t) & (vint["realtime_end"] >= t)]
    return v.set_index("date")["value"].sort_index()


def macro_features(market, vint, dates):
    """Point-in-time macro features at each date (rows) as defined in the pre-registration."""
    rows = []
    for t in dates:
        prev = t - pd.Timedelta(days=1)  # market series: the previous day's value, to allow for publication

        def last(s, n=0):
            s = s[s.index <= prev].dropna()
            return s.iloc[-1 - n] if len(s) > n else np.nan

        def chg63(s):
            s = s[s.index <= prev].dropna()
            return s.iloc[-1] / s.iloc[-64] - 1 if len(s) > 64 else np.nan

        f = {"term_spread": last(market["DGS10"]) - last(market["DGS3MO"]), "credit_spread": last(market["BAA10Y"]),
             "vix": last(market["VIXCLS"]), "dollar_63d": chg63(market["DTWEXBGS"]), "oil_63d": chg63(market["DCOILWTICO"])}
        k = {s: known_on(vint[s], t) for s in VINTAGED}
        at = lambda s, n: k[s].iloc[-1 - n] if len(k[s]) > n else np.nan
        f["payroll_growth"] = (at("PAYEMS", 0) / at("PAYEMS", 3)) ** 4 - 1
        f["unemployment_momentum"] = at("UNRATE", 0) - (k["UNRATE"].iloc[-13:-1].min() if len(k["UNRATE"]) > 12 else np.nan)
        f["inflation_12m"] = at("CPIAUCSL", 0) / at("CPIAUCSL", 12) - 1
        f["industrial_6m"] = at("INDPRO", 0) / at("INDPRO", 6) - 1
        f["claims_trend"] = (k["ICSA"].iloc[-4:].mean() / k["ICSA"].iloc[-52:].mean() - 1) if len(k["ICSA"]) >= 52 else np.nan
        f["financial_conditions"] = at("NFCI", 0)
        f["permits_12m"] = at("PERMIT", 0) / at("PERMIT", 12) - 1
        rows.append(f)
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates))


# ---------------------------------------------------------------- the test

def run():
    raw = download(["SPY", "^VIX"], "2005-01-01")
    close = raw["Close"].ffill()
    tech, lp, _ = models.technical_features(close["SPY"])
    rows = models.weekly_rows(lp.index[lp.index >= "2006-01-01"])
    market, vint = load_fred()
    M = macro_features(market, vint, rows)
    F = tech[TECHNICAL].reindex(rows).join(M)
    P, _, _ = models.walk_forward_market(close, features=F)
    out = {}
    for h, df in P.items():
        ev = models.evaluate(df, h)
        e = ev[models.ENSEMBLE]
        out[h] = {"eval": ev, "passed": e["r2_oos"] > 0 and e["dm_p"] is not None and e["dm_p"] < DM_BAR}
    return out, F


def main():
    res, F = run()
    L = ["# Research report 6: SPY forecasts with point-in-time macro data", "",
         f"Generated {date.today()} by `python -m alphaforge.macro`. Rules committed before the run: "
         "[PREREGISTRATION_6.md](PREREGISTRATION_6.md).", "",
         f"Features: {len(F.columns)} ({', '.join(F.columns)}). Macro series are ALFRED vintages as known on each "
         f"forecast date. First complete feature row: {F.dropna().index[0].date()}. Out of sample from January 2014.", ""]
    for h, v in res.items():
        L += [f"## {h} trading days", "", "| Model | Out-of-sample R² | DM p | Hit rate |", "|---|---|---|---|"]
        for m, e in v["eval"].items():
            dm = "" if e["dm_p"] is None else f"{e['dm_p']:.3f}"
            L.append(f"| {m} | {e['r2_oos']:+.2%} | {dm} | {e['hit']:.1%} |")
        e = v["eval"][models.ENSEMBLE]
        L += ["", f"Rule (ensemble R² > 0 and DM p < {DM_BAR:.4f}): **{'pass' if v['passed'] else 'fail'}** "
                  f"(R² {e['r2_oos']:+.2%}, p {e['dm_p']:.3f}).", ""]
    passed = [h for h, v in res.items() if v["passed"]]
    L += ["## Verdict", "", (f"Point-in-time macro gives out-of-sample skill at {', '.join(map(str, passed))} days: provisionally "
                             "demonstrated, reported and not traded." if passed else
                             "No horizon passes: point-in-time macro data does not make SPY forecastable beyond the historical "
                             "mean either."), ""]
    with open(os.path.join(ROOT, "docs", "RESEARCH_6.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("wrote docs/RESEARCH_6.md;", {h: v["passed"] for h, v in res.items()})


if __name__ == "__main__":
    main()
