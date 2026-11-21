"""Strategy lab: classic quantitative strategies on equal terms, net of costs.

Universes, chosen to avoid hindsight where the data allows:
- time-series strategies trade SPY (an index fund: no survivorship bias);
- cross-sectional strategies use the point-in-time S&P 500 of pit.py (monthly);
- pairs trading uses today's S&P 100 (survivorship-biased; flagged on the page).

Every strategy decides at a close and trades at the next close or the next month, pays costs on turnover,
and earns the T-bill rate on cash.
"""
import math
from statistics import NormalDist

import numpy as np
import pandas as pd

N01 = NormalDist()
ETF_COST = 2 / 1e4      # SPY: commission-free, about 1 bp half-spread plus impact
STOCK_COST = 7 / 1e4    # as in the main backtest
BORROW = 0.005          # annual cost of borrowing shares for the short leg


# ---------------------------------------------------------------- metrics

def perf(r, rf=None, ppy=252, gross=None, n_trials=1, trial_srs=None):
    """Return metrics for a periodic return series (net of costs)."""
    r = r.dropna()
    if len(r) < 24:
        return None
    ex = r - (rf.reindex(r.index).fillna(0) if rf is not None else 0)
    eq = (1 + r).cumprod()
    years = len(r) / ppy
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std() * math.sqrt(ppy)
    sr = ex.mean() / ex.std() * math.sqrt(ppy) if ex.std() > 0 else float("nan")
    down = np.sqrt((ex.clip(upper=0) ** 2).mean())
    dd = (eq / eq.cummax() - 1).min()
    s, k = r.skew(), r.kurt() + 3
    srp = ex.mean() / ex.std() if ex.std() > 0 else 0.0  # per period
    psr = N01.cdf(srp * math.sqrt(len(r) - 1) / math.sqrt(max(1e-9, 1 - s * srp + (k - 1) / 4 * srp ** 2)))
    split = r.index >= "2020-01-01"
    half = lambda x: (x.mean() / x.std() * math.sqrt(ppy)) if len(x) > 24 and x.std() > 0 else None
    out = {"cagr": cagr, "vol": vol, "sharpe": sr, "sortino": ex.mean() / down * math.sqrt(ppy) if down > 0 else None,
           "maxdd": dd, "calmar": cagr / abs(dd) if dd < 0 else None, "win": float((r > 0).mean()), "skew": float(s),
           "psr": psr, "sharpe_pre2020": half(ex[~split]), "sharpe_2020on": half(ex[split]), "years": years,
           "start": str(r.index[0].date())}
    if gross is not None:
        out["cost_drag"] = float((gross.reindex(r.index).fillna(0) - r).mean() * ppy)
    return out


# ---------------------------------------------------------------- SPY time-series strategies (daily)

def _run_daily(w_signal, ret, rf, cost):
    """w_signal: weight decided at each close, traded at the next close. Returns (net, gross, turnover)."""
    w = w_signal.shift(1).fillna(0)
    gross = w * ret + (1 - w).clip(lower=0) * rf - (w - 1).clip(lower=0) * (rf + 0.01 / 252)  # leverage pays rf + 1%
    turn = w.diff().abs().fillna(w.abs())
    return gross - turn * cost, gross, turn


