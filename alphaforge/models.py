"""Multi-model forecasting with purged walk-forward validation (pre-registered test 4).

Track A: SPY's log return over 5, 21 and 63 trading days from macro and technical features, sampled weekly.
Track B: each point-in-time S&P 500 member's next-month return relative to the average member.

Every model is refitted each January on data whose target ended before that date, then scored only on
the following year. The historical mean is the benchmark; out-of-sample R2 is measured against it
(Campbell & Thompson 2008) and its significance by the Diebold-Mariano test with a Newey-West variance.
"""
import math
from statistics import NormalDist

import numpy as np
import pandas as pd

from .vol import garch_fit

N01 = NormalDist()
HORIZONS = (5, 21, 63)
LEARNERS = ("Ridge regression", "Random forest", "Gradient boosting", "Neural network")
ENSEMBLE = "Ensemble"


# ---------------------------------------------------------------- learners (specs fixed by the pre-registration)

def make_learner(name, seed=0):
    from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.neural_network import MLPRegressor
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    if name == "Ridge regression":
        return make_pipeline(StandardScaler(), Ridge(alpha=10.0))
    if name == "Random forest":
        return RandomForestRegressor(n_estimators=300, max_depth=4, min_samples_leaf=50, n_jobs=-1, random_state=seed)
    if name == "Gradient boosting":
        return HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=200, random_state=seed)
    if name == "Neural network":
        # Inputs and the target are both standardized: returns of about 0.01 are too small a scale for the
        # network's initialization (the first run, without target scaling, diverged; see PREREGISTRATION_4).
        from sklearn.compose import TransformedTargetRegressor
        return TransformedTargetRegressor(
            regressor=make_pipeline(StandardScaler(), MLPRegressor(hidden_layer_sizes=(32, 16), early_stopping=True,
                                                                    max_iter=500, random_state=seed)),
            transformer=StandardScaler())
    raise ValueError(name)


# ---------------------------------------------------------------- track A features

def garch_filtered_vol(r, start_year=2008, min_obs=500):
    """Daily GARCH(1,1) volatility with parameters refitted each January on prior data only, then filtered
    forward through the year: h_t = s2 (1 - a - b) + a r_{t-1}^2 + b h_{t-1}."""
    r = r.dropna()
    out = pd.Series(np.nan, index=r.index)
    h = None
    for y in range(max(start_year, r.index[0].year + 2), r.index[-1].year + 1):
        past = r[r.index < f"{y}-01-01"]
        cur = r[(r.index >= f"{y}-01-01") & (r.index < f"{y + 1}-01-01")]
        if len(past) < min_obs or not len(cur):
            continue
        f = garch_fit(past.iloc[-756:].values[:, None])
        a, b, s2 = f["a"][0], f["b"][0], f["s2"][0]
        h = f["h_next"][0] if h is None else h
        x = cur.values - past.iloc[-756:].mean()
        hs = []
        for v in x:
            hs.append(h)
            h = s2 * (1 - a - b) + a * v * v + b * h
        out[cur.index] = np.sqrt(np.array(hs) * 252)
    return out


def technical_features(spy):
    """SPY's own features: past returns, distance from its 200-day average, realized and GARCH volatility."""
    lp = np.log(spy)
    r = lp.diff()
    f = pd.DataFrame({
        "ret_5d": lp - lp.shift(5), "ret_21d": lp - lp.shift(21), "ret_63d": lp - lp.shift(63), "ret_252d": lp - lp.shift(252),
        "vs_200d_avg": lp - np.log(spy.rolling(200).mean()),
        "realized_vol_21d": r.rolling(21).std() * math.sqrt(252),
        "garch_vol": garch_filtered_vol(r)})
    return f, lp, r


def market_features(close):
    """Daily feature frame and log price for SPY, from a Close frame with Yahoo columns (test 4's features)."""
    c = close.ffill()
    tech, lp, r = technical_features(c["SPY"])
    f = tech.assign(**{
        "vix": c["^VIX"], "vix_21d_change": c["^VIX"] - c["^VIX"].shift(21),
        "term_spread": c["^TNX"] - c["^IRX"],
        "credit_63d": np.log(c["HYG"] / c["IEF"]) - np.log(c["HYG"] / c["IEF"]).shift(63),
        "dollar_63d": np.log(c["DX-Y.NYB"] / c["DX-Y.NYB"].shift(63)),
        "oil_63d": (c["CL=F"] / c["CL=F"].shift(63) - 1).clip(-1, 3),
    })
    return f, lp, r


def weekly_rows(index):
    """Last trading day of each week, plus the latest day (for today's forecast)."""
    s = pd.Series(index, index=index)
    w = list(s.groupby(index.to_period("W-FRI")).last().values)
    if w[-1] != index[-1]:
        w.append(index[-1])
    return pd.DatetimeIndex(w)


# ---------------------------------------------------------------- ARIMA(p,1,0) = AR(p) on daily log returns

