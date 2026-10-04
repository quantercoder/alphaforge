"""Builds the terminal's data files: site/data.json (equities) and site/crypto.json (crypto)."""
import json
import math
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import analytics, backtest, metrics, portfolio, signals
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
            "stress": {"label": shock_label, "pnl": beta * shock * nav}, "betas": {s: float(v) for s, v in betas.items()},
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
    bench_key = next(iter(lines))
    compare = [{"name": k, **{m: metrics.stats(v, rf, ann)[m] for m in ("CAGR", "Ann. Vol", "Sharpe", "Max Drawdown")},
                **(analytics.active_stats(v, series[bench_key], ann) if k != bench_key else {})}
               for k, v in series.items()]
    mt = metrics.monthly_table(r)
    return {"summary": metrics.summary(res), "start": str(t0.date()), "dates": [str(i.date()) for i in curves.index],
            "lines": {k: curves[k].tolist() for k in curves}, "drawdown": {k: dd[k].tolist() for k in dd},
            "compare": compare, "bench_name": bench_key, "rf_avg": float(rf.mean() * ann) if rf is not None else None,
            "monthly": {"years": [int(y) for y in mt.index], "cols": list(mt.columns), "values": mt.values.tolist()}}


def _curve(state_dir, col):
    path = f"{state_dir}/equity.csv"
    if not os.path.exists(path):
        return pd.Series(dtype=float)
    c = pd.read_csv(path, index_col=0)
    return c[col].dropna() if col in c else pd.Series(dtype=float)


def _paper_navs(state_dir, sleeve):
    """The sleeve's NAV at each trading run and its daily return. The equity sleeve's return is
    (change in account - change in crypto NAV) / yesterday's equity NAV, so carving out the crypto
    budget is not a loss; rows from before the crypto column existed take its first value."""
    path = f"{state_dir}/equity.csv"
    if not os.path.exists(path):
        return pd.Series(dtype=float), pd.Series(dtype=float)
    c = pd.read_csv(path, index_col=0, parse_dates=True).sort_index()
    if sleeve == "crypto":
        nav = c["crypto"].dropna() if "crypto" in c else pd.Series(dtype=float)
        return nav, nav.pct_change().dropna()
    acct = c["account"].fillna(c["equity"]) if "account" in c else c["equity"]
    cry = c["crypto"].bfill().fillna(0) if "crypto" in c else acct * 0
    nav = acct - cry
    return nav, ((acct.diff() - cry.diff()) / nav.shift(1)).dropna()


def tracking_block(state_dir, sleeve, prices, strat, bench, rf, ann, start=None):
    """Paper sleeve against a shadow backtest that started the same day with today's settings."""
    nav, r = _paper_navs(state_dir, sleeve)
    start = pd.Timestamp(start).tz_localize(None).normalize() if start else (nav.index[0] if len(nav) else None)
    nav = nav[nav.index >= start] if start is not None else nav
    if len(nav) < 1:
        return None
    shadow = backtest.run_backtest(prices, strat, bench, rf, start=start)
    s = (1 + shadow.returns.loc[start:]).cumprod().reindex(nav.index).ffill().fillna(1.0)
    rp, rs = r.reindex(nav.index[1:]), s.pct_change().iloc[1:]
    d = (rp - rs).dropna()
    return {"start": str(start.date()), "dates": [str(i.date()) for i in nav.index],
            "paper": (nav / nav.iloc[0]).tolist(), "shadow": (s / s.iloc[0]).tolist(), "n": len(d),
            "paper_ret": float(nav.iloc[-1] / nav.iloc[0] - 1), "shadow_ret": float(s.iloc[-1] / s.iloc[0] - 1),
            "te": float(d.std() * math.sqrt(ann)) if len(d) >= 5 else None,
            "corr": float(rp.corr(rs)) if len(d) >= 20 else None}


def _status(lc, sc, m, nav, rule):
    return {"broker": lc["broker"], "live_money": bool(lc["live_money"]) and lc["broker"] == "alpaca",
            "halted": m.get("halted", False), "last_signal": m.get("last_signal"), "last_swap": m.get("last_swap"),
            "pending": (m.get("pending") or {}).get("signal_date"), "rule": rule, "nav": nav,
            "high_water": m.get("high_water"), "drawdown": (nav / m["high_water"] - 1) if m.get("high_water") else 0,
            "halt_at": -sc["max_drawdown_halt"]}


# ---------------------------------------------------------------- desk: limits, preview, health, controls

