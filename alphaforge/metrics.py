"""Performance and risk statistics on daily return series.

`rf` is an optional daily risk-free return series (same index); Sharpe, Sortino and alpha are
computed on excess returns when it is given. `ann` is periods per year: 252 for equities,
365 for crypto, which trades every day.
"""
import numpy as np
import pandas as pd

TD = 252


def _excess(returns, rf):
    return returns if rf is None else returns - rf.reindex(returns.index).fillna(0)


def drawdown(returns):
    eq = (1 + returns).cumprod()
    return eq / eq.cummax() - 1


def sharpe(returns, rf=None, ann=TD):
    x = _excess(returns, rf)
    sd = x.std()
    return 0.0 if sd == 0 or np.isnan(sd) else x.mean() / sd * np.sqrt(ann)


def sharpe_se(sr, years):
    """Standard error of an annualized Sharpe ratio under iid returns (Lo, 2002)."""
    return np.sqrt((1 + sr ** 2 / 2) / years) if years > 0 else np.nan


def sortino(returns, rf=None, ann=TD):
    x = _excess(returns, rf)
    downside = np.sqrt((x.clip(upper=0) ** 2).mean())
    return 0.0 if downside == 0 else x.mean() / downside * np.sqrt(ann)


def rolling_sharpe(returns, window=126, ann=TD):
    return returns.rolling(window).mean() / returns.rolling(window).std() * np.sqrt(ann)


def var_cvar(returns, level=0.95):
    """Historical one-day VaR and CVaR (expected shortfall), reported as positive losses."""
    q = returns.quantile(1 - level)
    return -q, -returns[returns <= q].mean()


def beta_alpha(returns, bench, rf=None, ann=TD):
    """CAPM beta and annualized Jensen's alpha vs benchmark, on excess returns when rf is given."""
    df = pd.concat([_excess(returns, rf), _excess(bench, rf)], axis=1).dropna()
    if len(df) < 2 or df.iloc[:, 1].var() == 0:
        return np.nan, np.nan
    b = df.cov().iloc[0, 1] / df.iloc[:, 1].var()
    a = (df.iloc[:, 0].mean() - b * df.iloc[:, 1].mean()) * ann
    return b, a


def monthly_table(returns):
    """Year x month compounded returns, plus a full-year column."""
    m = (1 + returns).resample("ME").prod() - 1
    t = m.groupby([m.index.year, m.index.month]).first().unstack()
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    t.columns = [names[c - 1] for c in t.columns]
    t["Year"] = (1 + returns).groupby(returns.index.year).prod() - 1
    return t


def first_trade(result):
    live = result.weights.abs().sum(axis=1) > 0
    return live.idxmax() if live.any() else result.returns.index[0]


def stats(r, rf=None, ann=TD, bench=None):
    """Headline statistics for a daily return series."""
    years = len(r) / ann
    total = (1 + r).prod() - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else np.nan
    mdd = drawdown(r).min()
    var, cvar = var_cvar(r)
    sr = sharpe(r, rf, ann)
    out = {
        "CAGR": cagr,
        "Ann. Vol": r.std() * np.sqrt(ann),
        "Sharpe": sr,
        "Sharpe SE": sharpe_se(sr, years),
        "Sortino": sortino(r, rf, ann),
        "Max Drawdown": mdd,
        "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "VaR 95% (1d)": var,
        "CVaR 95% (1d)": cvar,
        "Hit Rate": (r[r != 0] > 0).mean(),
    }
    if bench is not None:
        b, a = beta_alpha(r, bench, rf, ann)
        out["Beta"] = b
        out["Alpha (ann.)"] = a
    return out


def summary(result):
    """Headline stats for a backtest Result, computed from the first trade onward."""
    start = first_trade(result)
    ann = result.config.ann
    r = result.returns.loc[start:]
    years = len(r) / ann
    out = stats(r, None if result.rf is None else result.rf.loc[start:], ann,
                None if result.benchmark is None else result.benchmark.loc[start:])
    out["Ann. Turnover"] = result.turnover.loc[start:].sum() / years if years else np.nan
    out["Cost Drag (ann.)"] = result.costs.loc[start:].sum() / years if years else np.nan
    out["Avg Gross Lev."] = result.weights.loc[start:].abs().sum(axis=1).mean()
    return out
