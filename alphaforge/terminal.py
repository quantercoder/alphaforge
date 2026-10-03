"""Builds the terminal's data files: site/data.json (equities) and site/crypto.json (crypto)."""
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import backtest, metrics, signals
from .backtest import Config
from .data import MARKET_STRIP, risk_free
from .refdata import CRYPTO, name, sector, yahoo


def _clean(o):
    """JSON-safe: NaN/inf -> null, numpy scalars -> Python, floats rounded."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(o) else round(float(o), 6)
    if isinstance(o, (np.integer, np.bool_)):
        return o.item()
    return o


def _write(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(_clean(data), f, separators=(",", ":"), allow_nan=False)


# ---------------------------------------------------------------- market data

def quote(raw, ysym, year=252):
    if ysym not in raw["Close"]:
        return None
    c = raw["Close"][ysym].dropna()
    if len(c) < 2:
        return None
    h, lo, v = raw["High"][ysym].dropna(), raw["Low"][ysym].dropna(), raw["Volume"][ysym].dropna()
    prior_year = c[c.index.year < c.index[-1].year]
    return {
        "last": c.iloc[-1], "chg": c.iloc[-1] - c.iloc[-2], "pct": c.iloc[-1] / c.iloc[-2] - 1,
        "hi52": h.iloc[-year:].max(), "lo52": lo.iloc[-year:].min(),
        "ytd": c.iloc[-1] / prior_year.iloc[-1] - 1 if len(prior_year) else None,
        "vol20": v.iloc[-20:].mean() if len(v) else None,
        "spark": c.iloc[-30:].round(6).tolist(), "date": str(c.index[-1].date()),
    }


def ohlc(raw, ysym, n=260):
    if ysym not in raw["Close"]:
        return []
    df = pd.DataFrame({k: raw[k][ysym] for k in ["Open", "High", "Low", "Close", "Volume"]}).dropna().iloc[-n:]
    return [[str(i.date()), *np.round(r[:4], 6), int(r[4])] for i, r in zip(df.index, df.values)]


# ---------------------------------------------------------------- book, blotter

def average_costs(fills):
    """Average-cost basis per symbol rebuilt from fills (oldest first): {symbol: (qty, avg_cost)}.

    Buys move the average; sells reduce the quantity at the same average; a position that goes
    flat starts over. Used when the broker reports a zero cost basis."""
    book = {}
    for f in fills:
        q, avg = book.get(f["symbol"], (0.0, 0.0))
        n = f["qty"]
        if n > 0:
            avg = (q * avg + n * f["price"]) / (q + n) if q + n else 0.0
        q += n
        if abs(q) < 1e-9:
            q, avg = 0.0, 0.0
        book[f["symbol"]] = (q, avg)
    return book


def repair_costs(positions, broker):
    """Fill in a zero average cost from the order history when the history explains the position.

    Crypto fees are paid in coin, so the position is a little smaller than the sum of fills; allow 3%.
    If the history doesn't explain the quantity, the cost stays unknown instead of being invented."""
    broken = [s for s, p in positions.items() if not p.get("avg_cost")]
    if not broken or not hasattr(broker, "fills"):
        return positions
    rebuilt = average_costs(broker.fills("2015-01-01T00:00:00Z"))
    out = dict(positions)
    for s in broken:
        p = {**positions[s], "cost_basis": None, "upl": None, "upl_pct": None}
        q, avg = rebuilt.get(s, (0.0, 0.0))
        if avg > 0 and q and abs(q - p["qty"]) <= 0.03 * abs(p["qty"]):
            p["avg_cost"], p["cost_basis"], p["cost_source"] = avg, p["qty"] * avg, "order history"
        else:
            p["cost_source"] = "unknown"
        out[s] = p
    return out


