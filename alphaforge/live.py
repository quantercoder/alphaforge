"""Daily trading job. Run once after the US close:  python -m alphaforge.live

download -> freshness check -> mark to market -> kill switch / drawdown halt
-> execute yesterday's pending orders (sim) -> month-end signal -> save state -> terminal data

Signal generation calls the same `backtest.targets_at` the backtest uses, so live and
research positions come from one code path.
"""
import argparse
import json
import math
import os

import numpy as np
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar

from . import backtest, signals
from .backtest import Config
from .broker import AlpacaBroker, SimBroker
from .data import DEFAULT_UNIVERSE, MARKET_STRIP, SP100, download, load_prices

DEFAULTS = {
    "broker": "sim",              # sim | alpaca
    "live_money": False,          # alpaca only: true routes orders to the REAL-MONEY endpoint
    "capital": 100_000,           # sim starting cash
    "universe": DEFAULT_UNIVERSE,  # what the strategy trades
    "watchlist": SP100,            # extra names the terminal shows (watch-only)
    "history_start": "2014-01-01",
    "strategy": {"mode": "long_only"},  # any backtest.Config field
    "min_trade_notional": 200,    # skip dust trades (full closes always go through)
    "max_order_notional": 25_000, # fat-finger limit per order
    "max_drawdown_halt": 0.20,    # flatten and halt when equity falls this far below its peak
    "max_data_age_days": 4,       # refuse to trade on stale prices
}
_CBD = pd.offsets.CustomBusinessDay(calendar=USFederalHolidayCalendar())


def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


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


def is_signal_day(date, last_signal):
    """Last trading day of the month (US federal calendar approximation of NYSE), with catch-up.

    If a month-end was missed (holiday mismatch, failed run) the next run signals immediately.
    """
    if last_signal is None:
        return True
    period, last = pd.Period(date, "M"), pd.Period(last_signal, "M")
    month_end = (date + _CBD).month != date.month
    return (month_end and last != period) or (period - last).n >= 2


def plan_orders(weights, positions, equity, prices, lc):
    """Signed whole-share orders that move the book to `weights` x equity.

    Sells come first so their cash funds the buys. Orders crossing zero are split into a
    close and an open because brokers reject a single order that flips a position.
    """
    orders = []
    syms = set(k for k, v in weights.items() if v) | set(positions)
    for s in sorted(syms):
        px = prices.get(s)
        if px is None or not np.isfinite(px) or px <= 0:
            continue
        cur = positions.get(s, {}).get("qty", 0.0)
        tgt = math.trunc(weights.get(s, 0.0) * equity / px)
        delta = tgt - cur
        if tgt != 0 and abs(delta * px) < lc["min_trade_notional"]:
            continue
        cap = math.floor(lc["max_order_notional"] / px)
        if abs(delta) > cap:
            delta = math.copysign(cap, delta)
        if delta == 0:
            continue
        new = cur + delta
        if cur and new and (cur > 0) != (new > 0):
            orders += [(s, -cur), (s, new)]
        else:
            orders.append((s, delta))
    return sorted(orders, key=lambda o: o[1] * prices[o[0]])


def execute(broker, weights, prices, lc):
    eq = broker.equity(prices)
    orders = plan_orders(weights, broker.positions(), eq, prices, lc)
    return [f for s, q in orders if (f := broker.submit(s, q, prices[s]))]