def rsi(close, n=2):
    d = close.diff()
    up, dn = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean(), (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def spy_strategies(spy, rf, garch_vol):
    """Buy and hold, trend following, volatility targeting and short-term mean reversion on SPY."""
    ret = spy.pct_change().fillna(0)
    rf = rf.reindex(spy.index).fillna(0)
    sma200, sma5 = spy.rolling(200).mean(), spy.rolling(5).mean()
    out = {}
    out["Buy and hold SPY"] = _run_daily(pd.Series(1.0, index=spy.index), ret, rf, ETF_COST)
    out["Trend following (200-day average)"] = _run_daily((spy > sma200).astype(float).where(sma200.notna(), 0), ret, rf, ETF_COST)
    vt = (0.15 / garch_vol.reindex(spy.index)).clip(upper=1.5).fillna(0)
    out["Volatility targeting (GARCH, 15%)"] = _run_daily(vt, ret, rf, ETF_COST)
    # Connors RSI(2): buy a short-term dip in an uptrend, sell on the bounce.
    x = rsi(spy, 2)
    pos, held = [], 0.0
    for t in spy.index:
        if held == 0 and x[t] < 10 and spy[t] > sma200[t]:
            held = 1.0
        elif held == 1 and spy[t] > sma5[t]:
            held = 0.0
        pos.append(held)
    out["Mean reversion (RSI-2 dips)"] = _run_daily(pd.Series(pos, index=spy.index), ret, rf, ETF_COST)
    return out


# ---------------------------------------------------------------- point-in-time cross-section (monthly)

def xs_portfolio(signal, fwd, eligible, rf_m, q=0.2, long_short=False, low=False):
    """Monthly quantile portfolio on point-in-time members. Long-only top q, or long top / short bottom q
    (each leg 100% of capital, cash earns rf, the short leg pays borrow). low=True ranks ascending."""
    net, gross, prev_l, prev_s = [], [], None, None
    for t in signal.index:
        el = eligible.loc[t] & signal.loc[t].notna()
        names = el[el].index
        if len(names) < 50:
            continue
        s = signal.loc[t, names] * (-1 if low else 1)
        r = fwd.loc[t, names].fillna(0.0)
        k = max(1, int(round(q * len(names))))
        top, bot = s.nlargest(k).index, s.nsmallest(k).index
        wl = pd.Series(1 / k, index=top)
        ws = pd.Series(1 / k, index=bot) if long_short else None
        cost = (wl.sub(prev_l, fill_value=0).abs().sum() if prev_l is not None else 1.0) * STOCK_COST
        g = float(wl @ r[top])
        if long_short:
            cost += (ws.sub(prev_s, fill_value=0).abs().sum() if prev_s is not None else 1.0) * STOCK_COST
            g = g - float(ws @ r[bot]) + rf_m.get(t, 0.0) - BORROW / 12
        net.append((t, g - cost))
        gross.append((t, g))
        prev_l = wl * (1 + r[top]) / (1 + float(wl @ r[top]))
        prev_s = ws * (1 + r[bot]) / (1 + float(ws @ r[bot])) if long_short else None
    f = lambda xs: pd.Series(dict(xs)).sort_index()
    return f(net), f(gross)


# ---------------------------------------------------------------- pairs trading (distance method)

def pairs_trading(close, sectors, form=252, trade=126, n_pairs=10, entry=2.0, cost=STOCK_COST):
    """Gatev, Goetzmann & Rouwenhorst (2006): every `trade` days, pick the n pairs within a sector whose
    normalized prices moved closest over the prior `form` days; open when the spread is `entry` formation
    standard deviations wide (long the cheap leg, short the rich one), close when it crosses zero or at the
    end of the trading window. Equal capital per pair; idle capital earns nothing. Daily returns."""
    ret = close.pct_change(fill_method=None)
    out = pd.Series(0.0, index=close.index)
    for start in range(form, len(close) - 1, trade):
        fw = close.iloc[start - form:start]
        ok = [c for c in fw.columns if fw[c].notna().all() and close.iloc[start:start + trade][c].notna().all()]
        norm = fw[ok] / fw[ok].iloc[0]
        cands = []
        for i, a in enumerate(ok):
            for b in ok[i + 1:]:
                if sectors.get(a) == sectors.get(b) and sectors.get(a) not in (None, "Other"):
                    cands.append((float(((norm[a] - norm[b]) ** 2).sum()), a, b))
        cands.sort()
        window = close.index[start:start + trade]
        for _, a, b in cands[:n_pairs]:
            sd = float((norm[a] - norm[b]).std())
            pa, pb = close.loc[window, a] / fw[a].iloc[0], close.loc[window, b] / fw[b].iloc[0]
            spread = (pa - pb) / sd
            pos = 0
            for t_prev, t in zip(window[:-1], window[1:]):
                z = spread[t_prev]
                if pos == 0 and abs(z) > entry:
                    pos = -1 if z > 0 else 1  # z > 0: a is rich, short a and long b
                    out[t] -= 2 * cost / n_pairs
                elif pos != 0 and (np.sign(z) == pos or t == window[-1]):
                    pos = 0
                    out[t] -= 2 * cost / n_pairs
                if pos:
                    out[t] += pos * (ret.loc[t, a] - ret.loc[t, b]) / 2 / n_pairs
    return out.iloc[form:]