def book_rows(positions, nav, px, prev):
    """Per-position P&L in the units Alpaca shows. Broker fields win; the rest is computed."""
    rows = []
    for s, p in positions.items():
        last = p.get("last") or (float(px[s]) if s in px else None)
        if last is None:
            continue
        qty, avg = p["qty"], p["avg_cost"]
        mv = p.get("mv") or qty * last
        known = p.get("cost_source") != "unknown"
        cost = (p.get("cost_basis") or qty * avg) if known else None
        upl = p["upl"] if p.get("upl") is not None else (mv - cost if known else None)
        lastday = p.get("lastday") or (float(prev[s]) if s in prev else None)
        day = p["day_pl"] if p.get("day_pl") is not None else ((last - lastday) * qty if lastday else None)
        if p.get("day_pl") is not None and qty:
            # Alpaca measures today's P&L from the entry price for shares bought today. Back out the
            # reference price it used, so live ticks in the browser reproduce Alpaca's number.
            lastday = last - p["day_pl"] / qty
        rows.append({"sym": s, "name": name(s), "qty": qty, "avg": avg if known else None, "last": last, "mv": mv,
                     "cost": cost, "weight": mv / nav if nav else None, "upl": upl,
                     "upl_pct": upl / abs(cost) if cost and upl is not None else None, "day_pl": day,
                     "lastday": lastday, "day_pct": (last / lastday - 1) if lastday else None,
                     "cost_source": p.get("cost_source", "broker")})
    rows.sort(key=lambda x: -abs(x["mv"]))
    tot = {k: sum(r[k] or 0 for r in rows) for k in ("mv", "day_pl")}
    priced = [r for r in rows if r["upl"] is not None]  # unrealized P&L only where the cost is known
    tot["cost"] = sum(r["cost"] for r in priced)
    tot["upl"] = sum(r["upl"] for r in priced)
    tot["upl_pct"] = tot["upl"] / abs(tot["cost"]) if tot["cost"] else None
    tot["unknown_cost"] = len(rows) - len(priced)
    tot["weight"] = tot["mv"] / nav if nav else None
    return rows, tot


def blotter_rows(broker, cls, sleeve, state_dir):
    """This sleeve's orders, newest first, with slippage against the price at signal time."""
    refs = {}
    path = f"{state_dir}/orders.jsonl"
    local = []
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                o = json.loads(line)
                local.append(o)
                for k in ("id", "client_id"):
                    if o.get(k):
                        refs[o[k]] = o.get("price")
    if hasattr(broker, "orders"):
        rows = [o for o in broker.orders() if o["cls"] == cls]
    else:
        rows = [{**o, "time": o.get("time") or o["date"], "filled": o["qty"] if o["status"] == "filled" else 0,
                 "cls": cls} for o in local if o.get("sleeve", "equity") == sleeve][::-1][:200]
    out, slips = [], []
    for o in rows:
        ref = o.get("ref") or refs.get(o.get("id")) or refs.get(o.get("client_id"))
        if not hasattr(broker, "orders"):
            ref = None  # simulator fills are the reference price plus fixed slippage by construction
        slip = None
        if ref and o.get("price") and o.get("filled"):
            slip = (1 if o["filled"] > 0 else -1) * (o["price"] / ref - 1) * 1e4
            slips.append(slip)
        out.append({"time": o["time"], "symbol": o["symbol"], "qty": o["qty"], "filled": o.get("filled"),
                    "price": o.get("price"), "status": o["status"], "ref": ref, "slip_bps": slip,
                    "auto": (o.get("client_id") or "").startswith("af-") or o.get("id") in refs
                    or not hasattr(broker, "orders")})
    return out, (float(np.mean(slips)) if slips else None, len(slips))


# ---------------------------------------------------------------- risk

