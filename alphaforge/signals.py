"""Cross-sectional alpha factors. Every factor at date t uses prices up to and including t only."""
import numpy as np
import pandas as pd


def cs_zscore(df, clip=3.0):
    """Cross-sectional z-score per row, winsorized at +/- clip."""
    z = df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1).replace(0, np.nan), axis=0)
    return z.clip(-clip, clip)


def momentum(prices, lookback=252, skip=21):
    """12-1 momentum: return from t-252 to t-21, skipping the reversal-prone last month."""
    return np.log(prices.shift(skip) / prices.shift(lookback))


def reversal(prices, lookback=5):
    """Short-term reversal: last week's losers tend to bounce."""
    return -np.log(prices / prices.shift(lookback))


def low_vol(prices, lookback=63):
    """Low-volatility anomaly: lower realized vol scores higher."""
    return -np.log(prices).diff().rolling(lookback).std()


def quality_trend(prices, lookback=126):
    """Trend smoothness: return / path length. Rewards steady over jumpy gains."""
    lp = np.log(prices)
    net = lp - lp.shift(lookback)
    path = lp.diff().abs().rolling(lookback).sum()
    return net / path.replace(0, np.nan)


FACTORS = {
    "momentum": momentum,
    "reversal": reversal,
    "low_vol": low_vol,
    "quality_trend": quality_trend,
}


def factor_scores(prices):
    """Dict of z-scored factor panels."""
    return {name: cs_zscore(fn(prices)) for name, fn in FACTORS.items()}


def combine(scores, weights):
    """Weighted blend of z-scored factors, re-z-scored. Missing factors count as 0 for that name."""
    total = sum(abs(w) for w in weights.values())
    if total == 0:
        raise ValueError("At least one factor weight must be non-zero")
    blend = sum(scores[k].fillna(0) * w for k, w in weights.items() if w)
    # Names with no factor history at all stay NaN so they are not traded.
    valid = sum(scores[k].notna().astype(int) for k, w in weights.items() if w) > 0
    return cs_zscore(blend.where(valid))


def trend_score(prices, lookbacks=(20, 60, 120)):
    """Time-series trend: average sign of the log return over several lookbacks, in [-1, 1].

    Not cross-sectional: each asset is judged against its own past, so every asset can be
    in a downtrend at once (and the book goes to cash).
    """
    lp = np.log(prices)
    return sum(np.sign(lp - lp.shift(n)) for n in lookbacks) / len(lookbacks)


def alpha_panel(prices, cfg):
    """The model's score panel for a backtest.Config: factor blend, trend, or flat (equal weight)."""
    if cfg.model == "trend":
        return trend_score(prices)
    if cfg.model == "equal":
        return prices.notna().astype(float).where(prices.notna())
    return combine(factor_scores(prices), cfg.factor_weights)
