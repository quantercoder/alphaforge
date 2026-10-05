"""Daily trading job. Run once after the US close:  python -m alphaforge.live

The account is split into two sleeves that never touch each other's positions:

    equity  the multi-factor stock strategy (month-end rebalance + two-week swap)
    crypto  a trend-following crypto strategy with a fixed budget (weekly rebalance)

Each sleeve has its own NAV, high-water mark, drawdown halt and kill switch. Crypto NAV is
budget + its own P&L, reconciled from the broker's fills; equity NAV is the rest of the account.

Per sleeve: freshness check -> drawdown halt -> pending orders (sim) -> signal / swap -> orders.
Signals call the same `backtest.targets_at` the backtest uses.
"""
import argparse
import json
import math
import os

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from . import backtest, portfolio, signals
from .backtest import Config
from .broker import AlpacaBroker, SimBroker
from .data import DEFAULT_UNIVERSE, MARKET_STRIP, SP100, download, load_prices, risk_free
from .refdata import sector, yahoo

DEFAULTS = {
    "broker": "sim",              # sim | alpaca
    "live_money": False,          # alpaca only: true routes orders to the REAL-MONEY endpoint
    "capital": 100_000,           # sim starting cash
    "universe": DEFAULT_UNIVERSE,  # what the equity strategy trades
    "watchlist": SP100,            # extra names the terminal shows (watch-only)
    "history_start": "2014-01-01",
    "strategy": {"mode": "long_only"},  # any backtest.Config field
    "min_trade_notional": 200,    # skip dust trades (full closes always go through)
    "max_order_notional": 25_000, # fat-finger limit per order
    "max_drawdown_halt": 0.20,    # flatten the sleeve and halt when NAV falls this far below its peak
    "max_data_age_days": 4,       # refuse to trade on stale prices
    "require_approval": False,    # true: a rebalance or swap waits until a run with ALPHAFORGE_APPROVE=equity|all
    "limits": {},                 # monitoring limits shown on the terminal (see terminal.LIMITS)
}
CRYPTO_DEFAULTS = {
    "enabled": False,
    "budget": 10_000,             # capital the crypto sleeve starts with (its NAV then moves with its P&L)
    "universe": ["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD", "LINK/USD", "AVAX/USD", "DOGE/USD", "BCH/USD"],
    "history_start": "2019-01-01",
    "strategy": {"model": "trend", "mode": "trend", "target_vol": 0.25, "max_weight": 0.35,
                 "max_leverage": 1.0, "cost_bps": 25, "slippage_bps": 10, "cov_lookback": 60,
                 "warmup": 120, "rebalance": "W-FRI", "ann": 365},
    "rebalance_days": 7,
    "min_trade_notional": 25,
    "max_order_notional": 5_000,
    "cash_buffer": 0.02,          # crypto buys need settled cash; keep 2% for fees and price moves
    "max_drawdown_halt": 0.50,    # backtest max drawdown is ~48%; a tighter halt would stop it in normal swings
    "max_data_age_days": 3,
    "require_approval": False,
}
_CBD = pd.offsets.CustomBusinessDay(calendar=USFederalHolidayCalendar())


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    c = {**CRYPTO_DEFAULTS, **cfg.get("crypto", {})}
    c["strategy"] = {**CRYPTO_DEFAULTS["strategy"], **cfg.get("crypto", {}).get("strategy", {})}
    cfg["crypto"] = c
    return cfg


def sleeve_configs(lc):
    """name -> sleeve config. The equity sleeve uses the top-level keys for backward compatibility."""
    out = {"equity": {**lc, "cls": "us_equity", "fractional": False}}
    if lc["crypto"]["enabled"]:
        out["crypto"] = {**lc["crypto"], "cls": "crypto", "fractional": True}
    return out


