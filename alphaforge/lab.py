"""The Lab: an institutional-style research page built from free data, with every number labelled as
measured data or model output. Writes site/lab.json and docs/RESEARCH_4.md (pre-registered test 4).

    python -m alphaforge.lab

Sections: market intelligence, multi-model forecasts (track A: SPY; track B: point-in-time S&P 500),
risk of the paper book, strategy lab, portfolio construction and leverage, alerts, data integrity.
"""
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import metrics, models, pit, research, strategies
from .backtest import Config, run_backtest
from .data import DEFAULT_UNIVERSE, SP100, download, risk_free
from .live import load_config
from .portfolio import solve_qp
from .refdata import name, sector
from .terminal import _clean, _write
from .vol import garch_vol

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MACRO = ["SPY", "QQQ", "IWM", "TLT", "^VIX", "^VIX3M", "^TNX", "^IRX", "HYG", "IEF", "DX-Y.NYB", "CL=F", "GC=F",
         "HG=F", "BTC-USD"]
SECTOR_ETFS = {"XLK": "Technology", "XLF": "Financials", "XLV": "Health Care", "XLE": "Energy", "XLI": "Industrials",
               "XLY": "Consumer Discretionary", "XLP": "Consumer Staples", "XLU": "Utilities", "XLB": "Materials",
               "XLRE": "Real Estate", "XLC": "Communication Services"}
UNAVAILABLE = [
    ("Institutional flows (13F, fund flows, order flow)", "no free real-time source; nothing is estimated or shown in their place"),
    ("Analyst estimates and revisions", "not free (I/B/E/S); earnings surprises are measured against the company's own history instead"),
    ("Economic-events calendar", "no free, reliable machine-readable source; FOMC, CPI and payroll dates are not shown"),
    ("Options data (implied volatility surface, skew, open interest)", "not available free; VIX and VIX3M are the only implied-volatility inputs"),
    ("Prices of about 24% of former S&P 500 members", "Yahoo has no history for many delisted stocks (84% of member-months are priced)"),
    ("Deep learning (LSTM, Transformer)", "not run: about 800 MB of PyTorch per install, and weak evidence on daily returns (see RESEARCH_4.md)"),
]


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pct_rank(s, x):
    s = s.dropna()
    return float((s <= x).mean()) if len(s) else None


# ---------------------------------------------------------------- market intelligence

def market_intel(c, v, pclose, pvol, current):
    spy = c["SPY"].dropna()
    g = models.garch_filtered_vol(np.log(spy).diff())
    gv = g.dropna()
    vix, vix3m = c["^VIX"].dropna(), c["^VIX3M"].dropna()
    trend_up = spy.iloc[-1] > spy.rolling(200).mean().iloc[-1]
    vol_pct = pct_rank(gv.iloc[-2520:], gv.iloc[-1])
    inverted = vix.iloc[-1] > vix3m.iloc[-1]
    regime = "Stress" if inverted or vol_pct > 0.9 else ("Risk-on" if trend_up and vol_pct < 0.5 else "Neutral")
    macro_defs = [
        ("VIX (implied 30-day volatility)", c["^VIX"], "level"), ("VIX / VIX3M (term structure)", c["^VIX"] / c["^VIX3M"], "ratio"),
        ("10y − 3m Treasury spread (pts)", c["^TNX"] - c["^IRX"], "level"), ("10-year Treasury yield (%)", c["^TNX"], "level"),
        ("Credit: HYG / IEF", c["HYG"] / c["IEF"], "price"), ("US dollar (DXY)", c["DX-Y.NYB"], "price"),
        ("WTI crude", c["CL=F"], "price"), ("Gold", c["GC=F"], "price"), ("Copper / gold", c["HG=F"] / c["GC=F"], "price"),
        ("Long Treasuries (TLT)", c["TLT"], "price"), ("Small caps vs large (IWM / SPY)", c["IWM"] / c["SPY"], "price"),
    ]
    macro = []
    for label, s, kind in macro_defs:
        s = s.dropna()
        if len(s) < 260:
            continue
        chg = (s.iloc[-1] - s.iloc[-22]) if kind != "price" else s.iloc[-1] / s.iloc[-22] - 1
        y = s.iloc[-252:]
        macro.append({"name": label, "value": float(s.iloc[-1]), "kind": kind, "chg_1m": float(chg),
                      "z_1y": float((s.iloc[-1] - y.mean()) / y.std()) if y.std() > 0 else None,
                      "pct_10y": pct_rank(s.iloc[-2520:], s.iloc[-1]), "date": str(s.index[-1].date())})
    sectors = []
    for t, nm in SECTOR_ETFS.items():
        s = c[t].dropna() if t in c else pd.Series(dtype=float)
        if len(s) < 70:
            continue
        r = lambda n: float(s.iloc[-1] / s.iloc[-1 - n] - 1)
        ytd = s[s.index.year == s.index[-1].year]
        sectors.append({"etf": t, "sector": nm, "w1": r(5), "m1": r(21), "m3": r(63),
                        "ytd": float(s.iloc[-1] / s[s.index < ytd.index[0]].iloc[-1] - 1)})
    # Breadth and anomalies on today's S&P 500 members.
    px = pclose[[t for t in current if t in pclose]].ffill()
    last = px.iloc[-1]
    breadth = {"members": int(last.notna().sum()),
               "above_200d": float((last > px.rolling(200).mean().iloc[-1]).mean()),
               "above_50d": float((last > px.rolling(50).mean().iloc[-1]).mean()),
               "new_high_52w": int((last >= px.iloc[-252:].max()).sum()), "new_low_52w": int((last <= px.iloc[-252:].min()).sum()),
               "advancing": int((px.iloc[-1] > px.iloc[-2]).sum()), "declining": int((px.iloc[-1] < px.iloc[-2]).sum()),
               "date": str(px.index[-1].date())}
    r = px.pct_change(fill_method=None)
    z = r.iloc[-1] / r.iloc[-64:-1].std()
    vz = (pvol[px.columns].iloc[-1] - pvol[px.columns].iloc[-64:-1].mean()) / pvol[px.columns].iloc[-64:-1].std()
    anomalies = [{"sym": s, "ret": float(r.iloc[-1][s]), "ret_z": float(z[s]), "vol_z": float(vz[s]) if np.isfinite(vz[s]) else None}
                 for s in px.columns if np.isfinite(z[s]) and (abs(z[s]) > 3 or (np.isfinite(vz[s]) and vz[s] > 3))]
    anomalies.sort(key=lambda a: -abs(a["ret_z"]))
    return {"regime": {"label": regime, "trend_up": bool(trend_up), "garch_vol": float(gv.iloc[-1]), "vol_pct_10y": vol_pct,
                       "vix": float(vix.iloc[-1]), "vix_inverted": bool(inverted), "spy": float(spy.iloc[-1]),
                       "spy_vs_200d": float(spy.iloc[-1] / spy.rolling(200).mean().iloc[-1] - 1), "date": str(spy.index[-1].date()),
                       "rule": "Stress if VIX is above VIX3M (inverted) or GARCH volatility is in its top 10% of 10 years; "
                               "Risk-on if SPY is above its 200-day average and volatility is below its 10-year median; else Neutral."},
            "macro": macro, "sectors": sectors, "breadth": breadth, "anomalies": anomalies[:25]}


