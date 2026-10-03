"""Desk analytics for the terminal: factor risk model, P&L attribution, active risk, stress,
liquidity, limits, transaction cost analysis, signal diagnostics, data health and the next-trade
preview. Inputs are plain DataFrames, so the tests run on synthetic prices.

The risk model is a small Barra-style cross-sectional model. Each day t:

    r_i,t = f_mkt,t + sum_s D_i,s f_s,t + sum_k z_i,k,t-1 f_k,t + e_i,t      with  sum_s f_s,t = 0

D is the sector dummy matrix and z the style z-scores known at the prior close. The factor
covariance F and specific variances are exponentially weighted. Portfolio variance is
x'Fx + w'diag(spec)w with exposures x = X'w; each factor's share is x_k (F x)_k / variance (Euler).
"""
import math

import numpy as np
import pandas as pd

from . import portfolio, signals


# ---------------------------------------------------------------- factor risk model

def _ewma_weights(n, halflife):
    w = 0.5 ** (np.arange(n)[::-1] / halflife)
    return w / w.sum()


def risk_model(rets, styles=None, sectors=None, window=252, halflife=90):
    """Fit the cross-sectional model on the last `window` days of `rets` (T x N).

    styles: {name: T x N z-score panel}; yesterday's value is the exposure for today's return.
    sectors: {symbol: sector} or None. Returns a dict with factor names, daily factor returns,
    residuals, per-day exposures, factor covariance F, specific variances and today's exposures.
    """
    styles = styles or {}
    syms = list(rets.columns)
    idx = rets.index[-window:]
    secs = sorted({sectors[s] for s in syms}) if sectors else []
    D = np.array([[float(sectors[s] == k) for k in secs] for s in syms]).reshape(len(syms), len(secs))
    names = ["Market"] + secs + list(styles)
    S, K = len(secs), 1 + len(secs) + len(styles)
    Z = np.stack([styles[k].reindex(columns=syms).shift(1).reindex(idx).fillna(0).values for k in styles], axis=2) \
        if styles else np.zeros((len(idx), len(syms), 0))
    R = rets.reindex(idx)[syms].values
    con = np.zeros(K)
    con[1:1 + S] = 1e3  # sector returns sum to zero, so "Market" is the average stock
    f = np.full((len(idx), K), np.nan)
    E = np.full(R.shape, np.nan)
    X_all = np.zeros((len(idx), len(syms), K))
    for t in range(len(idx)):
        X = np.hstack([np.ones((len(syms), 1)), D, Z[t]])
        X_all[t] = X
        ok = np.isfinite(R[t])
        if ok.sum() < K + 2:
            continue
        A, b = X[ok], R[t, ok]
        if S > 1:
            A, b = np.vstack([A, con]), np.append(b, 0.0)
        f[t] = np.linalg.lstsq(A, b, rcond=None)[0]
        E[t, ok] = R[t, ok] - X[ok] @ f[t]
    good = np.isfinite(f).all(axis=1)
    fw = _ewma_weights(int(good.sum()), halflife)
    fg = f[good]
    mu = fw @ fg
    F = ((fg - mu) * fw[:, None]).T @ (fg - mu)
    spec = []
    for j in range(len(syms)):
        e = E[good, j]
        m = np.isfinite(e)
        spec.append(float(np.average(e[m] ** 2, weights=fw[m])) if m.sum() > 20 else float(np.nanvar(R[:, j])))
    today = np.hstack([np.ones((len(syms), 1)), D,
                       np.column_stack([styles[k].reindex(columns=syms).iloc[-1].fillna(0).values for k in styles])
                       if styles else np.zeros((len(syms), 0))])
    return {"syms": syms, "factors": names, "sectors": secs, "styles": list(styles), "index": idx,
            "f": pd.DataFrame(f, index=idx, columns=names), "resid": pd.DataFrame(E, index=idx, columns=syms),
            "X_t": X_all, "F": F, "spec": np.array(spec), "X": today}


def _group(model, k):
    n = model["factors"][k]
    return "Market" if k == 0 else "Sector" if n in model["sectors"] else "Style"