# Monitoring limits. "hard" ones are enforced by the trading job (capped or halted); "soft" ones only
# light up here. Override any of them per sleeve with "limits" in live.json.
LIMITS = {
    "equity": {"max_sector": 0.40, "max_beta": 1.2, "var_pct": 0.025, "max_days_to_exit": 1.0, "vol_mult": 1.5,
               "max_te": 0.12, "drift": 1.2},
    "crypto": {"max_beta": 1.5, "var_pct": 0.08, "max_days_to_exit": 1.0, "vol_mult": 1.5, "drift": 1.2},
}
REPO = "https://github.com/quantercoder/alphaforge"


def _adv_usd(raw, syms, ysym, crypto, n=20):
    """20-day average dollar volume. Yahoo reports crypto volume in dollars already."""
    out = {}
    for s in syms:
        y = ysym(s)
        if y in raw["Volume"] and y in raw["Close"]:
            v, c = raw["Volume"][y].iloc[-n:], raw["Close"][y].iloc[-n:]
            x = float((v if crypto else v * c).mean())
            if x > 0:
                out[s] = x
    return out


def _expected_close(crypto, now):
    """The latest daily bar the data should have: yesterday (UTC) for crypto; for stocks today once
    the market has opened on a trading day, else the previous trading day."""
    from .live import _CBD
    if crypto:
        return pd.Timestamp(now.date()) - pd.Timedelta(days=1)
    ny = now.tz_convert("America/New_York")
    d = pd.Timestamp(ny.date())
    days = pd.date_range(d - pd.Timedelta(days=12), d, freq=_CBD)
    if days[-1] == d and ny.hour * 60 + ny.minute >= 570:
        return d
    return days[-1] if days[-1] < d else days[-2]


def _last_target(m, alpha, rets, prices, strat):
    """Weights of the last rebalance (stored by the job; rebuilt from history for older state)."""
    if m.get("target"):
        return m["target"]
    if not m.get("last_signal"):
        return {}
    i = prices.index.searchsorted(pd.Timestamp(m["last_signal"]), side="right") - 1
    return {k: float(v) for k, v in backtest.targets_at(alpha, rets, i, strat).items() if v} if i > 0 else {}


def exposure_rows(universe, book, target, bench, sector_fn):
    """Held, target and benchmark weight per name: drift = held - target, active = held - benchmark."""
    w = {r["sym"]: r["weight"] or 0.0 for r in book}
    syms = list(dict.fromkeys(list(w) + [s for s in universe if target.get(s) or bench.get(s)]))
    rows = []
    for s in syms:
        r = {"sym": s, "sector": sector_fn(s), "w": w.get(s, 0.0), "target": target.get(s, 0.0), "bench": bench.get(s, 0.0)}
        rows.append({**r, "drift": r["w"] - r["target"], "active": r["w"] - r["bench"]})
    rows.sort(key=lambda r: -abs(r["active"]))
    return rows


def preview_block(name, sc, strat, m, tgt, pos, nav, prices, alpha_row, cost_bps, sector_fn):
    """What the next rebalance (and swap check) would trade if it ran on today's prices."""
    from .live import _CBD, plan_orders, swap_orders
    px = prices.iloc[-1].dropna()
    w = {k: float(v) for k, v in tgt.items() if v and np.isfinite(v)}
    out = {"next": analytics.next_dates(name, sc, strat, m, prices.index[-1], _CBD),
           "rebalance": analytics.preview_orders(plan_orders(w, pos, nav, px, sc), px, pos, nav, sc, cost_bps, sector_fn),
           "require_approval": bool(sc.get("require_approval")), "awaiting": m.get("awaiting"),
           "max_order": sc["max_order_notional"], "min_trade": sc["min_trade_notional"],
           "approve_url": f"{REPO}/actions/workflows/terminal.yml"}
    if name == "equity" and strat.swap_every:
        held = {s: float(px[s]) / q["avg_cost"] - 1 for s, q in pos.items()
                if q["qty"] > 0 and s in px and (q.get("avg_cost") or 0) > 0}
        from .live import current_weights
        drop, add = portfolio.pick_swaps(held, alpha_row, strat.swap_count, current_weights(pos, nav, px).to_dict(),
                                         sector_fn, strat.max_sector)
        out["swap"] = {"drop": drop, "add": add, "pnl": {s: held[s] for s in drop},
                       **analytics.preview_orders(swap_orders(drop, add, pos, px, sc), px, pos, nav, sc, cost_bps, sector_fn)}
    return out