def make_broker(lc, state_dir):
    strat = Config(**lc["strategy"])
    if lc["broker"] == "sim":
        return SimBroker(f"{state_dir}/account.json", lc["capital"],
                         strat.slippage_bps, strat.cost_bps)
    if lc["broker"] == "alpaca":
        live = bool(lc["live_money"]) and os.environ.get("ALPHAFORGE_CONFIRM_LIVE") == "yes"
        if lc["live_money"] and not live:
            raise RuntimeError("live_money is true but ALPHAFORGE_CONFIRM_LIVE != 'yes'; refusing to trade")
        return AlpacaBroker(os.environ.get("ALPACA_KEY_ID"), os.environ.get("ALPACA_SECRET_KEY"), live)
    raise ValueError(f"Unknown broker {lc['broker']}")


# ---------------------------------------------------------------- calendar

def is_signal_day(date, last_signal):
    """Last trading day of the month (US federal calendar approximation of NYSE), with catch-up.

    If a month-end was missed (holiday mismatch, failed run) the next run signals immediately.
    """
    if last_signal is None:
        return True
    period, last = pd.Period(date, "M"), pd.Period(last_signal, "M")
    month_end = (date + _CBD).month != date.month
    return (month_end and last != period) or (period - last).n >= 2


def signal_due(name, sc, date, m):
    if name == "crypto":
        return m.get("last_signal") is None or (date - pd.Timestamp(m["last_signal"])).days >= sc["rebalance_days"]
    return is_signal_day(date, m.get("last_signal"))


def swap_due(index, meta, strat):
    """True when `swap_every` trading days have passed since the last rebalance or swap."""
    if not strat.swap_every or not meta.get("last_signal"):
        return False
    last = max(d for d in (meta.get("last_signal"), meta.get("last_swap")) if d)
    return int((index > pd.Timestamp(last)).sum()) >= strat.swap_every


# ---------------------------------------------------------------- sizing

def _units(x, fractional):
    """Round a share count toward zero: whole shares, or 6 decimals for crypto."""
    return math.trunc(x * 1e6) / 1e6 if fractional else math.trunc(x)


def plan_orders(weights, positions, nav, prices, sc):
    """Signed orders that move one sleeve's positions to `weights` x sleeve NAV.

    Sells come first so their cash funds the buys. Orders crossing zero are split into a
    close and an open because brokers reject a single order that flips a position.
    """
    frac = sc.get("fractional", False)
    nav = nav * (1 - sc.get("cash_buffer", 0.0))  # headroom for fees so the last buy isn't rejected
    orders = []
    syms = set(k for k, v in weights.items() if v) | set(positions)
    for s in sorted(syms):
        px = prices.get(s)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        cur = positions.get(s, {}).get("qty", 0.0)
        tgt = _units(weights.get(s, 0.0) * nav / px, frac)
        delta = tgt - cur
        if tgt != 0 and abs(delta * px) < sc["min_trade_notional"]:
            continue
        cap = _units(sc["max_order_notional"] / px, frac)
        if abs(delta) > cap:
            delta = math.copysign(cap, delta)
        if abs(delta) < 1e-9:
            continue
        new = cur + delta
        if cur and new and (cur > 0) != (new > 0):
            orders += [(s, -cur), (s, new)]
        else:
            orders.append((s, delta))
    return sorted(orders, key=lambda o: o[1] * prices[o[0]])


def submit_all(broker, orders, prices, prefix):
    """Submit with deterministic client ids (prefix-symbol-n): a retried run gets 'duplicate'."""
    out, seen = [], {}
    for s, q in orders:
        n = seen[s] = seen.get(s, -1) + 1
        f = broker.submit(s, q, float(prices[s]), client_id=f"{prefix}-{s.replace('/', '')}-{n}")
        if f:
            out.append(f)
    return out