def run(lc, prices, state_dir="state", broker=None, today=None):
    """One trading day. Returns a report dict; persists account, equity curve, orders and meta."""
    os.makedirs(state_dir, exist_ok=True)
    strat = Config(**lc["strategy"])
    broker = broker or make_broker(lc, state_dir)
    meta_path = f"{state_dir}/meta.json"
    meta = {"last_signal": None, "pending": None, "high_water": None}
    if os.path.exists(meta_path):
        with open(meta_path) as f:
            meta.update(json.load(f))

    date = prices.index[-1]
    today = pd.Timestamp(today or pd.Timestamp.now().normalize())
    if (today - date).days > lc["max_data_age_days"]:
        raise RuntimeError(f"Latest price is {date.date()}, older than {lc['max_data_age_days']} days")
    px = prices.iloc[-1].dropna()
    d = str(date.date())
    fills, events = [], []

    equity = broker.equity(px)
    meta["high_water"] = max(meta["high_water"] or equity, equity)
    kill_file = f"{state_dir}/KILL"
    if equity / meta["high_water"] - 1 < -lc["max_drawdown_halt"] and not os.path.exists(kill_file):
        with open(kill_file, "w") as f:
            f.write(f"{d}: drawdown {equity / meta['high_water'] - 1:.2%} breached "
                    f"{-lc['max_drawdown_halt']:.0%}. Delete this file to resume.\n")
        events.append("drawdown halt triggered")
    halted = os.path.exists(kill_file) or os.environ.get("ALPHAFORGE_KILL") == "1"

    if halted:
        if broker.positions():
            fills += broker.flatten(px)
            events.append("flattened book")
        meta["pending"] = None
    else:
        p = meta["pending"]
        if p and not broker.queues_orders and d > p["signal_date"]:
            fills += execute(broker, p["weights"], px, lc)
            events.append(f"executed {p['signal_date']} rebalance")
            meta["pending"] = None
        if is_signal_day(date, meta["last_signal"]):
            alpha = signals.combine(signals.factor_scores(prices), strat.factor_weights)
            w = backtest.targets_at(alpha, prices.pct_change(), len(prices) - 1, strat)
            w = {k: round(float(v), 6) for k, v in w.items() if v and np.isfinite(v)}
            meta["last_signal"] = d
            events.append("generated month-end signal")
            if broker.queues_orders:
                broker.cancel_open()  # a rerun must not stack a second set of orders
                fills += execute(broker, w, px, lc)  # broker fills at the next open
            else:
                meta["pending"] = {"signal_date": d, "weights": w}  # fill at next close

    equity = broker.equity(px)
    meta["high_water"] = max(meta["high_water"], equity)
    broker.save()

    eq_path = f"{state_dir}/equity.csv"
    curve = pd.read_csv(eq_path, index_col=0) if os.path.exists(eq_path) else pd.DataFrame(columns=["equity"])
    curve.loc[d, "equity"] = round(equity, 2)
    curve.sort_index().to_csv(eq_path, index_label="date")
    with open(f"{state_dir}/orders.jsonl", "a") as f:
        for fl in fills:
            f.write(json.dumps({"date": d, **fl}) + "\n")
    meta["halted"] = halted
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=1)
    return {"date": d, "equity": equity, "fills": fills, "events": events, "halted": halted}


def main():
    ap = argparse.ArgumentParser(description="AlphaForge daily trading job")
    ap.add_argument("--config", default="live.json")
    ap.add_argument("--state", default="state")
    ap.add_argument("--site", default="site/data.json")
    ap.add_argument("--quotes-only", action="store_true", help="refresh terminal data without trading")
    a = ap.parse_args()

    lc = load_config(a.config)
    core = lc["universe"] + ["SPY"] + list(MARKET_STRIP.values())
    raw = download(core, lc["history_start"])
    extra = [s for s in lc["watchlist"] if s not in core]
    if extra:  # watch-only names need ~1 year for charts and 52-week ranges, not the full backtest history
        start = (pd.Timestamp.now() - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
        raw = pd.concat([raw, download(extra, start)], axis=1)
    prices, bench = load_prices(lc["universe"], None, raw=raw)
    broker = make_broker(lc, a.state)
    if not a.quotes_only:
        report = run(lc, prices, a.state, broker)
        print(json.dumps({k: v for k, v in report.items() if k != "fills"}, default=str))
        for fl in report["fills"]:
            print("  ", fl)

    from . import terminal
    terminal.build(raw, prices, bench, lc, broker, a.state, a.site)
    print(f"terminal data -> {a.site}")


if __name__ == "__main__":
    main()