def limit_rows(kind, lc_limits, risk, model, liq, preview, st, strat, sc, nav, bench_label):
    L = {**LIMITS[kind], **(lc_limits or {})}
    w = [abs(v) for v in (risk.get("weights") or {}).values()]
    sectors = risk.get("sectors") or {}
    nxt = max([abs(o["notional"]) for o in preview["rebalance"]["orders"]] + [0])
    return analytics.limits([
        ("Gross exposure", risk["gross"], strat.max_leverage, "hard", "pct"),
        (f"Largest position (traded at ≤{strat.max_weight:.0%})", max(w, default=0), strat.max_weight * L["drift"], "hard", "pct"),
        ("Drawdown vs halt", st["drawdown"], st["halt_at"], "hard", "pct"),
        ("Largest next order", nxt or None, sc["max_order_notional"], "hard", "usd"),
        ("Forecast volatility", risk["ex_ante_vol"] if risk["gross"] else None,
         (strat.target_vol or 0) * L["vol_mult"], "soft", "pct"),
        (f"Beta to {bench_label}", risk["beta"] if risk["gross"] else None, L["max_beta"], "soft", "num"),
        ("Largest sector", max(sectors.values(), default=None), L.get("max_sector"), "soft", "pct"),
        ("1-day VaR 95% / NAV", risk["var95"] / nav if nav and risk["gross"] else None, L["var_pct"], "soft", "pct"),
        ("Tracking error vs benchmark", (model or {}).get("active", {}).get("vol") if (model or {}).get("active") else None,
         L.get("max_te"), "soft", "pct"),
        ("Days to exit at 10% ADV", liq["max_days"], L["max_days_to_exit"], "soft", "num"),
    ])


def _jsonl(path, n=60):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        lines = [x for x in f.readlines()[-n:] if x.strip()]
    return [json.loads(x) for x in lines[::-1]]


def controls_block(lc, name, sc, state_dir):
    kill = f"{state_dir}/KILL" if name == "equity" else f"{state_dir}/KILL_{name.upper()}"
    live = bool(lc["live_money"]) and lc["broker"] == "alpaca"
    confirm = os.environ.get("ALPHAFORGE_CONFIRM_LIVE") == "yes"
    return {
        "controls": [
            ["Broker", {"alpaca": "Alpaca " + ("LIVE MONEY" if live else "paper"), "sim": "Simulator"}.get(lc["broker"], lc["broker"]), "ok" if not live else "warn"],
            ["Real-money gate", "open: live_money and ALPHAFORGE_CONFIRM_LIVE both set" if live and confirm
             else "closed: needs live_money true AND ALPHAFORGE_CONFIRM_LIVE=yes", "warn" if live and confirm else "ok"],
            ["Kill switch", f"ARMED ({os.path.basename(kill)} present)" if os.path.exists(kill) else f"clear (commit state/{os.path.basename(kill)} to halt)",
             "fail" if os.path.exists(kill) else "ok"],
            ["Approval before trading", "required" if sc.get("require_approval") else "not required (set require_approval in live.json)", "ok"],
            ["Max order size", f"${sc['max_order_notional']:,.0f}", "ok"],
            ["Drawdown halt", f"{sc['max_drawdown_halt']:.0%} below the sleeve's peak", "ok"],
            ["Duplicate orders", "blocked: deterministic client order ids (af-...), retries return 'duplicate'", "ok"],
            ["Stale data", f"refuses to trade on prices older than {sc['max_data_age_days']} days", "ok"],
        ],
        "permissions": [
            ["View this terminal", "anyone with the link; read-only, holds no keys"],
            ["Place orders", "the GitHub Actions job only, with the repository's Alpaca secrets"],
            ["Approve a rebalance", "repository collaborators with write access: Actions > terminal > Run workflow > approve"],
            ["Change strategy or limits", "a commit to live.json, so every change is in the git history"],
            ["Trade real money", "live_money: true in live.json AND repository variable ALPHAFORGE_CONFIRM_LIVE=yes"],
            ["Halt trading", "commit state/KILL (stocks) or state/KILL_CRYPTO, or set variable ALPHAFORGE_KILL"],
            ["Stream live prices", "each viewer's own Alpaca key, kept in their browser"],
        ],
        "audit": _jsonl(f"{state_dir}/audit.jsonl"),
        "alerts": _jsonl(f"{state_dir}/alerts.jsonl"),
    }