def swap_orders(drop, add, positions, prices, sc):
    """Sell `drop` entirely; the proceeds are split evenly across `add`. Sells go first."""
    orders = [(s, -positions[s]["qty"]) for s in drop if s in positions and s in prices]
    freed = sum(-q * float(prices[s]) for s, q in orders)
    for s in add:
        px = float(prices[s])
        q = _units(min(freed / len(add), sc["max_order_notional"]) / px, sc.get("fractional", False))
        if q > 0 and q * px >= sc["min_trade_notional"]:
            orders.append((s, q))
    return orders


def current_weights(positions, nav, px):
    """Today's weight of each held name in the sleeve (for the optimizer's turnover penalty)."""
    return pd.Series({s: p["qty"] * float(px[s]) / nav for s, p in positions.items() if s in px and nav}, dtype=float)


# ---------------------------------------------------------------- sleeve NAVs

def _mark(p, s, px):
    last = p.get("last") or (float(px[s]) if s in px else None)
    return p["qty"] * last if last else 0.0


def navs(broker, lc, meta, px_all, start=False):
    """Account equity and each sleeve's NAV.

    crypto NAV = crypto market value + crypto cash, where
    crypto cash = budget - market value when the sleeve started - net cash spent on crypto fills since.
    equity NAV = account equity - crypto NAV (or minus crypto market value when the crypto sleeve
    is off, so coins held by hand never inflate stock sizing).
    """
    pos = broker.positions()
    account = broker.equity(px_all)
    c_pos = {s: p for s, p in pos.items() if p["cls"] == "crypto"}
    c_mv = sum(_mark(p, s, px_all) for s, p in c_pos.items())
    out = {"account": account, "positions": pos, "crypto_mv": c_mv}
    cc = lc["crypto"]
    if cc["enabled"]:
        m = meta.setdefault("crypto", {})
        if start and "start" not in m:
            m["start"], m["mv_at_start"] = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"), c_mv
        if "start" in m:
            flows = sum(f["qty"] * f["price"] for f in broker.fills(m["start"]) if f["cls"] == "crypto")
            cash = cc["budget"] - m["mv_at_start"] - flows
        else:
            cash = cc["budget"] - c_mv  # not started yet: the budget is what it will trade with
        out["crypto"], out["crypto_cash"] = c_mv + cash, cash
        out["equity"] = account - out["crypto"]
    else:
        out["equity"] = account - c_mv
    return out


# ---------------------------------------------------------------- one sleeve, one day