def risk_block(w, rets, bench_rets, nav, ann, lookback, shock, shock_label, sort_key, shrink=0.3):
    """Forecast vs realized vol, parametric and historical VaR, beta, stress, risk contributions."""
    syms = list(w.index)
    hist = rets[syms].iloc[-lookback:].fillna(0)
    sample = hist.cov().values
    cov = (1 - shrink) * sample + shrink * np.diag(np.diag(sample))
    wv = w.values
    var_d = max(float(wv @ cov @ wv), 0)
    sigma = math.sqrt(var_d * ann)
    realized = float((hist @ wv).std() * math.sqrt(ann))
    year = rets[syms].iloc[-ann:].fillna(0) @ wv
    hvar = -float(year.quantile(0.05)) * nav if len(year) > 20 else None
    br = bench_rets.reindex(rets.index).iloc[-ann:]
    betas = rets[syms].iloc[-ann:].apply(lambda c: c.cov(br) / br.var()).fillna(0)
    beta = float((w * betas).sum())
    contrib = pd.Series(wv * (cov @ wv) / var_d if var_d else np.zeros(len(wv)), index=syms)
    order = sorted(syms, key=sort_key)
    return {"ex_ante_vol": sigma, "realized_vol": realized, "var95": 1.645 * math.sqrt(var_d) * nav,
            "hvar95": hvar, "beta": beta, "gross": float(w.abs().sum()), "net": float(w.sum()),
            "stress": {"label": shock_label, "pnl": beta * shock * nav},
            "contrib": {s: float(v) for s, v in contrib[contrib.abs() > 1e-4].sort_values(ascending=False).items()},
            "corr_syms": order, "corr": rets[order].iloc[-lookback:].corr().round(2).fillna(0).values.tolist()}


# ---------------------------------------------------------------- research

def growth_block(res, lines, ann):
    """Weekly growth of $1 for the strategy and comparison lines, plus drawdowns and stats."""
    t0 = metrics.first_trade(res)
    r = res.returns.loc[t0:]
    rf = None if res.rf is None else res.rf.loc[t0:]
    series = {"Strategy": r, **{k: v.loc[t0:] for k, v in lines.items()}}
    freq = "W-FRI" if ann == 252 else "W-SUN"
    curves = pd.DataFrame({k: (1 + v).cumprod() for k, v in series.items()}).resample(freq).last()
    dd = pd.DataFrame({k: metrics.drawdown(v) for k, v in series.items()}).resample(freq).min()
    compare = [{"name": k, **{m: metrics.stats(v, rf, ann)[m] for m in ("CAGR", "Ann. Vol", "Sharpe", "Max Drawdown")}}
               for k, v in series.items()]
    mt = metrics.monthly_table(r)
    return {"summary": metrics.summary(res), "start": str(t0.date()), "dates": [str(i.date()) for i in curves.index],
            "lines": {k: curves[k].tolist() for k in curves}, "drawdown": {k: dd[k].tolist() for k in dd},
            "compare": compare, "rf_avg": float(rf.mean() * ann) if rf is not None else None,
            "monthly": {"years": [int(y) for y in mt.index], "cols": list(mt.columns), "values": mt.values.tolist()}}


def _curve(state_dir, col):
    path = f"{state_dir}/equity.csv"
    if not os.path.exists(path):
        return pd.Series(dtype=float)
    c = pd.read_csv(path, index_col=0)
    return c[col].dropna() if col in c else pd.Series(dtype=float)


def _status(lc, sc, m, nav, rule):
    return {"broker": lc["broker"], "live_money": bool(lc["live_money"]) and lc["broker"] == "alpaca",
            "halted": m.get("halted", False), "last_signal": m.get("last_signal"), "last_swap": m.get("last_swap"),
            "pending": (m.get("pending") or {}).get("signal_date"), "rule": rule, "nav": nav,
            "high_water": m.get("high_water"), "drawdown": (nav / m["high_water"] - 1) if m.get("high_water") else 0,
            "halt_at": -sc["max_drawdown_halt"]}


# ---------------------------------------------------------------- pages

