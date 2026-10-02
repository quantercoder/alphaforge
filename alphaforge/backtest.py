"""Event-driven daily backtest with weight drift, execution lag and transaction costs."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import portfolio, signals


@dataclass
class Config:
    mode: str = "long_short"          # long_short | long_only
    rebalance: str = "ME"             # pandas offset alias: ME, W-FRI, QE... (weekly ~3x turnover)
    execution_lag: int = 1            # days between signal close and trade close
    target_vol: float = 0.10          # annualized, ex-ante
    max_weight: float = 0.10          # |w_i| as fraction of NAV
    max_leverage: float = 2.0         # gross exposure cap
    cost_bps: float = 2.0             # commissions + fees per unit traded
    slippage_bps: float = 5.0         # half-spread + impact per unit traded
    cov_lookback: int = 63
    warmup: int = 252                 # days before the first trade (momentum needs a year)
    factor_weights: dict = field(default_factory=lambda: {
        "momentum": 0.4, "reversal": 0.2, "low_vol": 0.2, "quality_trend": 0.2})


@dataclass
class Result:
    returns: pd.Series        # daily net strategy returns
    gross_returns: pd.Series  # before costs
    weights: pd.DataFrame     # end-of-day weights (post-trade)
    turnover: pd.Series       # sum |trade| on each day
    costs: pd.Series
    alpha: pd.DataFrame       # combined alpha panel
    benchmark: pd.Series | None
    config: Config

    @property
    def equity(self):
        return (1 + self.returns).cumprod()


def rebalance_dates(index, freq, warmup):
    """Last trading day of each period, after warmup."""
    s = pd.Series(index, index=index)
    dates = s.resample(freq).last().dropna()
    return [d for d in dates if index.get_loc(d) >= warmup]


def run_backtest(prices, cfg=None, benchmark=None):
    """Signals at close t, trade at close t+lag, earn returns from t+lag+1 onward.

    Weights drift with prices between rebalances, so costs reflect the real trade
    from drifted holdings to target rather than from the last target.
    """
    cfg = cfg or Config()
    prices = prices.sort_index()
    rets = prices.pct_change()
    alpha = signals.combine(signals.factor_scores(prices), cfg.factor_weights)
    idx = prices.index

    targets = {}
    for d in rebalance_dates(idx, cfg.rebalance, cfg.warmup):
        i = idx.get_loc(d)
        if i + cfg.execution_lag >= len(idx):
            continue
        hist = rets.iloc[max(1, i - cfg.cov_lookback + 1): i + 1]
        targets[idx[i + cfg.execution_lag]] = portfolio.target_weights(
            alpha.iloc[i], hist, cfg.mode, cfg.max_weight, cfg.target_vol, cfg.max_leverage)

    n = len(idx)
    cost_rate = (cfg.cost_bps + cfg.slippage_bps) / 1e4
    w = np.zeros(prices.shape[1])
    W = np.zeros((n, prices.shape[1]))
    gross, cost, turn = np.zeros(n), np.zeros(n), np.zeros(n)
    R = rets.fillna(0).values

    for t in range(n):
        r = R[t]
        g = float(w @ r)
        gross[t] = g
        # NAV-relative drift: each position grows with its asset, NAV grows with the book.
        w = w * (1 + r) / (1 + g) if (1 + g) > 0 else w * 0
        if idx[t] in targets:
            tgt = targets[idx[t]].values
            turn[t] = np.abs(tgt - w).sum()
            cost[t] = turn[t] * cost_rate
            w = tgt
        W[t] = w

    s = lambda a: pd.Series(a, index=idx)
    return Result(
        returns=s(gross - cost), gross_returns=s(gross),
        weights=pd.DataFrame(W, index=idx, columns=prices.columns),
        turnover=s(turn), costs=s(cost), alpha=alpha,
        benchmark=None if benchmark is None else benchmark.reindex(idx).pct_change().fillna(0),
        config=cfg,
    )