def ar_fit(r, max_p=5):
    """OLS AR(p) with intercept on daily returns, p chosen by AIC. Returns (p, coefs)."""
    r = np.asarray(r.dropna(), float)
    best = None
    for p in range(1, max_p + 1):
        Y = r[p:]
        X = np.column_stack([np.ones(len(Y))] + [r[p - k:len(r) - k] for k in range(1, p + 1)])
        beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
        resid = Y - X @ beta
        aic = len(Y) * math.log(resid.var()) + 2 * (p + 1)
        if best is None or aic < best[0]:
            best = (aic, p, beta)
    return best[1], best[2]


def ar_forecast(hist, p, beta, h):
    """Sum of the next h iterated AR forecasts of daily returns."""
    x = list(np.asarray(hist[-p:], float))
    total = 0.0
    for _ in range(h):
        nxt = beta[0] + sum(beta[k] * x[-k] for k in range(1, p + 1))
        x.append(nxt)
        total += nxt
    return total


# ---------------------------------------------------------------- track A walk-forward

def walk_forward_market(close, first_oos=2014, horizons=HORIZONS, models=LEARNERS, features=None):
    """Returns ({h: frame of forecasts by model with the realized target 'y'}, features, log price).
    `features`: a ready-made feature frame indexed by forecast dates (test 6); otherwise test 4's features."""
    if features is None:
        F, lp, r = market_features(close)
    else:
        _, lp, r = technical_features(close["SPY"].ffill())
        F = features
    idx = lp.index
    pos = pd.Series(np.arange(len(idx)), index=idx)
    rows = weekly_rows(idx[idx >= F.dropna().index[0]]) if features is None else F.dropna().index
    out = {}
    for h in horizons:
        y = (lp.shift(-h) - lp)
        ends = pd.Series(idx[np.minimum(pos.values + h, len(idx) - 1)], index=idx)  # when each target is known
        X = F.loc[rows].dropna()
        frames = []
        for year in range(first_oos, idx[-1].year + 1):
            cut = pd.Timestamp(f"{year}-01-01")
            tr = [t for t in X.index if ends[t] < cut and pos[t] + h < len(idx)]
            te = [t for t in X.index if cut <= t < pd.Timestamp(f"{year + 1}-01-01")]
            if len(tr) < 150 or not te:
                continue
            ytr = y[tr].values
            pred = pd.DataFrame(index=pd.DatetimeIndex(te))
            pred["Historical mean"] = ytr.mean()
            for name in models:
                m = make_learner(name)
                m.fit(X.loc[tr].values, ytr)
                pred[name] = m.predict(X.loc[te].values)
            p, beta = ar_fit(r[r.index < cut].iloc[-2520:])
            pred["ARIMA(p,1,0)"] = [ar_forecast(r[r.index <= t].values, p, beta, h) for t in te]
            pred["Momentum rule"] = np.where(X.loc[te, "ret_252d"] > 0, ytr.mean(), 0.0)
            frames.append(pred)
        P = pd.concat(frames)
        P[ENSEMBLE] = P[[*models, "ARIMA(p,1,0)", "Momentum rule"]].mean(axis=1)
        P["y"] = y.reindex(P.index)
        P.loc[[t for t in P.index if pos[t] + h >= len(idx)], "y"] = np.nan  # target not known yet
        out[h] = P
    return out, F, lp


# ---------------------------------------------------------------- evaluation

def newey_west_se(d, lag):
    d = np.asarray(d, float) - np.mean(d)
    n = len(d)
    v = d @ d / n
    for k in range(1, lag + 1):
        v += 2 * (1 - k / (lag + 1)) * (d[k:] @ d[:-k]) / n
    return math.sqrt(max(v, 1e-300) / n)


def evaluate(P, h, step=5):
    """Out-of-sample R2 vs the historical mean, Diebold-Mariano p, hit rate and its binomial p, RMSE."""
    E = P.dropna(subset=["y"])
    y, hm = E["y"].values, E["Historical mean"].values
    lag = max(1, math.ceil(h / step))
    n_eff = max(1, int(len(E) * min(1.0, step / h)))
    out = {}
    for m in [c for c in E.columns if c != "y"]:
        f = E[m].values
        r2 = 1 - ((y - f) ** 2).sum() / ((y - hm) ** 2).sum()
        d = (y - hm) ** 2 - (y - f) ** 2
        dm = d.mean() / newey_west_se(d, lag) if m != "Historical mean" else float("nan")
        hit = float((np.sign(f) == np.sign(y)).mean())
        z = (hit - 0.5) / math.sqrt(0.25 / n_eff)
        out[m] = {"r2_oos": float(r2), "dm_p": 1 - N01.cdf(dm) if dm == dm else None, "hit": hit,
                  "hit_p": 1 - N01.cdf(z), "rmse": float(np.sqrt(((y - f) ** 2).mean())), "n": int(len(E)), "n_eff": n_eff}
    return out