def news_and_earnings(symbols):
    """Third-party headlines (Yahoo) for SPY, and next earnings dates for the strategy's stocks."""
    import yfinance as yf
    news = []
    try:
        for it in (yf.Ticker("SPY").news or [])[:12]:
            c = it.get("content", it)
            t = c.get("pubDate") or c.get("providerPublishTime")
            if isinstance(t, (int, float)):
                t = datetime.fromtimestamp(t, timezone.utc).isoformat()
            news.append({"title": c.get("title"), "publisher": (c.get("provider") or {}).get("displayName") or c.get("publisher"),
                         "time": t, "url": ((c.get("canonicalUrl") or {}).get("url") or c.get("link"))})
    except Exception:  # noqa: BLE001 - headlines are optional; the page says when they are missing
        news = []
    earnings = []
    for s in symbols:
        try:
            cal = yf.Ticker(s).calendar or {}
            d = cal.get("Earnings Date") if isinstance(cal, dict) else None
            future = [pd.Timestamp(x) for x in (d or []) if pd.Timestamp(x) >= pd.Timestamp.now().normalize()]
            if future:
                earnings.append({"sym": s, "date": str(min(future).date())})
        except Exception:  # noqa: BLE001
            continue
    earnings.sort(key=lambda e: e["date"])
    return [n for n in news if n["title"]], earnings


# ---------------------------------------------------------------- risk of the paper book

def book_weights(state_dir):
    path = os.path.join(state_dir, "positions.csv")
    if not os.path.exists(path):
        return None, None
    p = pd.read_csv(path)
    p = p[(p["date"] == p["date"].max()) & (p["sleeve"] == "equity")]
    if p.empty:
        return None, None
    w = p.set_index("symbol")["weight"].astype(float)
    return w[w.abs() > 1e-6], str(p["date"].iloc[0])