def decompose(w, model, ann):
    """Risk of weights `w` (Series): factor groups, single styles, specific, and each name's share."""
    w = w.reindex(model["syms"]).fillna(0).values
    X, F, spec = model["X"], model["F"], model["spec"]
    x = X.T @ w
    Fx = F @ x
    fac = float(x @ Fx)
    sp = float((w ** 2) @ spec)
    var = fac + sp
    if var <= 0:
        return None
    by_k = x * Fx / var
    groups = {"Market": 0.0, "Sector": 0.0, "Style": 0.0}
    for k in range(len(x)):
        groups[_group(model, k)] += by_k[k]
    groups["Specific"] = sp / var
    cov_w = X @ Fx + spec * w  # (X F X' + diag spec) w
    names = {s: {"share": float(w[i] * cov_w[i] / var), "specific": float(w[i] ** 2 * spec[i] / var), "w": float(w[i])}
             for i, s in enumerate(model["syms"]) if abs(w[i]) > 1e-6}
    return {"vol": math.sqrt(var * ann), "factor_vol": math.sqrt(fac * ann), "specific_vol": math.sqrt(sp * ann),
            "groups": groups, "styles": {model["factors"][k]: float(by_k[k]) for k in range(len(x)) if _group(model, k) == "Style"},
            "sectors": {model["factors"][k]: float(by_k[k]) for k in range(len(x)) if _group(model, k) == "Sector" and abs(by_k[k]) > 1e-4},
            "exposure": {model["factors"][k]: float(x[k]) for k in range(len(x)) if _group(model, k) != "Sector"},
            "names": dict(sorted(names.items(), key=lambda kv: -kv[1]["share"]))}


# ---------------------------------------------------------------- attribution

def attribution(res, model, asset_rets, freq):
    """Split the backtest's daily return over the model window into market, sector, style,
    specific, cash and costs. Exact: market + sector + style + specific = sum_i w_i,t-1 r_i,t."""
    idx = model["index"]
    W = res.weights.reindex(columns=model["syms"]).fillna(0).shift(1).reindex(idx).fillna(0).values
    f = model["f"].values
    E = np.nan_to_num(model["resid"].values)
    comp = {}
    for k in range(len(model["factors"])):
        exp_k = np.einsum("tn,tn->t", W, model["X_t"][:, :, k])
        comp.setdefault(_group(model, k), np.zeros(len(idx)))
        comp[_group(model, k)] += exp_k * np.nan_to_num(f[:, k])
        if _group(model, k) == "Style":
            comp[model["factors"][k]] = exp_k * np.nan_to_num(f[:, k])
    comp["Specific"] = np.einsum("tn,tn->t", W, E)
    rf = res.rf.reindex(idx).fillna(0).values if res.rf is not None else np.zeros(len(idx))
    comp["Cash"] = (1 - W.sum(axis=1)) * rf
    comp["Costs"] = -res.costs.reindex(idx).fillna(0).values
    total = res.returns.reindex(idx).fillna(0).values
    groups = ["Market", "Sector", "Style", "Specific", "Cash", "Costs"]
    comp = {k: v for k, v in comp.items() if k in groups or k in model["styles"]}
    for g in groups:
        comp.setdefault(g, np.zeros(len(idx)))
    df = pd.DataFrame(comp, index=idx)
    names = (res.weights.shift(1).reindex(idx).fillna(0) * asset_rets.reindex(idx).fillna(0)).sum()  # w_i,t-1 r_i,t
    cum = df[groups].cumsum().resample(freq).last()
    return {"start": str(idx[0].date()), "end": str(idx[-1].date()), "total": float(total.sum()),
            "parts": {k: float(df[k].sum()) for k in groups}, "styles": {k: float(df[k].sum()) for k in model["styles"]},
            "names": {s: float(v) for s, v in names[names.abs() > 1e-5].sort_values(ascending=False).items()},
            "residual": float(total.sum() - df[groups].sum().sum()),
            "dates": [str(i.date()) for i in cum.index], "lines": {k: cum[k].round(6).tolist() for k in groups}}


def active_stats(r, b, ann):
    """Tracking error and information ratio of r against benchmark b (daily, same index)."""
    a = (r - b.reindex(r.index)).dropna()
    if len(a) < 20 or a.std() == 0:
        return {"te": None, "ir": None, "active": None}
    te = a.std() * math.sqrt(ann)
    return {"te": float(te), "ir": float(a.mean() * ann / te), "active": float(a.mean() * ann),
            "hit": float((a > 0).mean())}


# ---------------------------------------------------------------- stress, liquidity, limits

