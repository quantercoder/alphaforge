"""Event-driven daily backtest with weight drift, execution lag and transaction costs."""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import portfolio, signals
from .refdata import sector


@dataclass
class Config:
    model: str = "factors"            # factors | trend | equal  (what scores the assets)
    mode: str = "long_short"          # long_short | long_only | trend | equal  (scores -> weights)
    rebalance: str = "ME"             # pandas offset alias: ME, W-FRI, QE... (weekly ~3x turnover)
    execution_lag: int = 1            # days between signal close and trade close
    target_vol: float | None = 0.10   # annualized, ex-ante; None = no risk scaling
    max_weight: float = 0.10          # |w_i| as fraction of NAV
    max_leverage: float = 2.0         # gross exposure cap
    cost_bps: float = 2.0             # commissions + fees per unit traded
    slippage_bps: float = 5.0         # half-spread + impact per unit traded
    cov_lookback: int = 63
    warmup: int = 252                 # days before the first trade (momentum needs a year)
    swap_every: int = 0               # trading days between "replace the worst" checks; 0 = off
    swap_count: int = 2               # long holdings replaced at each check
    ann: int = 252                    # periods per year: 252 equities, 365 crypto
    # Constrained construction (long-only/trend). Any of these set -> portfolio.optimize runs after
    # the target weights: closest portfolio within the limits, with a turnover penalty.
    max_sector: float | None = None   # sum of weights per sector
    max_beta: float | None = None     # beta to the equal-weighted universe
    turnover_penalty: float = 0.0     # per unit of turnover, in units of annual tracking variance
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
    rf: pd.Series | None      # daily risk-free return earned on cash
    config: Config

    @property
    def equity(self):
        return (1 + self.returns).cumprod()


def rebalance_dates(index, freq, warmup):
    """Last trading day of each period, after warmup."""
    s = pd.Series(index, index=index)
    dates = s.resample(freq).last().dropna()
    return [d for d in dates if index.get_loc(d) >= warmup]


def constrained(cfg):
    return cfg.mode in ("long_only", "trend") and bool(cfg.max_sector or cfg.max_beta or cfg.turnover_penalty)


def targets_at(alpha, rets, i, cfg, w_now=None):
    """Target weights from information at row i only. Shared by backtest and live trading.
    `w_now` (today's weights) only matters for the optimizer's turnover penalty."""
    hist = rets.iloc[max(1, i - cfg.cov_lookback + 1): i + 1]
    w = portfolio.target_weights(alpha.iloc[i], hist, cfg.mode, cfg.max_weight, cfg.target_vol, cfg.max_leverage)
    if not constrained(cfg):
        return w
    return portfolio.optimize(w, hist, rets.iloc[max(1, i - 251): i + 1], cfg.max_weight, cfg.max_leverage,
                              cfg.max_sector, cfg.max_beta, cfg.turnover_penalty, w_now,
                              [sector(s) for s in w.index], alpha.iloc[i].notna(), ann=cfg.ann)


def run_backtest(prices, cfg=None, benchmark=None, rf=None, start=None):
    """Signals at close t, trade at close t+lag, earn returns from t+lag+1 onward.

    `start` (a date) makes the first signal that day instead of the first period end after warmup:
    a shadow of a live book that started then.

    Weights drift with prices between rebalances, so costs reflect the real trade
    from drifted holdings to target rather than from the last target. With `rf` (daily
    risk-free returns), uninvested NAV, 1 - sum(w), earns it.
    """
    cfg = cfg or Config()
    prices = prices.sort_index()
    rets = prices.pct_change()
    alpha = signals.alpha_panel(prices, cfg)
    idx = prices.index
    RF = np.zeros(len(idx)) if rf is None else rf.reindex(idx).ffill().fillna(0).values

    dates = rebalance_dates(idx, cfg.rebalance, cfg.warmup)
    if start is not None:
        s0 = idx[max(0, idx.searchsorted(pd.Timestamp(start), side="right") - 1)]
        dates = [s0] + [d for d in dates if d > s0]
    signal_rows = {idx.get_loc(d) for d in dates if idx.get_loc(d) + cfg.execution_lag < len(idx)}
    targets = {}

    n = len(idx)
    cost_rate = (cfg.cost_bps + cfg.slippage_bps) / 1e4
    w = np.zeros(prices.shape[1])
    W = np.zeros((n, prices.shape[1]))
    gross, cost, turn = np.zeros(n), np.zeros(n), np.zeros(n)
    R = rets.fillna(0).values
    P = prices.ffill().values
    cols = list(prices.columns)
    entry = np.full(len(cols), np.nan)  # price when each position was opened (P&L reference)
    swaps, last_action = {}, None

    for t in range(n):
        r = R[t]
        g = float(w @ r) + (1 - w.sum()) * RF[t]
        gross[t] = g
        # NAV-relative drift: each position grows with its asset, NAV grows with the book.
        w = w * (1 + r) / (1 + g) if (1 + g) > 0 else w * 0
        tgt = None
        if idx[t] in targets:
            tgt = targets[idx[t]].values
        elif t in swaps:
            drop, add = swaps[t]
            di, ai = [cols.index(s) for s in drop], [cols.index(s) for s in add]
            tgt = w.copy()
            tgt[ai] = tgt[di].sum() / len(ai)  # new names split the weight freed by the dropped ones
            tgt[di] = 0
        if tgt is not None:
            turn[t] = np.abs(tgt - w).sum()
            cost[t] = turn[t] * cost_rate
            opened = (w == 0) & (tgt != 0)
            entry[opened] = P[t, opened]
            entry[tgt == 0] = np.nan
            w = tgt
        W[t] = w

        # Decide at this close; trade execution_lag days later (same timing as full rebalances).
        if t in signal_rows:
            last_action = t
            targets[idx[t + cfg.execution_lag]] = targets_at(alpha, rets, t, cfg, pd.Series(w, index=cols))
        elif cfg.swap_every and last_action is not None and t - last_action >= cfg.swap_every:
            last_action = t
            if t + cfg.execution_lag < n:
                held = {cols[i]: P[t, i] / entry[i] - 1 for i in np.flatnonzero(w > 0) if entry[i] > 0}
                drop, add = portfolio.pick_swaps(held, alpha.iloc[t], cfg.swap_count, dict(zip(cols, w)),
                                                 sector, cfg.max_sector)
                if drop:
                    swaps[t + cfg.execution_lag] = (drop, add)

    s = lambda a: pd.Series(a, index=idx)
    return Result(
        returns=s(gross - cost), gross_returns=s(gross),
        weights=pd.DataFrame(W, index=idx, columns=prices.columns),
        turnover=s(turn), costs=s(cost), alpha=alpha,
        benchmark=None if benchmark is None else benchmark.reindex(idx).pct_change().fillna(0),
        rf=None if rf is None else s(RF),
        config=cfg,
    )