def var_block(w, rets, spy_ret, nav, sims=20000, seed=0):
    """1-day and 10-day VaR / ES at 95% and 99% by five methods, plus tail and dependence statistics."""
    R = rets[w.index].iloc[-756:].dropna(how="all").fillna(0)
    pr = (R @ w.values)
    out = {"methods": {}, "nav": nav}
    q = {0.95: N01_inv(0.95), 0.99: N01_inv(0.99)}
    hist2 = pr.iloc[-504:]
    s, k = float(pr.skew()), float(pr.kurt())
    mu, sd = float(pr.mean()), float(pr.std())
    # Filtered historical simulation: GARCH on the book's own return history, bootstrapped standardized residuals.
    from .vol import garch_fit
    f = garch_fit(pr.values[:, None])
    a, b, s2 = f["a"][0], f["b"][0], f["s2"][0]
    h, hs = s2, []
    x = pr.values - pr.mean()
    for v in x:
        hs.append(h)
        h = s2 * (1 - a - b) + a * v * v + b * h
    z = x / np.sqrt(hs)
    rng = np.random.default_rng(seed)
    paths = np.zeros(5000)
    hh = np.full(5000, h)
    for _ in range(10):
        e = rng.choice(z, 5000) * np.sqrt(hh)
        paths += e
        hh = s2 * (1 - a - b) + a * e * e + b * hh
    fhs1 = math.sqrt(h) * rng.choice(z, 20000)
    # Monte Carlo: multivariate Student-t (5 degrees of freedom) with GARCH volatilities and the 252-day correlation.
    g = garch_vol(rets[w.index].iloc[-756:], horizon=1).fillna(R.iloc[-63:].std()).values
    C = R.iloc[-252:].corr().fillna(0).values
    C = 0.7 * C + 0.3 * np.eye(len(g))
    np.fill_diagonal(C, 1.0)
    L = np.linalg.cholesky(C)
    nu = 5
    t = rng.standard_normal((sims, len(g))) @ L.T / np.sqrt(rng.chisquare(nu, (sims, 1)) / nu) * math.sqrt((nu - 2) / nu)
    mc1 = (t * g) @ w.values
    for lvl in (0.95, 0.99):
        zq = q[lvl]
        cf = zq + (zq ** 2 - 1) * s / 6 + (zq ** 3 - 3 * zq) * k / 24 - (2 * zq ** 3 - 5 * zq) * s * s / 36
        hq = -np.quantile(hist2, 1 - lvl)
        methods = {
            "Historical (2 years)": (hq, -hist2[hist2 <= -hq].mean(), -np.quantile(hist2.rolling(10).sum().dropna(), 1 - lvl)),
            "Parametric normal": (zq * sd - mu, sd * math.exp(-zq * zq / 2) / math.sqrt(2 * math.pi) / (1 - lvl) - mu, zq * sd * math.sqrt(10)),
            "Cornish-Fisher": (cf * sd - mu, None, cf * sd * math.sqrt(10)),
            "Filtered historical (GARCH)": (-np.quantile(fhs1, 1 - lvl), -fhs1[fhs1 <= np.quantile(fhs1, 1 - lvl)].mean(), -np.quantile(paths, 1 - lvl)),
            "Monte Carlo (Student-t, GARCH)": (-np.quantile(mc1, 1 - lvl), -mc1[mc1 <= np.quantile(mc1, 1 - lvl)].mean(),
                                               -np.quantile(mc1, 1 - lvl) * math.sqrt(10)),
        }
        for m, (v1, es1, v10) in methods.items():
            out["methods"].setdefault(m, {})[str(int(lvl * 100))] = {"var1": v1, "es1": es1, "var10": v10}
    eq = (1 + pr).cumprod()
    br = spy_ret.reindex(pr.index).fillna(0)
    hist_bins = np.histogram(paths, bins=40)  # 10-day filtered-historical P&L distribution
    out["tail"] = {"skew": s, "excess_kurtosis": k, "worst_day": float(pr.min()), "best_day": float(pr.max()),
                   "tail_ratio": float(abs(np.quantile(pr, 0.95) / np.quantile(pr, 0.05))), "max_drawdown_3y": float((eq / eq.cummax() - 1).min()),
                   "beta_spy": float(pr.cov(br) / br.var()), "corr_spy": float(pr.corr(br)), "vol_ann": sd * math.sqrt(252),
                   "garch": {"a": float(a), "b": float(b), "vol_now": math.sqrt(h * 252)}}
    out["dist10"] = {"edges": hist_bins[1].tolist(), "counts": hist_bins[0].tolist()}
    cm = R.iloc[-252:].corr()
    out["corr"] = {"syms": list(cm.columns), "m": cm.round(2).fillna(0).values.tolist()}
    out["exposure"] = {"gross": float(w.abs().sum()), "net": float(w.sum()), "names": len(w), "largest": float(w.abs().max())}
    return out


def N01_inv(p):
    return models.N01.inv_cdf(p)


# ---------------------------------------------------------------- portfolio construction

def allocations(R, alpha=None, cap=0.10, lam=5.0):
    """Long-only weights by six methods for the same covariance (GARCH volatilities, 252-day correlation)."""
    names = list(R.columns)
    n = len(names)
    g = garch_vol(R, horizon=21).fillna(R.iloc[-63:].std()).values * math.sqrt(252)
    C = R.iloc[-252:].corr().fillna(0).values
    C = 0.7 * C + 0.3 * np.eye(n)
    np.fill_diagonal(C, 1)
    S = g[:, None] * C * g[None, :]
    box = (np.vstack([np.eye(n), np.ones((1, n))]), np.r_[np.zeros(n), 1.0], np.r_[np.full(n, cap), 1.0])

    def qp(P, q, A=None, lo=None, hi=None):
        A, lo, hi = (box if A is None else (A, lo, hi))
        w = np.clip(solve_qp(P, q, A, lo, hi), 0, cap)
        return w / w.sum()

    W = {"Equal weight": np.full(n, 1 / n)}
    iv = 1 / g
    W["Inverse volatility (GARCH)"] = qp(np.eye(n), -iv / iv.sum())
    W["Minimum variance"] = qp(2 * S, np.zeros(n))
    x = solve_qp(2 * S, np.zeros(n), np.vstack([np.eye(n), g[None, :]]), np.r_[np.zeros(n), 1.0], np.r_[np.full(n, np.inf), 1.0])
    W["Maximum diversification"] = qp(np.eye(n), -np.clip(x, 0, None) / np.clip(x, 0, None).sum())
    w = np.full(n, 1 / n)
    for _ in range(500):  # equal risk contribution (Maillard, Roncalli & Teiletche 2010), fixed-point iteration
        rc = w * (S @ w)
        w = w * (rc.mean() / np.maximum(rc, 1e-12)) ** 0.5
        w /= w.sum()
    W["Risk parity (equal risk contribution)"] = np.minimum(w, cap) / np.minimum(w, cap).sum()
    if alpha is not None:
        W["Mean-variance (ensemble forecasts)"] = qp(lam * S, -alpha.reindex(names).fillna(0).values)
    out = []
    for m, w in W.items():
        vol = math.sqrt(w @ S @ w)
        rc = w * (S @ w) / (vol * vol)
        out.append({"method": m, "weights": {s: float(x) for s, x in zip(names, w) if x > 1e-4}, "vol": vol,
                    "div_ratio": float(w @ g / vol), "eff_n": float(1 / (w ** 2).sum()), "max_rc": float(rc.max())})
    return out