def build(raw, prices, bench, lc, broker, state_dir, site_dir, craw=None, cprices=None):
    from .live import _load_meta, navs  # local import: live imports this module lazily too

    meta = _load_meta(f"{state_dir}/meta.json")
    px_all = prices.iloc[-1].dropna()
    if cprices is not None:
        px_all = pd.concat([px_all, cprices.iloc[-1].dropna()])
    nv = navs(broker, lc, meta, px_all)
    acct = broker.account() if hasattr(broker, "account") else {"equity": nv["account"], "cash": getattr(broker, "cash", None)}
    acct_curve = pd.Series(dict(broker.history()), dtype=float) if hasattr(broker, "history") else _curve(state_dir, "account")
    account = {**acct, "equity_nav": nv["equity"], "crypto_nav": nv.get("crypto"), "crypto_mv": nv["crypto_mv"],
               "crypto_enabled": lc["crypto"]["enabled"],
               "dates": list(acct_curve.index.astype(str)), "curve": acct_curve.tolist()}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    _write(f"{site_dir}/data.json", equity_page(raw, prices, bench, lc, broker, state_dir, meta, nv, account, now))
    if cprices is not None:
        _write(f"{site_dir}/crypto.json", crypto_page(craw, cprices, lc, broker, state_dir, meta, nv, account, now))


def equity_page(raw, prices, bench, lc, broker, state_dir, meta, nv, account, now):
    strat = Config(**lc["strategy"])
    m = meta.get("equity", {})
    rets = prices.pct_change()
    universe = list(prices.columns)
    shown = list(dict.fromkeys(universe + ["SPY"] + list(lc.get("watchlist", []))))
    rf = risk_free(raw, 252)

    res = backtest.run_backtest(prices, strat, bench, rf)
    base = dict(cost_bps=strat.cost_bps, slippage_bps=strat.slippage_bps, warmup=strat.warmup)
    ew = backtest.run_backtest(prices, Config(model="equal", mode="equal", target_vol=None, max_weight=1.0,
                                              max_leverage=1.0, **base), None, rf)
    mom = backtest.run_backtest(prices, Config(**{**lc["strategy"], "swap_every": 0, "factor_weights": {
        "momentum": 1.0, "reversal": 0, "low_vol": 0, "quality_trend": 0}}), None, rf)
    research = growth_block(res, {"SPY": res.benchmark, f"Equal weight {len(universe)}": ew.returns,
                                  "Momentum only": mom.returns}, 252)

    scores = signals.factor_scores(prices)
    alpha = signals.alpha_panel(prices, strat)
    tgt = backtest.targets_at(alpha, rets, len(prices) - 1, strat)
    sig = [{"sym": s, "alpha": alpha.iloc[-1][s], "target": tgt[s], "sector": sector(s),
            **{f: sc.iloc[-1][s] for f, sc in scores.items()}} for s in universe]
    sig.sort(key=lambda x: -(x["alpha"] if x["alpha"] == x["alpha"] else -9))

    nav = nv["equity"]
    pos = repair_costs({s: p for s, p in nv["positions"].items() if p["cls"] == "us_equity"}, broker)
    book, totals = book_rows(pos, nav, prices.iloc[-1], prices.iloc[-2])
    w = pd.Series({x["sym"]: x["weight"] for x in book if x["sym"] in universe}, dtype=float).reindex(universe).fillna(0)
    risk = risk_block(w, rets, bench.pct_change(), nav, 252, strat.cov_lookback, -0.10, "S&P 500 -10%",
                      lambda s: (sector(s), s))
    sectors = pd.Series({s: w[s] for s in universe}).groupby(sector).sum()
    risk["sectors"] = {k: float(v) for k, v in sectors[sectors.abs() > 1e-4].sort_values(ascending=False).items()}
    risk["exposures"] = {f: float((w * sc.iloc[-1].fillna(0)).sum()) for f, sc in scores.items()}
    blotter, slip = blotter_rows(broker, "us_equity", "equity", state_dir)

    rule = "month-end rebalance" + (f", swap worst {strat.swap_count} every {strat.swap_every}d" if strat.swap_every else "")
    return {
        "page": "equity", "generated_at": now, "as_of": str(prices.index[-1].date()),
        "status": {**_status(lc, lc, m, nav, rule), "mode": strat.mode, "target_vol": strat.target_vol,
                   "cost_bps": strat.cost_bps + strat.slippage_bps},
        "strip": {k: quote(raw, v) for k, v in MARKET_STRIP.items() if v in raw["Close"]},
        "universe": universe,
        "names": {s: [name(s), sector(s)] for s in shown},
        "quotes": {s: q for s in shown if (q := quote(raw, s))},
        "ohlc": {s: b for s in shown if (b := ohlc(raw, s))},
        "backtest": research, "signals": sig, "account": account,
        "sleeve_curve": {"dates": list(_curve(state_dir, "equity").index), "curve": _curve(state_dir, "equity").tolist()},
        "book": book, "totals": totals, "blotter": blotter, "slippage": {"avg_bps": slip[0], "n": slip[1]},
        "risk": risk,
    }


