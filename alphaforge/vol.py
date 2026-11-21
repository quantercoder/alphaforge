"""Volatility forecasting: GARCH(1,1) by maximum likelihood, and the 63-day sample it is tested against.

GARCH(1,1) (Bollerslev 1986), with variance targeting (Engle & Mezrich 1996):

    h_t = omega + a * r_{t-1}^2 + b * h_{t-1},      omega = s^2 (1 - a - b)

s^2 is the sample variance of the fitting window, so only (a, b) are estimated. They are found by
maximizing the Gaussian log-likelihood  -1/2 sum(log h_t + r_t^2 / h_t)  over a fine grid
(a in 0.01..0.25, b in 0.60..0.99, a + b < 0.999), for every asset at once: a grid is exact to its step,
never fails to converge, and needs no optimizer library.
"""
import numpy as np

A_GRID = np.round(np.arange(0.01, 0.26, 0.01), 2)
B_GRID = np.round(np.arange(0.60, 0.995, 0.01), 2)
_A, _B = np.meshgrid(A_GRID, B_GRID, indexing="ij")
_OK = (_A + _B) < 0.999
GRID_A, GRID_B = _A[_OK], _B[_OK]  # (C,)


def garch_fit(r):
    """r: T x N daily returns without gaps. Returns per-asset dict of arrays: a, b, s2, h_next, loglik."""
    r = np.asarray(r, float)
    r = r - r.mean(axis=0)
    s2 = r.var(axis=0, ddof=1)
    a, b = GRID_A[:, None], GRID_B[:, None]           # (C, 1)
    omega = s2[None, :] * (1 - a - b)                  # (C, N)
    h = np.broadcast_to(s2, omega.shape).copy()
    ll = np.zeros_like(omega)
    for t in range(r.shape[0]):
        r2 = r[t] ** 2
        ll -= 0.5 * (np.log(h) + r2 / h)
        h = omega + a * r2 + b * h                     # h is now the forecast for t + 1
    best = ll.argmax(axis=0)
    cols = np.arange(r.shape[1])
    return {"a": GRID_A[best], "b": GRID_B[best], "s2": s2, "h_next": h[best, cols], "loglik": ll[best, cols]}


def garch_forecast(fit, horizon):
    """Average daily variance over the next `horizon` days:
    h_{T+k} = s^2 + (a + b)^(k-1) (h_{T+1} - s^2), averaged over k = 1..horizon."""
    p = fit["a"] + fit["b"]
    k = np.arange(horizon)[:, None]
    return (fit["s2"] + p[None, :] ** k * (fit["h_next"] - fit["s2"])[None, :]).mean(axis=0)


def garch_vol(returns, horizon=21, window=756, min_obs=500):
    """Daily volatility forecast (average over the horizon) for each column of a returns DataFrame.
    Columns without `min_obs` complete days in the window get NaN (callers fall back to the sample)."""
    import pandas as pd
    w = returns.iloc[-window:]
    full = [c for c in w.columns if w[c].notna().sum() >= min_obs]
    out = pd.Series(np.nan, index=returns.columns)
    if full:
        x = w[full].dropna(how="any")
        if len(x) >= min_obs:
            out[full] = np.sqrt(garch_forecast(garch_fit(x.values), horizon))
        else:  # different start dates: fit each on its own complete tail
            for c in full:
                xc = w[c].dropna().values[:, None]
                out[c] = float(np.sqrt(garch_forecast(garch_fit(xc), horizon))[0])
    return out


def sample_vol(returns, lookback=63):
    return returns.iloc[-lookback:].std()


def qlike(realized_var, forecast_var):
    """Patton (2011) QLIKE loss for variance forecasts; 0 for a perfect forecast."""
    q = realized_var / forecast_var
    return q - np.log(q) - 1