def allocation_backtest(prices, methods_fn, start="2016-01-01"):
    """Monthly walk-forward of each allocation method on fixed names, net of 7 bp per unit of turnover."""
    rets = prices.pct_change(fill_method=None)
    me = [d for d in prices.resample("ME").last().index if d >= pd.Timestamp(start)]
    me = [prices.index[prices.index.searchsorted(d, side="right") - 1] for d in me]
    series, prev = {}, {}
    for t0, t1 in zip(me[:-1], me[1:]):
        R = rets.loc[:t0].iloc[-756:].dropna(axis=1, thresh=500).fillna(0)
        if R.shape[1] < 5:
            continue
        period = rets.loc[t0:t1].iloc[1:][R.columns].fillna(0)
        grow = (1 + period).prod() - 1
        for a in methods_fn(R):
            w = pd.Series(a["weights"]).reindex(R.columns).fillna(0)
            cost = (w - prev.get(a["method"], w * 0).reindex(R.columns).fillna(0)).abs().sum() * strategies.STOCK_COST
            series.setdefault(a["method"], []).append((t1, float(w @ grow) - cost))
            prev[a["method"]] = w * (1 + grow) / (1 + float(w @ grow))
    return {m: pd.Series(dict(v)) for m, v in series.items()}


def leverage_sim(r, rf, levels=(1.0, 1.5, 2.0, 3.0), years=1, paths=2000, block=21, seed=0):
    """Strategy returns levered (borrowing at T-bills + 1%), block-bootstrapped one-year outcomes."""
    rng = np.random.default_rng(seed)
    rf = rf.reindex(r.index).fillna(0)
    out = []
    n = 252 * years
    for L in levels:
        lr = L * r - (L - 1) * (rf + 0.01 / 252)
        x = lr.values
        starts = rng.integers(0, len(x) - block, (paths, n // block))
        sims = np.array([np.prod(1 + np.concatenate([x[s:s + block] for s in row])) - 1 for row in starts])
        eq = (1 + lr).cumprod()
        out.append({"leverage": L, "cagr": float(eq.iloc[-1] ** (252 / len(lr)) - 1), "vol": float(lr.std() * math.sqrt(252)),
                    "maxdd": float((eq / eq.cummax() - 1).min()), "p_loss_20": float((sims < -0.2).mean()),
                    "p_loss_50": float((sims < -0.5).mean()), "median_1y": float(np.median(sims))})
    ex = r - rf
    sd_ann = float(r.std() * math.sqrt(252))
    sr = float(ex.mean() / ex.std() * math.sqrt(252))
    se = math.sqrt((1 + sr * sr / 2) / (len(r) / 252))  # Lo (2002)
    kelly = sr / sd_ann  # f* = mu / sigma^2 = Sharpe / sigma
    return out, {"full": kelly, "half": kelly / 2, "sharpe": sr, "sharpe_se": se,
                 "low": max(0.0, sr - 1.96 * se) / sd_ann,
                 "note": "Kelly fraction f* = mean excess return / variance = Sharpe / volatility, from the backtest. It treats the "
                         "backtest's Sharpe as the true future one. At the lower 95% bound of that Sharpe the fraction is much "
                         "smaller, and on the fair point-in-time universe the strategy's edge is about zero, where Kelly is 0."}


# ---------------------------------------------------------------- forecasts

def track_a(close, rf_d):
    """SPY: every model's out-of-sample record and today's forecasts, per horizon. With a FRED key the macro
    features are point-in-time FRED / ALFRED data (test 6); without one, test 4's Yahoo stand-ins."""
    source = "Yahoo market prices (test 4)"
    features = None
    if os.environ.get("FRED_API_KEY"):
        from . import macro
        tech, lp0, _ = models.technical_features(close["SPY"].dropna())
        rows = models.weekly_rows(lp0.index[lp0.index >= "2006-01-01"])
        market, vint = macro.load_fred()
        features = tech[macro.TECHNICAL].reindex(rows).join(macro.macro_features(market, vint, rows))
        source = "FRED / ALFRED, as known on each date (test 6)"
    P, F, lp = models.walk_forward_market(close, features=features)
    r = lp.diff()
    out = {"features": list(F.columns), "feature_source": source, "asof": str(lp.index[-1].date()), "horizons": {}}
    for h, df in P.items():
        ev = models.evaluate(df, h)
        today = df.iloc[-1]
        sigma = float(garch_vol(r.dropna().to_frame("SPY"), horizon=h).iloc[0] * math.sqrt(h))
        sc = models.scenarios(df, h, sigma, float(today[models.ENSEMBLE]))
        e = ev[models.ENSEMBLE]
        rules = [("Out-of-sample R² above 0 and Diebold-Mariano p < 0.05", e["r2_oos"] > 0 and e["dm_p"] < 0.05,
                  f"R² {e['r2_oos']:+.2%}, DM p {e['dm_p']:.2f}"),
                 ("Hit rate above 50%, binomial p < 0.05", e["hit"] > 0.5 and e["hit_p"] < 0.05,
                  f"{e['hit']:.1%} of {e['n']} forecasts ({e['n_eff']} independent), p {e['hit_p']:.2f}")]
        hist = df.dropna(subset=["y"]).iloc[-260:]
        out["horizons"][str(h)] = {
            "today": {m: float(today[m]) for m in df.columns if m != "y"}, "eval": ev, "sigma": sigma, "scenarios": sc,
            "rules": rules, "passed": all(x[1] for x in rules),
            "history": {"dates": [str(d.date()) for d in hist.index], "forecast": hist[models.ENSEMBLE].round(5).tolist(),
                        "realized": hist["y"].round(5).tolist()}}
    return out


def track_b(res, n_trials=33):
    """Point-in-time S&P 500: every model's out-of-sample record, test-2 rules on the ensemble, and
    today's forecasts for current members."""
    close, monthly, fwd, el = res["close"], res["monthly"], res["fwd"], res["eligible"]
    members = pit.member_mask(pit.membership(), monthly.index, list(monthly.columns))
    vol = pit.load_prices(list(monthly.columns))["Volume"].reindex(columns=monthly.columns)
    ranked = models.panel_features(close, vol, monthly, members)
    elig_all = members & monthly.notna()
    preds = models.panel_walk_forward(ranked, fwd, elig_all)
    dv = (close * vol).rolling(63, min_periods=40).mean().reindex(monthly.index)
    liquid = dv.ge(dv.where(elig_all).median(axis=1), axis=0)
    test = [t for t in el.index if t >= pd.Timestamp("2016-01-01")]
    E = el.loc[test]
    rows, ens = {}, None
    for m, P in preds.items():
        sig = P.reindex(index=test, columns=E.columns)
        s, b, ic = pit.simulate(sig, fwd.loc[test], E)
        a = (s - b).dropna()
        rows[m] = {"ic": float(ic.mean()), "ic_t": float(ic.mean() / ic.std() * math.sqrt(len(ic))), "ir": pit.ir(a),
                   "t": pit.ir(a) * math.sqrt(len(a) / 12), "active": float(a.mean() * 12), "months": len(a)}
        if m == models.ENSEMBLE:
            ens = (sig, s, b, ic, a)
    sig, s, b, ic, a = ens
    yrs = len(a) / 12
    trial_srs = [x["ir"] / math.sqrt(12) for x in rows.values() if x["ir"] == x["ir"]] + [v / math.sqrt(12) for v in pit.prior_grid_irs()]
    dsr, _ = research.deflated_sharpe(a, trial_srs, n_trials)
    per = {k: pit.ir(a[(a.index.year >= y0) & (a.index.year <= y1)]) for k, (y0, y1) in
           {"2016–19": (2016, 2019), "2020–22": (2020, 2022), "2023–now": (2023, 2100)}.items()}
    halves = {}
    for h, m in (("liquid", liquid), ("less liquid", ~liquid)):
        hs, hb, _ = pit.simulate(sig, fwd.loc[test], E & m.loc[test])
        halves[h] = pit.ir(hs - hb)
    ic_t = ic.mean() / ic.std() * math.sqrt(len(ic))
    rules = [
        ("1. Signal", ic.mean() > 0 and ic_t >= 2, f"IC {ic.mean():+.3f}, t {ic_t:+.1f}"),
        ("2. Edge vs equal weight", pit.ir(a) * math.sqrt(yrs) >= 2, f"IR {pit.ir(a):+.2f}, t {pit.ir(a) * math.sqrt(yrs):+.1f} over {yrs:.1f} years"),
        ("3. Deflated", dsr >= 0.95, f"{dsr:.0%} after {n_trials} trials"),
        ("4. Stability", sum(v > 0 for v in per.values()) >= 2, ", ".join(f"{k} {v:+.2f}" for k, v in per.items())),
        ("5. Breadth", all(v > 0 for v in halves.values()), ", ".join(f"{k} {v:+.2f}" for k, v in halves.items())),
        ("6. Coverage", res["coverage"] >= 0.90, f"{res['coverage']:.1%} of member-months priced"),
    ]
    last = monthly.index[-1]
    cur = [t for t, sp in pit.membership().items() if any(e is None for _, e in sp) and t in monthly.columns]
    today = {m: P.reindex(columns=cur).iloc[-1] for m, P in preds.items() if last in P.index}
    eq_s, eq_b = (1 + s).cumprod(), (1 + b).cumprod()
    return {"models": rows, "rules": rules, "passed": all(x[1] for x in rules), "asof": str(last.date()),
            "curve": {"dates": [str(d.date()) for d in eq_s.index], "strategy": eq_s.round(4).tolist(), "bench": eq_b.round(4).tolist()},
            "today": today}


def stock_forecasts(today, close, ic, horizon=21):
    """Today's one-month forecasts for current S&P 500 members: Grinold's rule on the ensemble's rank,
    GARCH volatility, model agreement, and bull / base / bear moves (90th / 50th / 10th percentile)."""
    if not today or models.ENSEMBLE not in today:
        return []
    ens = today[models.ENSEMBLE].dropna()
    z = (ens - ens.mean()) / ens.std()
    rets = close[ens.index].pct_change(fill_method=None)
    sig = garch_vol(rets.iloc[-756:], horizon).fillna(rets.iloc[-63:].std()) * math.sqrt(horizon)
    model_ranks = pd.DataFrame({m: v.reindex(ens.index).rank(pct=True) for m, v in today.items() if m != models.ENSEMBLE})
    agree = 1 - model_ranks.std(axis=1) / 0.29  # 1 = every model ranks it alike; 0.29 = std of independent uniform ranks
    rows = []
    for s in ens.index:
        if not np.isfinite(sig.get(s, np.nan)):
            continue
        mu = ic * sig[s] * z[s]
        bull, bear = mu + 1.2816 * sig[s], mu - 1.2816 * sig[s]
        rows.append({"sym": s, "name": name(s), "sector": sector(s), "rank": float(ens[s]), "fc": mu, "bull": bull, "bear": bear,
                     "sigma": float(sig[s]), "agree": float(agree.get(s, np.nan)), "rr": float(bull / abs(bear)) if bear < 0 else None})
    rows.sort(key=lambda r: -r["fc"])
    return rows


# ---------------------------------------------------------------- build

def pit_cache_stale(days=3):
    if not os.path.exists(pit.CACHE):
        return True
    c = pd.read_pickle(pit.CACHE)  # our own cache file (see pit.load_prices)
    return (pd.Timestamp.now() - c.index[-1]).days > days


def main(state_dir=os.path.join(ROOT, "state"), site_dir=os.path.join(ROOT, "site")):
    built = now()
    lc = load_config(os.path.join(ROOT, "live.json"))
    raw = download(sorted(set(MACRO + list(SECTOR_ETFS))), "2005-01-01")
    c = raw["Close"].ffill()
    rf_d = risk_free(raw, 252).fillna(0)

    res = pit.run_test(refresh=pit_cache_stale())
    pclose, pvol = res["close"], pit.load_prices(list(res["close"].columns))["Volume"]
    spells = pit.membership()
    current = [t for t, sp in spells.items() if any(e is None for _, e in sp)]

    intel = market_intel(c, raw["Volume"], pclose, pvol, current)
    news, earnings = news_and_earnings(DEFAULT_UNIVERSE)

    A = track_a(c, rf_d)
    B = track_b(res)
    fc_stocks = stock_forecasts(B.pop("today"), pclose, B["models"][models.ENSEMBLE]["ic"])

    # Strategy lab.
    rf_m = (1 + rf_d).resample("ME").prod() - 1
    rf_m.index = [pclose.index[min(len(pclose) - 1, pclose.index.searchsorted(d, side="right") - 1)] for d in rf_m.index]
    rf_m = rf_m[~rf_m.index.duplicated()]
    garch_spy = models.garch_filtered_vol(np.log(c["SPY"]).diff())
    zoo = {}
    for nm, (net, gross, _) in strategies.spy_strategies(c["SPY"].dropna(), rf_d, garch_spy).items():
        zoo[nm] = ("SPY, daily", net.loc["2010":], gross.loc["2010":], 252)
    test = res["eligible"].index
    E, fwd, monthly = res["eligible"], res["fwd"].loc[test], res["monthly"]
    sig = {k: v.loc[test] for k, v in res["sigs"].items()}
    vol63 = -pclose.pct_change(fill_method=None).rolling(63, min_periods=40).std().reindex(monthly.index).loc[test]
    rev = -(monthly / monthly.shift(1) - 1).loc[test]
    comp = sum(x.rank(axis=1, pct=True) for x in (sig["A. Momentum 12-1"], vol63, rev)) / 3
    xs = {"Momentum, long-only top 20%": (sig["A. Momentum 12-1"], False), "Momentum, market-neutral long/short": (sig["A. Momentum 12-1"], True),
          "Short-term reversal, long/short": (rev, True), "Low volatility, long-only": (vol63, False),
          "Multi-factor (momentum + low vol + reversal)": (comp, False)}
    for nm, (s_, ls) in xs.items():
        net, gross = strategies.xs_portfolio(s_, fwd, E, rf_m, long_short=ls)
        zoo[nm] = ("Point-in-time S&P 500, monthly", net, gross, 12)
    ew = pit.simulate(sig["A. Momentum 12-1"], fwd, E)[1]
    zoo["Equal weight S&P 500 (benchmark)"] = ("Point-in-time S&P 500, monthly", ew, None, 12)
    sp100 = [s for s in SP100 if s in pclose.columns]
    pairs = strategies.pairs_trading(pclose[sp100].loc["2013":].ffill(limit=5), {s: sector(s) for s in sp100})
    zoo["Pairs trading (distance method)"] = ("Today's S&P 100, daily (survivorship-biased)", pairs, None, 252)
    from .live import load_crypto
    cp, _ = load_crypto({**lc, "crypto": {**lc["crypto"], "enabled": True}})
    cres = run_backtest(cp, Config(**lc["crypto"]["strategy"]), cp["BTC/USD"])
    t0c = metrics.first_trade(cres)
    zoo["Crypto trend (live sleeve)"] = ("8 coins, daily (survivorship-biased)", cres.returns.loc[t0c:], cres.gross_returns.loc[t0c:], 365)
    zoo["Bitcoin buy and hold"] = ("BTC, daily", cres.benchmark.loc[t0c:], None, 365)
    table, curves = [], {}
    for nm, (uni, net, gross, ppy) in zoo.items():
        rf = rf_d if uni.startswith("SPY") else (rf_m if ppy == 12 else None)
        p = strategies.perf(net, rf, ppy, gross)
        if not p:
            continue
        table.append({"name": nm, "universe": uni, **p})
        eq = (1 + net.dropna()).cumprod()
        eq = eq.resample("ME").last() if ppy != 12 else eq
        curves[nm] = {"dates": [str(d.date()) for d in eq.index], "v": eq.round(4).tolist()}
    table.sort(key=lambda r: -(r["sharpe"] if r["sharpe"] == r["sharpe"] else -9))

    # Paper-book risk.
    w, wdate = book_weights(state_dir)
    nav = None
    eqcsv = os.path.join(state_dir, "equity.csv")
    if os.path.exists(eqcsv):
        nav = float(pd.read_csv(eqcsv).iloc[-1]["equity"])
    prets = pclose.pct_change(fill_method=None)
    risk = None
    if w is not None:
        w = w[[s for s in w.index if s in prets.columns]]
        risk = var_block(w, prets, c["SPY"].pct_change(), nav)
        risk["asof"] = wdate

    # Portfolio construction on the strategy's 30 names, and leverage of the live strategy.
    names30 = [s for s in DEFAULT_UNIVERSE if s in pclose.columns]
    R30 = prets[names30].iloc[-756:].dropna(axis=1, thresh=500).fillna(0)
    alpha = pd.Series({r["sym"]: r["fc"] * 12 for r in fc_stocks})
    alloc = allocations(R30, alpha)
    bt = allocation_backtest(pclose[names30], lambda R: allocations(R))
    alloc_bt = [{"method": m, **(strategies.perf(s, rf_m, 12) or {})} for m, s in bt.items()]
    from .data import load_prices
    p30, bench = load_prices(DEFAULT_UNIVERSE, None, raw=download(DEFAULT_UNIVERSE + ["SPY"], "2014-01-01"))
    live_bt = run_backtest(p30, Config(**lc["strategy"]), bench, rf_d.reindex(p30.index).fillna(0))
    t0 = metrics.first_trade(live_bt)
    lev, kelly = leverage_sim(live_bt.returns.loc[t0:], rf_d)

    # Alerts: rule-based, research only.
    alerts = []
    rg = intel["regime"]
    if rg["vix_inverted"]:
        alerts.append(("warn", "VIX above VIX3M: the volatility curve is inverted, typical of market stress"))
    if not rg["trend_up"]:
        alerts.append(("warn", f"SPY is {abs(rg['spy_vs_200d']):.1%} below its 200-day average"))
    if rg["vol_pct_10y"] and rg["vol_pct_10y"] > 0.9:
        alerts.append(("warn", f"SPY GARCH volatility {rg['garch_vol']:.0%} is in its top 10% of 10 years"))
    for a_ in intel["anomalies"][:5]:
        alerts.append(("info", f"{a_['sym']} moved {a_['ret']:+.1%} today ({a_['ret_z']:+.1f} standard deviations)"))
    if risk:
        var99 = risk["methods"]["Filtered historical (GARCH)"]["99"]["var1"]
        if var99 > 0.04:
            alerts.append(("warn", f"Book 1-day 99% VaR {var99:.1%} (filtered historical)"))
    h21 = A["horizons"]["21"]
    alerts.append(("info", f"Ensemble 1-month SPY forecast {h21['today'][models.ENSEMBLE]:+.2%} "
                           f"(80% range {h21['scenarios']['lo80']:+.1%} to {h21['scenarios']['hi80']:+.1%}); "
                           f"out-of-sample R² {h21['eval'][models.ENSEMBLE]['r2_oos']:+.1%}. Research only, not traded."))

    sources = [
        {"data": "Macro series as first published (payrolls, unemployment, CPI, production, claims, conditions, permits) and market rates",
         "source": "FRED / ALFRED (St. Louis Fed), vintages" if os.environ.get("FRED_API_KEY") else "not loaded (no FRED key in this build)",
         "asof": built[:10], "kind": "DATA"},
        {"data": "Company fundamentals: equity, shares, EPS, net income, assets, with filing dates",
         "source": "SEC EDGAR XBRL (data/fundamental_events.csv.gz; tested in RESEARCH_7, no edge found)", "asof": "research run", "kind": "DATA"},
        {"data": "Daily prices, volumes, VIX, Treasury yields, ETFs, futures", "source": "Yahoo Finance (yfinance), adjusted",
         "asof": str(c.index[-1].date()), "kind": "DATA"},
        {"data": "Point-in-time S&P 500 membership", "source": "github.com/fja05680/sp500 (MIT licence)", "asof": "data/sp500_ticker_start_end.csv", "kind": "DATA"},
        {"data": "Point-in-time S&P 500 prices and volumes", "source": "Yahoo Finance", "asof": str(pclose.index[-1].date()), "kind": "DATA"},
        {"data": "Paper-book positions", "source": "state/positions.csv, written from Alpaca after each trading run", "asof": wdate, "kind": "DATA"},
        {"data": "Headlines", "source": "Yahoo Finance news (third-party, not verified here)", "asof": built[:10], "kind": "DATA"},
        {"data": "Earnings dates", "source": "Yahoo Finance calendar", "asof": built[:10], "kind": "DATA"},
        {"data": "Forecasts, scenarios, VaR, regime, allocations, strategy results", "source": "models in this repository", "asof": built, "kind": "MODEL"},
    ]
    controls = [
        "Point-in-time S&P 500 membership for every cross-sectional test (no hindsight universe).",
        "Purged walk-forward: every model is refitted each January on data whose target ended before that date.",
        "The rules of every test were committed to git before it ran (docs/PREREGISTRATION*.md).",
        "Deflated Sharpe ratios count every configuration tried in the project (43 by test 7).",
        "Costs: 2 bp per unit of turnover for SPY, 7 bp for stocks, 0.5% a year to borrow shares, T-bills + 1% to borrow cash.",
        "A signal at a close trades at the next close (daily) or holds for the next month (monthly); no same-bar fills.",
        "Survivorship-biased results are labelled: pairs trading (today's S&P 100), crypto (today's coins), allocations (today's 30 names).",
    ]
    lab = {"built": built, "sources": sources, "unavailable": [{"item": a, "why": b} for a, b in UNAVAILABLE], "controls": controls,
           "intel": intel, "news": news, "earnings": earnings, "forecast_market": A, "forecast_xs": B,
           "stocks": fc_stocks, "strategies": table, "curves": curves, "risk": risk,
           "allocations": alloc, "allocation_backtest": alloc_bt, "leverage": lev, "kelly": kelly,
           "alerts": [{"level": l_, "text": t_} for l_, t_ in alerts]}
    _write(os.path.join(site_dir, "lab.json"), lab)
    write_report(A, B, table)
    print("wrote site/lab.json and docs/RESEARCH_4.md")
    print("track A:", {h: v["passed"] for h, v in A["horizons"].items()}, "| track B:", B["passed"])


def write_report(A, B, table):
    L = ["# Research report 4: multi-model forecasting", "",
         f"Generated {datetime.now(timezone.utc).date()} by `python -m alphaforge.lab`. Rules committed before the run: "
         "[PREREGISTRATION_4.md](PREREGISTRATION_4.md).", "", "## Track A: SPY", "",
         "Weekly forecasts out of sample from January 2014; each model refitted every January on data whose target ended before it.", ""]
    for h, v in A["horizons"].items():
        L += [f"### {h} trading days", "", "| Model | Out-of-sample R² | DM p | Hit rate | RMSE |", "|---|---|---|---|---|"]
        for m, e in v["eval"].items():
            dm = "" if e["dm_p"] is None else f"{e['dm_p']:.2f}"
            L.append(f"| {m} | {e['r2_oos']:+.2%} | {dm} | {e['hit']:.1%} | {e['rmse']:.4f} |")
        L += ["", "| Rule (ensemble) | Result | Evidence |", "|---|---|---|"]
        L += [f"| {n} | {'pass' if ok else '**fail**'} | {ev} |" for n, ok, ev in v["rules"]] + [""]
    L += ["## Track B: point-in-time S&P 500 cross-section", "",
          "| Model | Rank IC | IC t | Top 20% vs equal weight, IR | t |", "|---|---|---|---|---|"]
    for m, e in B["models"].items():
        L.append(f"| {m} | {e['ic']:+.3f} | {e['ic_t']:+.1f} | {e['ir']:+.2f} | {e['t']:+.1f} |")
    L += ["", "| Rule (ensemble) | Result | Evidence |", "|---|---|---|"]
    L += [f"| {n} | {'pass' if ok else '**fail**'} | {ev} |" for n, ok, ev in B["rules"]]
    a_pass = [h for h, v in A["horizons"].items() if v["passed"]]
    L += ["", "## Verdict", "",
          ("Track A: out-of-sample skill over the historical mean at " + ", ".join(a_pass) + " days. " if a_pass else
           "Track A: no horizon shows out-of-sample skill over the historical mean. ")
          + ("Track B: passes; a change could be proposed for your approval." if B["passed"] else
             "Track B: fails; the live strategy is unchanged."), "",
          "## Amendment: first run", "",
          "The first run (21 November 2026) had a defect: the neural network's target was not standardized and its "
          "forecasts diverged. Its out-of-sample R² was −1,696% (5 days), −669% (21 days) and −291% (63 days), which "
          "dragged the ensemble to −46%, −19% and −6%. Every rule failed in that run too. The tables above are after the "
          "fix ([PREREGISTRATION_4.md](PREREGISTRATION_4.md), amendment); a pass appearing only after the fix would be "
          "exploratory, not demonstrated.", "",
          "## Strategy lab", "", "| Strategy | Universe | Sharpe | Sortino | CAGR | Max DD | Since |", "|---|---|---|---|---|---|---|"]
    for r in table:
        L.append(f"| {r['name']} | {r['universe']} | {r['sharpe']:.2f} | {(r['sortino'] or 0):.2f} | {r['cagr']:.1%} | {r['maxdd']:.1%} | {r['start']} |")
    with open(os.path.join(ROOT, "docs", "RESEARCH_4.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