EQUITY_SCENARIOS = [
    ("COVID crash", "2020-02-19", "2020-03-23"),
    ("Q4 2018 selloff", "2018-09-20", "2018-12-24"),
    ("2022 rate shock", "2022-01-03", "2022-10-12"),
    ("Aug 2024 yen carry unwind", "2024-07-16", "2024-08-05"),
    ("Apr 2025 tariff shock", "2025-04-02", "2025-04-08"),
]
CRYPTO_SCENARIOS = [
    ("COVID crash", "2020-02-13", "2020-03-12"),
    ("May 2021 crash", "2021-04-13", "2021-07-20"),
    ("Terra/LUNA collapse", "2022-05-04", "2022-06-18"),
    ("FTX collapse", "2022-11-05", "2022-11-21"),
    ("Aug 2024 unwind", "2024-07-29", "2024-08-05"),
]


def stress(w, prices, bench, nav, scenarios, betas):
    """Replay historical windows on today's weights. A name with no price at the start of a window
    is proxied by beta x the benchmark's move in it."""
    out = []
    for label, a, b in scenarios:
        a, b = pd.Timestamp(a), pd.Timestamp(b)
        if bench.index[0] > a or bench.index[-1] < b:
            continue
        bm = float(bench.asof(b) / bench.asof(a) - 1)
        pnl, proxied = 0.0, []
        for s, wt in w.items():
            if not wt:
                continue
            col = prices[s] if s in prices else None
            p0 = col.asof(a) if col is not None else np.nan
            if col is not None and np.isfinite(p0) and p0 > 0 and col.first_valid_index() <= a:
                r = float(col.asof(b) / p0 - 1)
            else:
                r, _ = float(betas.get(s, 1.0)) * bm, proxied.append(s)
            pnl += wt * r
        out.append({"label": label, "start": str(a.date()), "end": str(b.date()), "bench": bm, "ret": pnl,
                    "pnl": pnl * nav, "proxied": proxied})
    return out


def liquidity(book, adv_usd, participation=0.10):
    """Days to exit each position trading at most `participation` of average daily dollar volume."""
    rows = []
    for p in book:
        adv = adv_usd.get(p["sym"])
        dte = abs(p["mv"]) / (participation * adv) if adv else None
        rows.append({"sym": p["sym"], "mv": p["mv"], "adv": adv, "pct_adv": abs(p["mv"]) / adv if adv else None, "days": dte})
    rows.sort(key=lambda r: -(r["days"] or 0))
    known = [r for r in rows if r["days"] is not None]
    one_day = sum(abs(r["mv"]) * min(1.0, 1 / r["days"]) if r["days"] else abs(r["mv"]) for r in known)
    tot = sum(abs(r["mv"]) for r in known)
    return {"participation": participation, "rows": rows, "max_days": max((r["days"] for r in known), default=None),
            "one_day": one_day / tot if tot else None}


def light(u):
    return "red" if u >= 1 else "amber" if u >= 0.9 else "green"


def limits(items):
    """[(name, value, limit, kind, fmt)] -> rows with utilization and a traffic light."""
    rows = []
    for name, value, limit, kind, fmt in items:
        if value is None or not limit:
            continue
        u = abs(value) / limit
        rows.append({"name": name, "value": value, "limit": limit, "util": u, "light": light(u), "kind": kind, "fmt": fmt})
    return rows


# ---------------------------------------------------------------- signal diagnostics

def signal_ic(panels, prices, horizons=(1, 5, 21, 63), pooled=False, months=None):
    """Spearman IC of each score panel vs forward returns, sampled at month ends.

    Cross-sectional by default (one IC per month, then mean and t-stat). pooled=True ranks
    across assets and dates together, for time-series signals with few assets."""
    month_ends = prices.resample("ME").last().index
    rows = [r for r in prices.index.searchsorted(month_ends, side="right") - 1 if r >= 1]
    if months:
        rows = rows[-months:]
    step = float(np.median(np.diff(rows))) if len(rows) > 1 else 1.0  # rows between samples
    out = {}
    for name, z in panels.items():
        z = z.reindex(prices.index)
        res = {}
        for h in horizons:
            fwd = prices.shift(-h) / prices - 1
            ok_rows = [r for r in rows if r + h < len(prices) and z.iloc[r].notna().sum() > 2]
            if pooled:
                a = pd.concat([z.iloc[r] for r in ok_rows]).values
                b = pd.concat([fwd.iloc[r] for r in ok_rows]).values
                m = np.isfinite(a) & np.isfinite(b)
                n = int(m.sum())
                ic = pd.Series(a[m]).rank().corr(pd.Series(b[m]).rank()) if n > 10 else np.nan
                # Overlapping windows (h longer than the sampling step) are not independent: shrink n.
                n_eff = n * min(1.0, step / h)
                res[str(h)] = {"ic": ic, "t": ic * math.sqrt(n_eff) if ic == ic else None, "n": n}
                continue
            ics = []
            for r in ok_rows:
                a, b = z.iloc[r], fwd.iloc[r]
                m = a.notna() & b.notna()
                if m.sum() > 5:
                    ics.append(a[m].rank().corr(b[m].rank()))
            ics = pd.Series(ics).dropna()
            res[str(h)] = {"ic": ics.mean() if len(ics) else None,
                           "t": ics.mean() / ics.std() * math.sqrt(len(ics)) if len(ics) > 2 and ics.std() > 0 else None,
                           "hit": float((ics > 0).mean()) if len(ics) else None, "n": len(ics)}
        out[name] = res
    return out