def crypto_page(craw, cprices, lc, broker, state_dir, meta, nv, account, now):
    cc = lc["crypto"]
    strat = Config(**cc["strategy"])
    m = meta.get("crypto", {})
    rets = cprices.pct_change()
    universe = list(cprices.columns)
    btc = cprices["BTC/USD"] if "BTC/USD" in cprices else cprices.iloc[:, 0]

    res = backtest.run_backtest(cprices, strat, btc)
    ew = backtest.run_backtest(cprices, Config(model="equal", mode="equal", target_vol=None, max_weight=1.0,
                                               max_leverage=1.0, rebalance="W-SUN", cost_bps=strat.cost_bps,
                                               slippage_bps=strat.slippage_bps, warmup=strat.warmup, ann=365))
    research = growth_block(res, {"BTC buy & hold": res.benchmark, f"Equal weight {len(universe)}": ew.returns}, 365)

    trend = signals.trend_score(cprices)
    tgt = backtest.targets_at(trend, rets, len(cprices) - 1, strat)
    lp = np.log(cprices)
    sig = [{"sym": s, "alpha": trend.iloc[-1][s], "target": tgt[s],
            **{f"r{n}": float(lp[s].iloc[-1] - lp[s].iloc[-1 - n]) for n in (20, 60, 120)},
            "vol": float(rets[s].iloc[-60:].std() * math.sqrt(365))} for s in universe]
    sig.sort(key=lambda x: (-(x["alpha"] if x["alpha"] == x["alpha"] else -9), -x["r60"]))

    nav = nv.get("crypto") or cc["budget"]
    pos = repair_costs({s: p for s, p in nv["positions"].items() if p["cls"] == "crypto"}, broker)
    book, totals = book_rows(pos, nav, cprices.iloc[-1], cprices.iloc[-2])
    w = pd.Series({x["sym"]: x["weight"] for x in book if x["sym"] in universe}, dtype=float).reindex(universe).fillna(0)
    risk = risk_block(w, rets, btc.pct_change(), nav, 365, strat.cov_lookback, -0.20, "Bitcoin -20%",
                      lambda s: -float(trend.iloc[-1].get(s, 0) or 0))
    blotter, slip = blotter_rows(broker, "crypto", "crypto", state_dir)
    unmanaged = [r["sym"] for r in book if r["sym"] not in universe]

    quotes = {s: q for s in universe if (q := quote(craw, yahoo(s), 365))}
    return {
        "page": "crypto", "generated_at": now, "as_of": str(cprices.index[-1].date()),
        "status": {**_status(lc, cc, m, nav, f"weekly trend rebalance, {cc['rebalance_days']}d"),
                   "mode": "trend", "target_vol": strat.target_vol, "budget": cc["budget"],
                   "cash": nv.get("crypto_cash"), "started": m.get("start"), "unmanaged": unmanaged,
                   "cost_bps": strat.cost_bps + strat.slippage_bps},
        "strip": {s.split("/")[0]: quotes.get(s) for s in universe},
        "universe": universe,
        "names": {s: [CRYPTO.get(s, s), "Crypto"] for s in universe},
        "quotes": quotes,
        "ohlc": {s: b for s in universe if (b := ohlc(craw, yahoo(s), 365))},
        "backtest": research, "signals": sig, "account": account,
        "sleeve_curve": {"dates": list(_curve(state_dir, "crypto").index), "curve": _curve(state_dir, "crypto").tolist()},
        "book": book, "totals": totals, "blotter": blotter, "slippage": {"avg_bps": slip[0], "n": slip[1]},
        "risk": risk,
    }