def step_sleeve(name, sc, prices, broker, m, nav, positions, d, state_dir):
    """Run one sleeve for the day. Returns (fills, events, alerts)."""
    strat = Config(**sc["strategy"])
    px = prices.iloc[-1].dropna()
    date = prices.index[-1]
    rets = prices.pct_change()
    fills, events, alerts = [], [], []
    prefix = f"af-{name[:3]}-{d}"

    m["high_water"] = max(m.get("high_water") or nav, nav)
    dd = nav / m["high_water"] - 1 if m["high_water"] > 0 else 0.0
    kill_file = f"{state_dir}/KILL" if name == "equity" else f"{state_dir}/KILL_{name.upper()}"
    if dd < -sc["max_drawdown_halt"] and not os.path.exists(kill_file):
        with open(kill_file, "w") as f:
            f.write(f"{d}: {name} sleeve drawdown {dd:.2%} breached {-sc['max_drawdown_halt']:.0%}. "
                    "Delete this file to resume.\n")
        events.append("drawdown halt triggered")
        alerts.append(f"{name}: drawdown halt at {dd:.2%}")
    halted = os.path.exists(kill_file) or os.environ.get("ALPHAFORGE_KILL") in ("1", name)

    if halted:
        orders = [(s, -p["qty"]) for s, p in positions.items() if s in px]
        if orders:
            fills += submit_all(broker, orders, px, f"{prefix}-kl")
            events.append("flattened book")
        m["pending"] = None
    else:
        p = m.get("pending")
        if p and not broker.queues_orders and d > p["signal_date"]:
            if "drop" in p:
                fills += submit_all(broker, swap_orders(p["drop"], p["add"], positions, px, sc), px, f"{prefix}-sw")
                events.append(f"executed {p['signal_date']} swap")
            else:
                fills += submit_all(broker, plan_orders(p["weights"], positions, nav, px, sc), px, f"{prefix}-rb")
                events.append(f"executed {p['signal_date']} rebalance")
            m["pending"] = None
            positions = {s: q for s, q in broker.positions().items() if q["cls"] == sc["cls"]}
        waiting = m.get("awaiting") or {}
        approved = os.environ.get("ALPHAFORGE_APPROVE") in (name, "all")
        reb, swp = signal_due(name, sc, date, m) or waiting.get("kind") == "rebalance", False
        if not reb:
            swp = swap_due(prices.index, m, strat)
        if (reb or swp) and sc.get("require_approval") and not approved:
            kind = "rebalance" if reb else "swap"
            if waiting.get("kind") != kind:
                alerts.append(f"{name}: {kind} is waiting for approval (Actions > terminal > Run workflow > approve)")
            m["awaiting"] = {"kind": kind, "since": waiting.get("since", d) if waiting.get("kind") == kind else d}
            events.append(f"{kind} waiting for approval")
            reb = swp = False
        elif reb or swp:
            if sc.get("require_approval"):
                events.append(f"{'rebalance' if reb else 'swap'} approved by {os.environ.get('GITHUB_ACTOR', 'operator')}")
            m["awaiting"] = None
        if reb:
            alpha = signals.alpha_panel(prices, strat)
            w = backtest.targets_at(alpha, rets, len(prices) - 1, strat, current_weights(positions, nav, px))
            w = {k: round(float(v), 6) for k, v in w.items() if v and np.isfinite(v)}
            m["last_signal"], m["target"] = d, w
            events.append("generated month-end signal" if name == "equity" else "generated weekly signal")
            if broker.queues_orders:
                broker.cancel_stale(sc["cls"], prefix)
                fills += submit_all(broker, plan_orders(w, positions, nav, px, sc), px, f"{prefix}-rb")
            else:
                m["pending"] = {"signal_date": d, "weights": w}  # fill at next close
        elif swp:
            m["last_swap"] = d
            held = {s: float(px[s]) / q["avg_cost"] - 1 for s, q in positions.items()
                    if q["qty"] > 0 and s in px and s in prices.columns and q["avg_cost"] > 0}
            alpha = signals.alpha_panel(prices, strat)
            drop, add = portfolio.pick_swaps(held, alpha.iloc[-1], strat.swap_count,
                                             current_weights(positions, nav, px).to_dict(), sector, strat.max_sector)
            events.append(f"swap check: drop {drop or 'none'}, add {add or 'none'}")
            if drop and m.get("target"):
                t = dict(m["target"])
                freed = sum(t.pop(s, 0.0) for s in drop)
                m["target"] = {**t, **{s: round(freed / len(add), 6) for s in add}}
            if drop and broker.queues_orders:
                broker.cancel_stale(sc["cls"], prefix)
                fills += submit_all(broker, swap_orders(drop, add, positions, px, sc), px, f"{prefix}-sw")
            elif drop:
                m["pending"] = {"signal_date": d, "drop": drop, "add": add}

    alerts += [f"{name}: {f['symbol']} {f['qty']:+g} {f['status']}: {f.get('error', '')}"
               for f in fills if f["status"] in ("error", "rejected")]
    m["halted"], m["drawdown"], m["nav"] = halted, dd, nav
    return fills, events, alerts


def reconcile(broker, meta, days=3):
    """Alert once on any of this job's recent orders the broker rejected, canceled or expired."""
    if not hasattr(broker, "orders"):
        return []
    seen = set(meta.setdefault("alerted", []))
    cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)).isoformat()
    out = []
    for o in broker.orders():
        if (o.get("client_id") or "").startswith("af-") and o["status"] in ("rejected", "canceled", "expired") \
                and (o["time"] or "") >= cutoff and o["id"] not in seen:
            out.append(f"broker {o['status']} {o['symbol']} {o['qty']:+g} ({o['client_id']})")
            seen.add(o["id"])
    meta["alerted"] = sorted(seen)[-300:]
    return out