def signal_corr(panels, prices, months=36):
    """Average cross-sectional rank correlation between signals at month ends."""
    month_ends = prices.resample("ME").last().index
    rows = (prices.index.searchsorted(month_ends, side="right") - 1)[-months:]
    names = list(panels)
    acc = np.zeros((len(names), len(names)))
    n = 0
    for r in rows:
        df = pd.DataFrame({k: panels[k].iloc[r] for k in names}).dropna()
        if len(df) > 5:
            acc += df.rank().corr().fillna(0).values
            n += 1
    return {"names": names, "corr": (acc / n).round(2).tolist() if n else None}


def crowding(panels, rets, window=63, months=36):
    """Co-movement crowding (Lou & Polk's comomentum): average pairwise correlation of the top third's
    market-adjusted returns over the last `window` days, now and as a percentile of its own history."""
    resid = rets.sub(rets.mean(axis=1), axis=0)
    month_ends = rets.resample("ME").last().index
    rows = [r for r in (rets.index.searchsorted(month_ends, side="right") - 1)[-months:] if r >= window]
    if not rows or rows[-1] != len(rets) - 1:
        rows.append(len(rets) - 1)

    def co(z, r):
        top = z.iloc[r].dropna()
        top = top.nlargest(max(3, len(top) // 3)).index
        c = resid[top].iloc[r - window + 1:r + 1].corr().values
        return float(c[np.triu_indices_from(c, 1)].mean())

    out = {}
    for name, z in panels.items():
        z = z.reindex(rets.index)
        hist = [co(z, r) for r in rows if z.iloc[r].notna().sum() > 5]
        if len(hist) < 3:
            continue
        now = hist[-1]
        out[name] = {"now": now, "pct": float((np.array(hist) <= now).mean()), "median": float(np.median(hist))}
    return out


def capacity(weight_panels, adv_usd, participation=0.10):
    """AUM at which the average rebalance trade in any name stays under `participation` of its ADV
    in one day: min_i participation * ADV_i / mean |dw_i| over rebalances."""
    out = {}
    for name, W in weight_panels.items():
        d = W.diff().abs()
        d = d[d.sum(axis=1) > 1e-6]
        if d.empty:
            continue
        avg = d.mean()
        caps = {s: participation * adv_usd[s] / avg[s] for s in avg.index if avg[s] > 1e-6 and adv_usd.get(s)}
        if caps:
            s = min(caps, key=caps.get)
            out[name] = {"aum": float(caps[s]), "binding": s, "turnover": float(d.sum(axis=1).mean())}
    return out


def standalone_weights(z, rows, mode="long_only"):
    """Long-only top-third weights of one signal at the given rows (to measure its own turnover)."""
    return pd.DataFrame({z.index[r]: portfolio.alpha_to_weights(z.iloc[r], mode) for r in rows}).T


# ---------------------------------------------------------------- transaction cost analysis

def tca(blotter, raw, yahoo_sym, crypto, assumed_bps):
    """Decision (signal close) -> arrival (open of the fill day) -> fill, per order, plus summary.

    Delay is the overnight move before the order could trade; impact is fill vs arrival. Both are
    signed so that positive = cost. Crypto orders trade around the clock, so no arrival split."""
    rows = []
    for o in blotter:
        f = abs(o.get("filled") or 0)
        side = 1 if o["qty"] > 0 else -1
        r = {"time": o["time"], "symbol": o["symbol"], "side": side, "filled": f, "ordered": abs(o["qty"]),
             "status": o["status"], "decision": o.get("ref"), "fill": o.get("price") if f else None,
             "arrival": None, "delay_bps": None, "impact_bps": None, "slip_bps": o.get("slip_bps"),
             "participation": None, "notional": f * o["price"] if f and o.get("price") else 0.0}
        if f and o.get("price") and o.get("time"):
            ys = yahoo_sym(o["symbol"])
            day = pd.Timestamp(o["time"]).tz_convert("UTC" if crypto else "America/New_York").tz_localize(None).normalize()
            if not crypto and ys in raw["Open"] and day in raw.index:
                op = raw["Open"][ys].get(day)
                if op and np.isfinite(op):
                    r["arrival"] = float(op)
                    r["impact_bps"] = side * (o["price"] / op - 1) * 1e4
                    if o.get("ref"):
                        r["delay_bps"] = side * (op / o["ref"] - 1) * 1e4
            if ys in raw["Volume"] and day in raw.index:
                v = raw["Volume"][ys].get(day)
                if v and np.isfinite(v) and v > 0:
                    r["participation"] = (r["notional"] / v) if crypto else f / v  # Yahoo crypto volume is in dollars
        rows.append(r)
    done = [r for r in rows if r["status"] in ("filled", "partially_filled", "canceled", "expired", "rejected", "done_for_day")]
    ordered = sum(r["ordered"] for r in done)

    def wavg(k):
        xs = [(r[k], r["notional"]) for r in rows if r[k] is not None and r["notional"]]
        n = sum(w for _, w in xs)
        return sum(v * w for v, w in xs) / n if n else None

    shortfall = sum(r["slip_bps"] / 1e4 * r["notional"] for r in rows if r["slip_bps"] is not None)
    parts = [r["participation"] for r in rows if r["participation"] is not None]
    return {"rows": rows, "summary": {
        "orders": len(rows), "filled": sum(1 for r in rows if r["filled"]),
        "fill_rate": sum(r["filled"] for r in done) / ordered if ordered else None,
        "slip_bps": wavg("slip_bps"), "delay_bps": wavg("delay_bps"), "impact_bps": wavg("impact_bps"),
        "shortfall": shortfall, "notional": sum(r["notional"] for r in rows),
        "max_participation": max(parts) if parts else None, "assumed_bps": assumed_bps}}


# ---------------------------------------------------------------- data health

def _check(name, status, detail):
    return {"check": name, "status": status, "detail": detail}


def data_health(prices, quotes, as_of_expected, crypto, positions, fills_book, identity, blotter, meta, now):
    """identity: (account equity, cash, market value of every position) or None."""
    # Freshness, gaps, suspicious moves (corporate actions / bad ticks), broker reconciliation.
    out = []
    last = prices.index[-1]
    lag = len(pd.bdate_range(last, as_of_expected)) - 1 if not crypto else (as_of_expected - last).days
    out.append(_check("Price history fresh", "ok" if lag <= 0 else "warn" if lag == 1 else "fail",
                      f"latest close {last.date()}, expected {as_of_expected.date()}"))
    stale_q = sorted(s for s, q in quotes.items() if q and q["date"] < str(last.date()))
    out.append(_check("Quotes complete", "ok" if not stale_q else "warn",
                      f"{len(quotes)} symbols" + (f"; behind: {', '.join(stale_q[:8])}" if stale_q else "")))
    miss = [s for s in prices.columns if not np.isfinite(prices[s].iloc[-1])]
    out.append(_check("No missing prices", "ok" if not miss else "fail", ", ".join(miss) or "every name priced today"))
    tail = prices.iloc[-6:]
    flat = [s for s in prices.columns if tail[s].nunique() == 1]
    out.append(_check("No stale prices", "ok" if not flat else "warn",
                      ", ".join(flat) if flat else "every name moved in the last 5 sessions"))
    lim = 0.5 if crypto else 0.25
    r = prices.pct_change().iloc[-10:]
    jumps = [f"{s} {r[s].abs().idxmax().date()} {r[s].loc[r[s].abs().idxmax()]:+.0%}" for s in prices.columns if (r[s].abs() > lim).any()]
    out.append(_check("Corporate actions / bad ticks", "ok" if not jumps else "warn",
                      "; ".join(jumps) if jumps else f"no daily move over {lim:.0%} in 10 sessions (prices split- and dividend-adjusted)"))
    bad = []
    for s, p in positions.items():
        q = fills_book.get(s, (0.0, 0.0))[0]
        if abs(q - p["qty"]) > max(1e-6, 0.03 * abs(p["qty"])):
            bad.append(f"{s} broker {p['qty']:g} vs orders {q:g}")
    out.append(_check("Positions reconcile to fills", "ok" if not bad else "warn",
                      "; ".join(bad[:6]) if bad else f"{len(positions)} positions match the order history"))
    if identity and identity[1] is not None and identity[0]:
        equity, cash, mv = identity
        diff = equity - cash - mv
        ok = abs(diff) <= 0.005 * equity
        out.append(_check("Cash + positions = equity", "ok" if ok else "warn", f"difference ${diff:,.0f}"))
    open_ = [o for o in blotter if o["status"] in ("new", "accepted", "pending_new", "partially_filled", "held")
             and o.get("time") and pd.Timestamp(o["time"]) < now - pd.Timedelta(days=1)]
    out.append(_check("No stuck orders", "ok" if not open_ else "warn",
                      ", ".join(f"{o['symbol']} {o['status']}" for o in open_[:6]) or "no open order older than a day"))
    lr = meta.get("last_run")
    age = (now - pd.Timestamp(lr)).days if lr else None
    out.append(_check("Trading job ran", "ok" if age is not None and age <= 4 else "warn",
                      f"last trading run {lr}" if lr else "no trading run recorded yet"))
    return out


# ---------------------------------------------------------------- next-trade preview

def preview_orders(orders, prices, positions, nav, sc, cost_bps, sectors=None):
    """Pre-trade view of a list of (symbol, qty): notional, weights after, cost, limit checks."""
    rows, cash = [], 0.0
    post = {s: p["qty"] for s, p in positions.items()}
    for s, q in orders:
        px = float(prices[s])
        n = q * px
        cash -= n
        post[s] = post.get(s, 0) + q
        rows.append({"sym": s, "qty": q, "px": px, "notional": n, "capped": abs(n) >= sc["max_order_notional"] * 0.999})
    mv = {s: q * float(prices[s]) for s, q in post.items() if abs(q) > 1e-9 and s in prices}
    w = {s: v / nav for s, v in mv.items()} if nav else {}
    sec = pd.Series(w).groupby(lambda s: sectors(s)).sum() if sectors and w else pd.Series(dtype=float)
    gross_trade = sum(abs(r["notional"]) for r in rows)
    return {"orders": rows, "turnover": gross_trade / nav if nav else None, "cost": gross_trade * cost_bps / 1e4,
            "cash_change": cash, "post_gross": sum(abs(v) for v in w.values()), "post_max": max(w.values(), default=0),
            "post_max_sector": float(sec.max()) if len(sec) else None, "post_names": len(w),
            "buys": sum(r["notional"] for r in rows if r["notional"] > 0),
            "sells": -sum(r["notional"] for r in rows if r["notional"] < 0)}


def next_dates(name, sc, strat, m, today, cbd):
    """When the next rebalance and swap check are due (calendar estimate)."""
    if name == "crypto":
        last = m.get("last_signal")
        # The job runs on weekdays, so a due date on a weekend trades the next Monday.
        due = pd.Timestamp(last) + pd.Timedelta(days=sc["rebalance_days"]) + pd.offsets.BDay(0) if last else None
        return {"rebalance": str(due.date()) if due is not None else "next trading run", "swap": None}
    days = pd.date_range(today, today + pd.Timedelta(days=75), freq=cbd)
    last_p = pd.Period(m["last_signal"], "M") if m.get("last_signal") else None
    reb = next((d for d in days if (d + cbd).month != d.month and pd.Period(d, "M") != last_p), None)
    swap = None
    if not m.get("last_signal"):
        return {"rebalance": "next trading run", "swap": None}
    if strat.swap_every:
        anchor = max(d for d in (m.get("last_signal"), m.get("last_swap")) if d)
        # The job counts trading days in the price data; plain weekdays match it better than the federal
        # calendar, which closes on Columbus and Veterans Day when NYSE is open.
        swap = pd.Timestamp(anchor) + strat.swap_every * pd.offsets.BDay()
        swap = max(swap, today)
    return {"rebalance": str(reb.date()) if reb is not None else None, "swap": str(swap.date()) if swap is not None else None}
