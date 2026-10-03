"""Alpha -> target weights: construction, position caps, ex-ante volatility targeting."""
import numpy as np
import pandas as pd


def cap_weights(w, max_weight, iters=20):
    """Clip |w_i| <= max_weight while preserving gross exposure, redistributing the excess."""
    w = w.copy()
    gross = np.abs(w).sum()
    if gross == 0:
        return w
    capped = np.zeros(len(w), dtype=bool)
    for _ in range(iters):
        over = np.abs(w) > max_weight + 1e-12
        if not over.any():
            break
        capped |= over
        w[capped] = np.sign(w[capped]) * max_weight
        free = ~capped & (w != 0)
        room = gross - np.abs(w).sum()
        if room <= 1e-12 or not free.any():
            break
        w[free] *= 1 + room / np.abs(w[free]).sum()
    return w


def alpha_to_weights(alpha, mode="long_short", top_frac=0.3):
    """Unit-gross weights from a cross-sectional alpha vector (NaN = untradeable).

    long_short: dollar-neutral, weights proportional to demeaned alpha.
    long_only:  top `top_frac` of names, weights proportional to alpha rank.
    """
    a = alpha.dropna()
    w = pd.Series(0.0, index=alpha.index)
    if len(a) < 2:
        return w
    if mode == "long_short":
        s = a - a.mean()
        w[s.index] = s / s.abs().sum()
    elif mode == "equal":
        w[a.index] = 1 / len(a)
    elif mode == "long_only":
        n = max(1, int(round(len(a) * top_frac)))
        top = a.nlargest(n).rank()
        w[top.index] = top / top.sum()
    else:
        raise ValueError(f"Unknown mode: {mode}")
    return w


def vol_target(w, cov, target_vol, max_leverage):
    """Scale weights so ex-ante annualized vol hits target, capped at max_leverage gross."""
    var = float(w @ cov @ w) * 252
    if var <= 0:
        return w * 0
    scale = target_vol / np.sqrt(var)
    gross = np.abs(w).sum()
    if gross * scale > max_leverage:
        scale = max_leverage / gross
    return w * scale


def pick_swaps(held_pnl, alpha_row, k):
    """Pair the worst-k long holdings by P&L since entry with the best-alpha names not held.

    The worst holding is paired with the best candidate, the second worst with the second best,
    and a pair is kept only if the candidate's alpha beats the holding's. Returns (drop, add).
    """
    worst = sorted(held_pnl, key=held_pnl.get)[:k]
    a = alpha_row.dropna()
    cands = [s for s in a.sort_values(ascending=False).index if s not in held_pnl]
    pairs = [(d, c) for d, c in zip(worst, cands) if a.get(c, -np.inf) > a.get(d, -np.inf)]
    return [d for d, _ in pairs], [c for _, c in pairs]


def target_weights(alpha_row, hist_returns, mode, max_weight, target_vol, max_leverage,
                   cov_shrink=0.3):
    """Full pipeline for one rebalance date. `hist_returns` must end at the signal date."""
    if mode == "trend":
        # Long only in up-trending assets, sized by inverse volatility (risk parity across trends).
        vol = hist_returns.std().reindex(alpha_row.index)
        u = (alpha_row.clip(lower=0) / vol).replace([np.inf, -np.inf], np.nan).fillna(0)
        w = u / u.sum() if u.sum() > 0 else u * 0
    else:
        w = alpha_to_weights(alpha_row, mode)
    w = pd.Series(cap_weights(w.values, max_weight), index=w.index)
    if target_vol is None:  # no risk scaling (equal-weight benchmark)
        return w.clip(-max_weight, max_weight)
    sample = hist_returns.fillna(0).cov().values
    # Shrink toward diagonal: sample covariance on ~63 days x 30 names is noisy.
    cov = (1 - cov_shrink) * sample + cov_shrink * np.diag(np.diag(sample))
    scaled = vol_target(w.values, cov, target_vol, max_leverage)
    # Hard NAV-relative limit after leverage; may nudge vol slightly under target.
    return pd.Series(np.clip(scaled, -max_weight, max_weight), index=w.index)