def desk_block(kind, *, lc, sc, strat, m, raw, prices, bench, bench_label, universe, ysym, model, w, bench_w,
               res, book, risk, nav, st, tgt, alpha, rets, pos, positions_all, broker, blotter, quotes, px_all,
               scenarios, sector_fn, now, state_dir, last_run):
    """Everything the desk panels need for one sleeve."""
    crypto = kind == "crypto"
    ann = 365 if crypto else 252
    adv = _adv_usd(raw, list(dict.fromkeys(universe + [r["sym"] for r in book])), ysym, crypto)
    mdl = None
    if model is not None:
        mdl = {"total": analytics.decompose(w, model, ann), "active": analytics.decompose(w - bench_w, model, ann),
               "factor_vol": {f: math.sqrt(max(model["F"][k, k], 0) * ann) for k, f in enumerate(model["factors"])},
               "names": model["factors"], "n": len(model["syms"])}
        attr = analytics.attribution(res, model, rets, "W-SUN" if crypto else "W-FRI")
        attr["sectors"] = {k: float(v) for k, v in pd.Series(attr["names"]).groupby(sector_fn).sum().sort_values(ascending=False).items()} \
            if attr["names"] and not crypto else {}
    else:
        attr = None
    shocks = []
    if mdl and mdl["total"]:
        for f in model["styles"]:
            x = mdl["total"]["exposure"].get(f, 0.0)
            k = model["factors"].index(f)
            move = -math.copysign(3 * math.sqrt(max(model["F"][k, k], 0) * 21), x or 1)
            shocks.append({"label": f"{f.replace('_', ' ')} factor 3σ month against the book", "ret": x * move, "pnl": x * move * nav})
    stress = {"history": analytics.stress(w[w != 0], prices, bench, nav, scenarios, risk.get("betas", {})), "factor": shocks}
    liq = analytics.liquidity(book, adv)
    risk["weights"] = {s: float(v) for s, v in w[w != 0].items()}
    preview = preview_block(kind, sc, strat, m, tgt, pos, nav, prices, alpha.iloc[-1], strat.cost_bps + strat.slippage_bps, sector_fn)
    lim = limit_rows(kind, sc.get("limits") if crypto else lc.get("limits"), risk, mdl, liq, preview, st, strat, sc, nav, bench_label)
    tca = analytics.tca(blotter, raw, ysym, crypto, strat.cost_bps + strat.slippage_bps)
    identity = None
    if hasattr(broker, "account"):
        a = broker.account()
        identity = (a["equity"], a["cash"], sum(p.get("mv") or 0 for p in positions_all.values()))
    fills_book = average_costs(broker.fills("2015-01-01T00:00:00Z")) if hasattr(broker, "fills") else {}
    health = analytics.data_health(prices[universe], quotes, _expected_close(crypto, now), crypto, pos, fills_book, identity,
                                   blotter, {"last_run": last_run}, now)
    ctl = controls_block(lc, kind, sc, state_dir)
    live_alerts = [f"limit breach: {r['name']}" for r in lim if r["light"] == "red"] + \
                  [f"data: {h['check']} ({h['detail']})" for h in health if h["status"] == "fail"]
    return {"model": mdl, "attribution": attr, "stress": stress, "liquidity": liq, "limits": lim, "preview": preview,
            "tca": tca["summary"], "tca_rows": tca["rows"], "health": health, "controls": ctl, "alerts_now": live_alerts}


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
    old = backtest.run_backtest(prices, Config(**{k: v for k, v in lc["strategy"].items() if k not in (
        "factor_weights", "max_sector", "max_beta", "turnover_penalty")}), None, rf)  # the 4-factor blend it replaced
    research = growth_block(res, {"SPY": res.benchmark, f"Equal weight {len(universe)}": ew.returns,
                                  "Old 4-factor blend": old.returns}, 252)

    scores = signals.factor_scores(prices)
    alpha = signals.alpha_panel(prices, strat)
    from .live import current_weights
    held = {s: p for s, p in nv["positions"].items() if p["cls"] == "us_equity"}
    tgt = backtest.targets_at(alpha, rets, len(prices) - 1, strat, current_weights(held, nv["equity"], prices.iloc[-1]))
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

    # Factor risk model on the S&P 100 (strategy names + watchlist) with a year of daily returns.
    from .live import sleeve_configs
    msyms = [s for s in dict.fromkeys(universe + list(lc.get("watchlist", []))) if s in raw["Close"] and s != "SPY"]
    mp = raw["Close"][msyms].ffill().iloc[-520:]
    mp = mp.loc[:, mp.iloc[-253:].notna().all()]
    model = analytics.risk_model(mp.pct_change(), signals.factor_scores(mp), {s: sector(s) for s in mp.columns})
    bench_w = pd.Series(1 / len(universe), index=universe)
    target = _last_target(m, alpha, rets, prices, strat)
    sc_eq = sleeve_configs(lc)["equity"]
    desk = desk_block("equity", lc=lc, sc=sc_eq, strat=strat, m=m, raw=raw, prices=prices, bench=bench, bench_label="S&P 500",
                      universe=universe, ysym=lambda s: s, model=model, w=w, bench_w=bench_w, res=res, book=book, risk=risk,
                      nav=nav, st=_status(lc, lc, m, nav, ""), tgt=tgt, alpha=alpha, rets=rets, pos=pos,
                      positions_all=nv["positions"], broker=broker, blotter=blotter, quotes={s: quote(raw, s) for s in shown},
                      px_all=prices.iloc[-1], scenarios=analytics.EQUITY_SCENARIOS, sector_fn=sector,
                      now=pd.Timestamp.now(tz="UTC"), state_dir=state_dir, last_run=meta.get("last_run"))
    desk["exposure"] = exposure_rows(universe, book, target, bench_w.to_dict(), sector)
    desk["bench_label"] = f"equal weight {len(universe)}"
    sig_panels = {**scores, "alpha": alpha}
    month_rows = [r for r in prices.index.searchsorted(prices.resample("ME").last().index, side="right") - 1 if r > 252][-13:]
    trade_days = res.turnover[res.turnover > 0].index[-24:]
    adv = _adv_usd(raw, universe, lambda s: s, False)
    desk["signals"] = {
        "ic": analytics.signal_ic(sig_panels, prices), "horizons": [1, 5, 21, 63],
        "corr": analytics.signal_corr(sig_panels, prices), "crowding": analytics.crowding(sig_panels, rets),
        "capacity": analytics.capacity({**{k: analytics.standalone_weights(z, month_rows) for k, z in sig_panels.items()},
                                        "strategy": res.weights.loc[trade_days]}, adv)}

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
        "risk": risk, "desk": desk,
        "tracking": tracking_block(state_dir, "equity", prices, strat, bench, rf, 252),
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

    # One-factor model (crypto market + coin-specific); benchmark is buying and holding bitcoin.
    from .live import sleeve_configs
    model = analytics.risk_model(rets[universe], None, None, window=365)
    bench_w = pd.Series({s: float(s == btc.name) for s in universe})
    sc = sleeve_configs({**lc, "crypto": {**cc, "enabled": True}})["crypto"]
    desk = desk_block("crypto", lc=lc, sc=sc, strat=strat, m=m, raw=craw, prices=cprices, bench=btc, bench_label="Bitcoin",
                      universe=universe, ysym=yahoo, model=model, w=w, bench_w=bench_w, res=res, book=book, risk=risk,
                      nav=nav, st=_status(lc, cc, m, nav, ""), tgt=tgt, alpha=trend, rets=rets, pos=pos,
                      positions_all=nv["positions"], broker=broker, blotter=blotter, quotes=quotes,
                      px_all=cprices.iloc[-1], scenarios=analytics.CRYPTO_SCENARIOS, sector_fn=lambda s: "Crypto",
                      now=pd.Timestamp.now(tz="UTC"), state_dir=state_dir, last_run=meta.get("last_run"))
    desk["exposure"] = exposure_rows(universe, book, _last_target(m, trend, rets, cprices, strat), bench_w.to_dict(),
                                     lambda s: "Crypto")
    desk["bench_label"] = "bitcoin buy & hold"
    trade_days = res.turnover[res.turnover > 0].index[-24:]
    desk["signals"] = {
        "ic": analytics.signal_ic({"trend": trend}, cprices, horizons=(1, 7, 30, 90), pooled=True), "horizons": [1, 7, 30, 90],
        "capacity": analytics.capacity({"strategy": res.weights.loc[trade_days]}, _adv_usd(craw, universe, yahoo, True))}
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
        "risk": risk, "desk": desk,
        "tracking": tracking_block(state_dir, "crypto", cprices, strat, btc, None, 365, m.get("start")) if m.get("start") else None,
    }