# ---------------------------------------------------------------- the whole day

def snapshot_positions(path, d, nv, px_all):
    """One row per holding per trading day: what was held, at what price, and its weight in its sleeve.
    A rerun on the same day replaces that day's rows."""
    sleeve_nav = {"us_equity": nv["equity"], "crypto": nv.get("crypto") or nv["crypto_mv"]}
    rows = []
    for s, p in sorted(nv["positions"].items()):
        last = p.get("last") or (float(px_all[s]) if s in px_all else None)
        mv = p["qty"] * last if last else None
        nav = sleeve_nav.get(p["cls"])
        rows.append({"date": d, "symbol": s, "sleeve": "crypto" if p["cls"] == "crypto" else "equity", "qty": p["qty"],
                     "price": round(last, 6) if last else None, "value": round(mv, 2) if mv is not None else None,
                     "weight": round(mv / nav, 6) if mv is not None and nav else None})
    old = pd.read_csv(path) if os.path.exists(path) else pd.DataFrame(columns=list(rows[0]) if rows else ["date"])
    old = old[old["date"].astype(str) != d]
    pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(path, index=False)


def _load_meta(path):
    meta = {}
    if os.path.exists(path):
        with open(path) as f:
            meta = json.load(f)
    if "last_signal" in meta or "high_water" in meta:  # migrate the single-sleeve layout
        flat = {k: meta.pop(k) for k in list(meta) if k not in ("equity", "crypto", "alerted")}
        flat.pop("high_water", None)  # the old high-water mark was the whole account, not the sleeve
        meta["equity"] = {**flat, **meta.get("equity", {})}
    meta.setdefault("equity", {})
    return meta


def run(lc, prices, state_dir="state", broker=None, today=None, crypto_prices=None):
    """One trading day for every enabled sleeve. Persists account, equity curve, orders and meta."""
    os.makedirs(state_dir, exist_ok=True)
    broker = broker or make_broker(lc, state_dir)
    meta_path = f"{state_dir}/meta.json"
    meta = _load_meta(meta_path)
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    data = {"equity": prices}
    if lc["crypto"]["enabled"] and crypto_prices is not None:
        data["crypto"] = crypto_prices
    configs = sleeve_configs(lc)
    for name, p in data.items():
        if (today - p.index[-1]).days > configs[name]["max_data_age_days"]:
            raise RuntimeError(f"{name}: latest price is {p.index[-1].date()}, older than "
                               f"{configs[name]['max_data_age_days']} days")

    # rename(None): rows from different dates carry different names, which pandas 3 refuses to concat
    px_all = pd.concat([p.iloc[-1].dropna().rename(None) for p in data.values()])
    d = str(prices.index[-1].date())
    nv = navs(broker, lc, meta, px_all, start="crypto" in data)
    fills, events, alerts = [], [], []
    for name, p in data.items():
        sc = configs[name]
        pos = {s: q for s, q in nv["positions"].items() if q["cls"] == sc["cls"]}
        f, e, a = step_sleeve(name, sc, p, broker, meta.setdefault(name, {}), nv[name], pos,
                              str(p.index[-1].date()), state_dir)
        fills += [{**x, "sleeve": name} for x in f]
        events += [f"{name}: {x}" if name != "equity" else x for x in e]
        alerts += a
    broker.save()
    alerts += reconcile(broker, meta)

    after = navs(broker, lc, meta, px_all)
    eq_path = f"{state_dir}/equity.csv"
    curve = pd.read_csv(eq_path, index_col=0) if os.path.exists(eq_path) else pd.DataFrame(columns=["equity"])
    curve.loc[d, "equity"] = round(after["equity"], 2)  # the equity sleeve (column kept for history)
    curve.loc[d, "account"] = round(after["account"], 2)
    if "crypto" in after:
        curve.loc[d, "crypto"] = round(after["crypto"], 2)
    curve.sort_index().to_csv(eq_path, index_label="date")
    snapshot_positions(f"{state_dir}/positions.csv", d, after, px_all)
    with open(f"{state_dir}/orders.jsonl", "a") as f:
        for fl in fills:
            f.write(json.dumps({"date": d, **fl}, default=float) + "\n")
    now = pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds")
    meta["last_run"] = now
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)
    env = os.environ.get
    with open(f"{state_dir}/audit.jsonl", "a") as f:  # who ran what, from which commit
        f.write(json.dumps({"time": now, "date": d, "actor": env("GITHUB_ACTOR", "local"),
                            "trigger": env("GITHUB_EVENT_NAME", "manual"), "run": env("GITHUB_RUN_ID"),
                            "sha": (env("GITHUB_SHA") or "")[:7] or None, "approve": env("ALPHAFORGE_APPROVE") or None,
                            "events": events, "orders": len(fills), "alerts": alerts}) + "\n")
    if alerts:
        with open(f"{state_dir}/alerts.jsonl", "a") as f:
            for a in alerts:
                f.write(json.dumps({"time": now, "alert": a}) + "\n")
    return {"date": d, "equity": after["equity"], "account": after["account"], "navs":
            {k: after[k] for k in ("equity", "crypto") if k in after}, "fills": fills, "events": events,
            "halted": any(meta[k].get("halted") for k in data), "alerts": alerts}


