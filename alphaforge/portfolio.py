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


def alpha_to_weights(alpha, mode="long_short", top_frac=0.3, held=(), hold_frac=None):
    """Unit-gross weights from a cross-sectional alpha vector (NaN = untradeable).

    long_short: dollar-neutral, weights proportional to demeaned alpha.
    long_only:  top `top_frac` of names, weights proportional to alpha rank. With `hold_frac`, a name
                already `held` stays while it ranks in the top `hold_frac` (a rank buffer), and the
                remaining slots go to the best-ranked names not held.
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
        pick = a.nlargest(n).index
        if hold_frac and len(held):
            rank = a.rank(ascending=False)
            keep = [s for s in held if s in rank.index and rank[s] <= hold_frac * len(a)]
            keep = sorted(keep, key=lambda s: rank[s])[:n]
            pick = keep + [s for s in a.sort_values(ascending=False).index if s not in keep][: n - len(keep)]
        top = a[pick].rank()
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


def pick_swaps(held_pnl, alpha_row, k, weights=None, sector=None, max_sector=None):
    """Pair the worst-k long holdings by P&L since entry with the best-alpha names not held.

    The worst holding is paired with the best candidate, the second worst with the second best,
    and a pair is kept only if the candidate's alpha beats the holding's. With `max_sector`, a
    candidate whose sector would end above the cap (taking the dropped name's weight) is skipped.
    Returns (drop, add).
    """
    worst = sorted(held_pnl, key=held_pnl.get)[:k]
    a = alpha_row.dropna()
    cands = [s for s in a.sort_values(ascending=False).index if s not in held_pnl]
    sec_w = {}
    if max_sector and weights and sector:
        for s, v in weights.items():
            sec_w[sector(s)] = sec_w.get(sector(s), 0.0) + v

    def room(d, c):
        if not sec_w or sector(c) == "Other":
            return True
        w = weights.get(d, 0.0)
        return sec_w.get(sector(c), 0.0) + w - (w if sector(c) == sector(d) else 0.0) <= max_sector + 1e-9

    pairs, pos = [], 0
    for d in worst:
        while pos < len(cands) and not room(d, cands[pos]):
            pos += 1
        if pos == len(cands):
            break
        c = cands[pos]
        pos += 1
        if a.get(c, -np.inf) > a.get(d, -np.inf):
            pairs.append((d, c))
            if sec_w:
                w = weights.get(d, 0.0)
                sec_w[sector(d)] -= w
                sec_w[sector(c)] = sec_w.get(sector(c), 0.0) + w
    return [d for d, _ in pairs], [c for _, c in pairs]


# ---------------------------------------------------------------- constrained construction

def solve_qp(P, q, A, lo, hi, rho=0.5, sigma=1e-6, relax=1.6, iters=10_000, tol=1e-8):
    """min 1/2 x'Px + q'x  subject to  lo <= Ax <= hi, by ADMM with over-relaxation (the OSQP
    iteration, Stellato et al. 2020). Dense and small: fine for a few hundred variables."""
    n, m = P.shape[0], A.shape[0]
    x, z, y = np.zeros(n), np.zeros(m), np.zeros(m)
    K = np.linalg.inv(P + sigma * np.eye(n) + rho * A.T @ A)
    for _ in range(iters):
        xt = K @ (sigma * x - q + A.T @ (rho * z - y))
        zt = A @ xt
        x_new = relax * xt + (1 - relax) * x
        z_mix = relax * zt + (1 - relax) * z
        z_new = np.clip(z_mix + y / rho, lo, hi)
        y = y + rho * (z_mix - z_new)
        done = np.abs(A @ x_new - z_new).max() < tol and np.abs(rho * (z_new - z)).max() < tol
        x, z = x_new, z_new
        if done:
            break
    return x


def optimize(target, hist, long_hist, max_weight, max_leverage, max_sector=None, max_beta=None,
             turnover_penalty=0.0, w_now=None, sectors=None, allowed=None, cov_shrink=0.3, ann=252):
    """Closest long-only portfolio to `target` (in tracking variance) that respects the limits:

        min (w - w*)' S (w - w*) + tau * sum|w - w0|
        s.t. 0 <= w_i <= max_weight,  sum w <= max_leverage,  sum_{i in s} w_i <= max_sector,
             beta' w <= max_beta

    S is the annualized shrunk covariance, w0 today's weights, beta each name's beta to the
    equal-weighted universe over `long_hist`. Names in sector "Other" have no sector limit.
    """
    names = target.index
    n = len(names)
    ok = allowed.reindex(names).fillna(False).values.astype(bool) if allowed is not None else np.ones(n, bool)
    ub = np.where(ok, max_weight, 0.0)
    sample = hist.reindex(columns=names).fillna(0).cov().values
    S = ((1 - cov_shrink) * sample + cov_shrink * np.diag(np.diag(sample))) * ann
    wt = target.fillna(0).values
    w0 = w_now.reindex(names).fillna(0).values if w_now is not None else np.zeros(n)
    rows, lo, hi = [np.eye(n), np.ones((1, n))], [np.zeros(n), [0.0]], [ub, [max_leverage]]
    if max_sector and sectors is not None:
        for s in sorted(set(sectors) - {"Other"}):
            rows.append(np.array([[float(x == s) for x in sectors]]))
            lo.append([-np.inf])
            hi.append([max_sector])
    if max_beta:
        lh = long_hist.reindex(columns=names).fillna(0)
        mkt = lh.mean(axis=1)
        beta = (lh.apply(lambda c: c.cov(mkt)) / mkt.var()).fillna(1.0).values
        rows.append(beta[None, :])
        lo.append([-np.inf])
        hi.append([max_beta])
    A = np.vstack(rows)
    lo, hi = np.concatenate([np.asarray(v, float) for v in lo]), np.concatenate([np.asarray(v, float) for v in hi])
    P, q = 2 * S, -2 * S @ wt
    if turnover_penalty:  # x = [w, t] with t >= |w - w0|
        m = A.shape[0]
        A = np.vstack([np.hstack([A, np.zeros((m, n))]),
                       np.hstack([np.eye(n), np.eye(n)]),     # w + t >= w0
                       np.hstack([np.eye(n), -np.eye(n)])])   # w - t <= w0
        lo = np.concatenate([lo, w0, np.full(n, -np.inf)])
        hi = np.concatenate([hi, np.full(n, np.inf), w0])
        P = np.block([[P, np.zeros((n, n))], [np.zeros((n, n)), 1e-6 * np.eye(n)]])
        q = np.concatenate([q, np.full(n, turnover_penalty)])
    w = solve_qp(P, q, A, lo, hi)[:n]
    # Repair the solver's last-digit violations: clip to the box, then scale down until every
    # upper limit holds (all limit rows have non-negative coefficients except a negative beta).
    w = np.clip(w, 0, ub)
    for r, h in zip(A[: len(hi) - (2 * n if turnover_penalty else 0), :n], hi):
        tot = float(r @ w)
        if np.isfinite(h) and tot > h > 0:
            w *= h / tot
    return pd.Series(np.where(w > 1e-6, w, 0.0), index=names)


def risk_model_cov(long_returns, names, shrink=0.3, horizon=21):
    """Annualized covariance D C D: GARCH(1,1) volatilities (63-day sample where history is short) and the
    252-day correlation shrunk toward the identity. Returns (cov, vols)."""
    from .vol import garch_vol
    R = long_returns.reindex(columns=names)
    g = garch_vol(R, horizon).fillna(R.iloc[-63:].std()).fillna(R.std()).values * np.sqrt(252)
    C = R.iloc[-252:].fillna(0).corr().fillna(0).values
    C = (1 - shrink) * C + shrink * np.eye(len(names))
    np.fill_diagonal(C, 1.0)
    return g[:, None] * C * g[None, :], g


def max_div_weights(long_returns, names, max_weight):
    """Maximum diversification (Choueifaty & Coignard 2008): maximize w'sigma / sqrt(w'Sigma w), long-only, each
    weight at most max_weight. Solved as min x'Sigma x s.t. sigma'x = 1, x >= 0, x_i <= max_weight * sum(x)
    (linear), then w = x / sum(x)."""
    S, g = risk_model_cov(long_returns, names)
    n = len(names)
    cap_rows = np.eye(n) - max_weight * np.ones((n, n))      # x_i - cap * sum(x) <= 0
    A = np.vstack([np.eye(n), g[None, :], cap_rows])
    lo = np.r_[np.zeros(n), 1.0, np.full(n, -np.inf)]
    hi = np.r_[np.full(n, np.inf), 1.0, np.zeros(n)]
    x = np.clip(solve_qp(2 * S, np.zeros(n), A, lo, hi), 0, None)
    w = x / x.sum() if x.sum() > 0 else np.full(n, 1 / n)
    return pd.Series(cap_weights(w, max_weight), index=names)


def target_weights(alpha_row, hist_returns, mode, max_weight, target_vol, max_leverage,
                   cov_shrink=0.3, w_now=None, hold_buffer=None, trend_exit=None, vol_model="sample",
                   long_returns=None):
    """Full pipeline for one rebalance date. `hist_returns` must end at the signal date.

    w_now: today's weights (for the buffers). hold_buffer: long-only rank buffer (see alpha_to_weights).
    trend_exit: trend mode keeps a held asset until its score falls to this level (default: sell at <= 0).
    vol_model "garch": volatilities from GARCH(1,1) on `long_returns` (3 years) with the 252-day
    correlation, instead of the sample covariance of `hist_returns`."""
    held = [] if w_now is None else [s for s, v in w_now.items() if v > 1e-9]
    if mode == "trend":
        # Long only in up-trending assets, sized by inverse volatility (risk parity across trends).
        vol = hist_returns.std().reindex(alpha_row.index)
        score = alpha_row.clip(lower=0)
        if trend_exit is not None and held:
            # Hysteresis: a held asset stays (sized as the smallest positive score) until its score
            # reaches trend_exit.
            floor = alpha_row[alpha_row > 0].min() if (alpha_row > 0).any() else 1 / 3
            keep = [s for s in held if s in alpha_row.index and alpha_row[s] > trend_exit and alpha_row[s] <= 0]
            score[keep] = floor
        u = (score / vol).replace([np.inf, -np.inf], np.nan).fillna(0)
        w = u / u.sum() if u.sum() > 0 else u * 0
    elif mode == "max_div":  # no forecast: every name with a score (i.e. with history) is eligible
        names = list(alpha_row.dropna().index)
        w = pd.Series(0.0, index=alpha_row.index)
        if len(names) >= 2 and long_returns is not None:
            w[names] = max_div_weights(long_returns, names, max_weight)
    else:
        w = alpha_to_weights(alpha_row, mode, held=held, hold_frac=hold_buffer)
    w = pd.Series(cap_weights(w.values, max_weight), index=w.index)
    if target_vol is None:  # no risk scaling (equal-weight benchmark)
        return w.clip(-max_weight, max_weight)
    sample = hist_returns.fillna(0).cov().values
    # Shrink toward diagonal: sample covariance on ~63 days x 30 names is noisy.
    cov = (1 - cov_shrink) * sample + cov_shrink * np.diag(np.diag(sample))
    if vol_model == "garch" and long_returns is not None:
        from .vol import garch_vol
        g = garch_vol(long_returns.reindex(columns=w.index), horizon=21).values
        sd = np.where(np.isfinite(g), g, np.sqrt(np.diag(sample)))   # no 2-year history: sample vol
        corr = long_returns.iloc[-252:].reindex(columns=w.index).fillna(0).corr().fillna(0).values
        corr = (1 - cov_shrink) * corr + cov_shrink * np.eye(len(sd))
        np.fill_diagonal(corr, 1.0)
        cov = sd[:, None] * corr * sd[None, :]
    scaled = vol_target(w.values, cov, target_vol, max_leverage)
    # Hard NAV-relative limit after leverage; may nudge vol slightly under target.
    return pd.Series(np.clip(scaled, -max_weight, max_weight), index=w.index)
