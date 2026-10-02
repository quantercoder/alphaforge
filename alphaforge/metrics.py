"""Performance and risk statistics on daily return series."""
import numpy as np
import pandas as pd

TD = 252


def drawdown(returns):
    eq = (1 + returns).cumprod()
    return eq / eq.cummax() - 1


def sharpe(returns):
    sd = returns.std()
    return 0.0 if sd == 0 or np.isnan(sd) else returns.mean() / sd * np.sqrt(TD)


def sortino(returns):
    downside = np.sqrt((returns.clip(upper=0) ** 2).mean())
    return 0.0 if downside == 0 else returns.mean() / downside * np.sqrt(TD)


def rolling_sharpe(returns, window=126):
    return returns.rolling(window).mean() / returns.rolling(window).std() * np.sqrt(TD)


def var_cvar(returns, level=0.95):
    """Historical one-day VaR and CVaR (expected shortfall), reported as positive losses."""
    q = returns.quantile(1 - level)
    return -q, -returns[returns <= q].mean()


def beta_alpha(returns, bench):
    """CAPM beta and annualized Jensen's alpha vs benchmark."""
    df = pd.concat([returns, bench], axis=1).dropna()
    if len(df) < 2 or df.iloc[:, 1].var() == 0:
        return np.nan, np.nan
    b = df.cov().iloc[0, 1] / df.iloc[:, 1].var()
    a = (df.iloc[:, 0].mean() - b * df.iloc[:, 1].mean()) * TD
    return b, a


def monthly_table(returns):
    """Year x month compounded returns, plus a full-year column."""
    m = (1 + returns).resample("ME").prod() - 1
    t = m.groupby([m.index.year, m.index.month]).first().unstack()
    t.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                 "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][: len(t.columns)]
    t["Year"] = (1 + returns).groupby(returns.index.year).prod() - 1
    return t


def summary(result):
    """Headline stats for a backtest Result, computed from the first trade onward."""
    live = result.weights.abs().sum(axis=1) > 0
    start = live.idxmax() if live.any() else result.returns.index[0]
    r = result.returns.loc[start:]
    years = len(r) / TD
    total = (1 + r).prod() - 1
    cagr = (1 + total) ** (1 / years) - 1 if years > 0 and total > -1 else np.nan
    mdd = drawdown(r).min()
    var, cvar = var_cvar(r)
    out = {
        "CAGR": cagr,
        "Ann. Vol": r.std() * np.sqrt(TD),
        "Sharpe": sharpe(r),
        "Sortino": sortino(r),
        "Max Drawdown": mdd,
        "Calmar": cagr / abs(mdd) if mdd < 0 else np.nan,
        "VaR 95% (1d)": var,
        "CVaR 95% (1d)": cvar,
        "Hit Rate": (r[r != 0] > 0).mean(),
        "Ann. Turnover": result.turnover.loc[start:].sum() / years if years else np.nan,
        "Cost Drag (ann.)": result.costs.loc[start:].sum() / years if years else np.nan,
        "Avg Gross Lev.": result.weights.loc[start:].abs().sum(axis=1).mean(),
    }
    if result.benchmark is not None:
        b, a = beta_alpha(r, result.benchmark.loc[start:])
        out["Beta"] = b
        out["Alpha (ann.)"] = a
    return out