def load_crypto(lc, today=None):
    """Daily crypto closes (Alpaca pair columns) and raw OHLCV, complete UTC days only."""
    cc = lc["crypto"]
    raw = download([yahoo(s) for s in cc["universe"]], cc["history_start"])
    today = pd.Timestamp(today or pd.Timestamp.now(tz="UTC").date())
    raw = raw[raw.index < today]  # today's bar is still forming
    close = raw["Close"].rename(columns={yahoo(s): s for s in cc["universe"]})
    return close[[s for s in cc["universe"] if s in close]].ffill(), raw


def main():
    ap = argparse.ArgumentParser(description="AlphaForge daily trading job")
    ap.add_argument("--config", default="live.json")
    ap.add_argument("--state", default="state")
    ap.add_argument("--site", default="site")
    ap.add_argument("--alerts", default="alerts.txt")
    ap.add_argument("--quotes-only", action="store_true", help="refresh terminal data without trading")
    a = ap.parse_args()

    lc = load_config(a.config)
    core = lc["universe"] + ["SPY", "^IRX"] + list(MARKET_STRIP.values())
    raw = download(core, lc["history_start"])
    extra = [s for s in lc["watchlist"] if s not in core]
    if extra:  # watch-only names don't need the full backtest history
        # ~800 days: a year of charts plus a year of factor history for the risk model
        start = (pd.Timestamp.now() - pd.Timedelta(days=800)).strftime("%Y-%m-%d")
        raw = pd.concat([raw, download(extra, start)], axis=1)
    prices, bench = load_prices(lc["universe"], None, raw=raw)
    cprices, craw = load_crypto(lc) if lc["crypto"]["enabled"] else (None, None)
    broker = make_broker(lc, a.state)

    alerts = []
    if not a.quotes_only:
        report = run(lc, prices, a.state, broker, crypto_prices=cprices)
        print(json.dumps({k: v for k, v in report.items() if k != "fills"}, default=str))
        for fl in report["fills"]:
            print("  ", fl)
        alerts = report["alerts"]

    from . import terminal
    terminal.build(raw, prices, bench, lc, broker, a.state, a.site, craw=craw, cprices=cprices)
    print(f"terminal data -> {a.site}")
    if alerts:
        with open(a.alerts, "a") as f:
            f.write("\n".join(alerts) + "\n")
        print("ALERTS:\n" + "\n".join(alerts))


if __name__ == "__main__":
    main()