def scenarios(P, h, sigma_h, centre):
    """Bull / base / bear (90th / 50th / 10th percentile) and 80% / 95% intervals for today's forecast,
    from the out-of-sample forecast errors standardized by that period's volatility."""
    E = P.dropna(subset=["y"])
    err = (E["y"] - E[ENSEMBLE]).values
    z = err / np.std(err)
    q = {p: float(np.quantile(z, p)) for p in (0.025, 0.10, 0.5, 0.90, 0.975)}
    v = lambda p: centre + sigma_h * q[p]
    return {"bear": v(0.10), "base": v(0.5), "bull": v(0.90), "lo80": v(0.10), "hi80": v(0.90),
            "lo95": v(0.025), "hi95": v(0.975),
            "coverage80": float(((E["y"] >= E[ENSEMBLE] + np.std(err) * q[0.10]) & (E["y"] <= E[ENSEMBLE] + np.std(err) * q[0.90])).mean())}


# ---------------------------------------------------------------- track B: cross-sectional panel

def panel_features(close, vol, monthly, members):
    """Month-end features per stock, rank-normalized to [-1, 1] across members each month."""
    from . import pit
    r = close.pct_change(fill_method=None)
    mkt = r.where(members.reindex(r.index, method="ffill").fillna(False)).mean(axis=1)
    me = monthly.index
    f = {
        "mom_12_1": pit.momentum(monthly),
        "mom_6_1": monthly.shift(1) / monthly.shift(6) - 1,
        "rev_1m": -(monthly / monthly.shift(1) - 1),
        "high_52w": pit.high52(close, monthly),
        "vol_63d": -(r.rolling(63, min_periods=40).std().reindex(me)),
        "resid_mom": pit.residual_momentum(monthly, members & monthly.notna()),
        "max_ret_21d": -(r.rolling(21, min_periods=15).max().reindex(me)),
        "dollar_vol": np.log((close * vol).rolling(63, min_periods=40).mean().reindex(me)),
    }
    beta = {}  # 252-day beta to the equal-weighted members, at month-ends only
    rv, mv = r.values, mkt.values
    loc = r.index.get_indexer(me)
    for t, i in zip(me, loc):
        if i < 150:
            continue
        y, x = rv[max(0, i - 251):i + 1], mv[max(0, i - 251):i + 1]
        ok = np.isfinite(y) & np.isfinite(x)[:, None]
        n = ok.sum(0)
        xm = np.where(ok, x[:, None], 0).sum(0) / np.maximum(n, 1)
        dx = np.where(ok, x[:, None] - xm, 0)
        dy = np.where(ok, y - np.where(ok, y, 0).sum(0) / np.maximum(n, 1), 0)
        b = (dx * dy).sum(0) / np.maximum((dx * dx).sum(0), 1e-12)
        b[n < 150] = np.nan
        beta[t] = b
    f["beta_252d"] = -pd.DataFrame(beta, index=r.columns).T.reindex(me)
    elig = members & monthly.notna()
    ranked = {}
    for k, v in f.items():
        v = v.where(elig)
        ranked[k] = v.rank(axis=1, pct=True) * 2 - 1
    return ranked


def panel_walk_forward(ranked, fwd, eligible, first_oos=2016, models=LEARNERS):
    """Monthly cross-sectional forecasts. Returns {model: DataFrame months x stocks} of predictions."""
    names = list(ranked)
    months = eligible.index
    stack = pd.concat({k: v.reindex(index=months, columns=eligible.columns).stack(future_stack=True) for k, v in ranked.items()}, axis=1)
    target = fwd.reindex(index=months, columns=eligible.columns)
    target = target.sub(target.where(eligible).mean(axis=1), axis=0)  # relative to the average member
    stack["y"] = target.stack(future_stack=True)
    stack["el"] = eligible.stack(future_stack=True)
    stack = stack[stack["el"].fillna(False).astype(bool)].drop(columns="el")
    stack = stack.dropna(subset=names)
    preds = {m: [] for m in (*models, "Momentum rule")}
    for year in range(first_oos, months[-1].year + 1):
        cut = pd.Timestamp(f"{year}-01-01")
        tr_months = [t for t in months if t < cut][:-1]  # purge: the last month's target ends after the cut
        te_months = [t for t in months if cut <= t < pd.Timestamp(f"{year + 1}-01-01")]
        if not te_months:
            continue
        tr = stack[stack.index.get_level_values(0).isin(tr_months)].dropna(subset=["y"])
        te = stack[stack.index.get_level_values(0).isin(te_months)]
        if len(tr) < 5000 or te.empty:
            continue
        lo, hi = tr["y"].quantile([0.01, 0.99])
        ytr = tr["y"].clip(lo, hi).values
        for m in models:
            est = make_learner(m)
            est.fit(tr[names].values, ytr)
            preds[m].append(pd.Series(est.predict(te[names].values), index=te.index))
        preds["Momentum rule"].append(te["mom_12_1"])
    out = {}
    for m, parts in preds.items():
        if parts:
            out[m] = pd.concat(parts).unstack()
    ranks = [v.rank(axis=1, pct=True) for v in out.values()]
    out[ENSEMBLE] = sum(ranks) / len(ranks)
    return out
