import json
import os

import numpy as np
import pandas as pd
import pytest

from alphaforge import portfolio
from alphaforge.backtest import Config, run_backtest
from alphaforge.broker import AlpacaBroker, SimBroker
from alphaforge.data import synthetic_prices
from alphaforge.live import DEFAULTS, is_signal_day, plan_orders, run


@pytest.fixture
def lc():
    return {**DEFAULTS, "strategy": {"mode": "long_only"}, "max_data_age_days": 10_000}


def test_signal_day_calendar():
    assert is_signal_day(pd.Timestamp("2026-09-30"), "2026-08-31")      # month end
    assert not is_signal_day(pd.Timestamp("2026-09-29"), "2026-08-31")  # mid-month
    assert not is_signal_day(pd.Timestamp("2026-09-30"), "2026-09-30")  # already done
    assert is_signal_day(pd.Timestamp("2026-10-01"), "2026-08-31")      # missed month: catch up
    assert is_signal_day(pd.Timestamp("2026-10-01"), None)              # first run


def test_plan_orders_limits_and_flip_split(lc):
    prices = pd.Series({"A": 100.0, "B": 50.0, "C": 10.0})
    pos = {"A": {"qty": 10, "avg_cost": 90}, "C": {"qty": 100, "avg_cost": 10}}
    lc = {**lc, "max_order_notional": 3_000}
    orders = plan_orders({"A": -0.2, "B": 0.5}, pos, 10_000, prices, lc)
    assert ("A", -10) in orders and ("A", -20) in orders   # flip split into close + open
    assert ("C", -100) in orders                           # unwanted name fully closed
    assert ("B", 60) in orders                             # 100 shares wanted, capped at $3k
    assert orders[-1][1] > 0                               # buys after sells


def test_sim_broker_cash_accounting(tmp_path):
    b = SimBroker(str(tmp_path / "a.json"), 10_000, slippage_bps=10, commission_bps=0)
    b.submit("X", 10, 100.0)
    assert b.cash == pytest.approx(10_000 - 10 * 100.1)
    assert b.equity({"X": 100.0}) == pytest.approx(10_000 - 1.0)
    b.submit("X", -10, 100.0)
    assert b.positions() == {}
    b.save()
    assert SimBroker(str(tmp_path / "a.json")).cash == pytest.approx(b.cash)


def test_run_lag_then_fill(tmp_path, lc):
    """Signal day queues orders; the next day's run fills them at that day's close."""
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    state = str(tmp_path)
    r1 = run(lc, prices.iloc[:-1], state)
    assert r1["fills"] == [] and "generated month-end signal" in r1["events"]
    r2 = run(lc, prices, state)
    assert r2["fills"] and all(f["status"] == "filled" for f in r2["fills"])
    acct = json.load(open(os.path.join(state, "account.json")))
    assert acct["positions"] and acct["cash"] < lc["capital"]
    assert len(pd.read_csv(os.path.join(state, "equity.csv"))) == 2


def test_drawdown_halt_flattens(tmp_path, lc):
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    state = str(tmp_path)
    run(lc, prices.iloc[:-1], state)
    run(lc, prices, state)
    crash = prices.copy()
    crash.loc[crash.index[-1] + pd.offsets.BDay()] = prices.iloc[-1] * 0.5
    r = run({**lc, "max_drawdown_halt": 0.1}, crash, state)
    assert r["halted"] and os.path.exists(os.path.join(state, "KILL"))
    assert json.load(open(os.path.join(state, "account.json")))["positions"] == {}


def test_stale_data_refuses(tmp_path, lc):
    prices, _ = synthetic_prices(n_assets=12, n_days=400)
    with pytest.raises(RuntimeError, match="older than"):
        run({**lc, "max_data_age_days": 4}, prices, str(tmp_path), today="2030-01-01")


class FakeAlpaca(AlpacaBroker):
    """AlpacaBroker with canned REST responses; records every call."""

    def __init__(self):
        super().__init__("k", "s")
        self.calls = []

    def _req(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/v2/account":
            return {"equity": "101000", "cash": "40000", "buying_power": "80000", "last_equity": "100000"}
        if path == "/v2/positions":
            return [{"symbol": "AAPL", "qty": "10", "avg_entry_price": "200", "current_price": "210"}]
        if path.startswith("/v2/orders?"):
            return [{"symbol": "AAPL", "side": "sell", "qty": "5", "filled_qty": "5", "filled_avg_price": "211.5",
                     "status": "filled", "filled_at": "2026-10-05T13:30:02Z", "submitted_at": "2026-10-04T21:16:00Z"}]
        if path.startswith("/v2/account/portfolio/history"):
            return {"timestamp": [1790899200, 1790985600], "equity": [0, 101000]}
        if method == "POST":
            return {"id": "x", "status": "accepted"}
        return None


def test_alpaca_paper_is_default_endpoint():
    assert FakeAlpaca().base == AlpacaBroker.PAPER


def test_alpaca_normalization():
    b = FakeAlpaca()
    assert b.account() == {"equity": 101000.0, "cash": 40000.0, "buying_power": 80000.0, "day_pl": 1000.0}
    assert b.positions()["AAPL"] == {"qty": 10.0, "avg_cost": 200.0, "last": 210.0}
    o = b.orders()[0]
    assert (o["qty"], o["filled"], o["price"], o["date"]) == (-5.0, -5.0, 211.5, "2026-10-05 13:30")
    assert b.history() == [("2026-10-03", 101000)]  # unfunded day dropped


def test_queued_broker_cancels_before_rebalance(tmp_path, lc):
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    b = FakeAlpaca()
    r = run(lc, prices, str(tmp_path), broker=b)
    methods = [(m, p.split("?")[0]) for m, p, _ in b.calls]
    first_post = methods.index(("POST", "/v2/orders"))
    assert ("DELETE", "/v2/orders") in methods[:first_post]
    assert r["fills"] and all(f["status"] == "accepted" for f in r["fills"])


def test_pick_swaps_pairs_worst_with_best():
    alpha = pd.Series({"A": -1.0, "B": 0.5, "C": 2.0, "D": 1.5, "E": 0.1, "F": -0.5})
    held = {"A": -0.10, "B": -0.05, "E": 0.20, "F": 0.01}
    assert portfolio.pick_swaps(held, alpha, 2) == (["A", "B"], ["C", "D"])
    # A replacement must outscore the holding it replaces.
    assert portfolio.pick_swaps({"C": -0.3}, alpha, 2) == ([], [])


def test_backtest_swaps_trade_and_stay_causal():
    prices, _ = synthetic_prices(n_assets=20, n_days=900, seed=1)
    cfg = Config(mode="long_only", swap_every=10, swap_count=2)
    base = run_backtest(prices, Config(mode="long_only"))
    swp = run_backtest(prices, cfg)
    assert (swp.turnover > 0).sum() > (base.turnover > 0).sum()  # extra trade days from swaps
    cut = 650
    shocked = prices.copy()
    shocked.iloc[cut + 1:] *= np.random.default_rng(0).uniform(0.5, 1.5, shocked.iloc[cut + 1:].shape)
    pd.testing.assert_series_equal(swp.returns.iloc[: cut + 1], run_backtest(shocked, cfg).returns.iloc[: cut + 1])


def test_live_swap_after_ten_days(tmp_path, lc):
    """Month-start signal, fill next day, swap check 10 trading days later, swap fills the day after."""
    prices, _ = synthetic_prices(n_assets=20, n_days=460, seed=1)
    start = prices.index.get_loc(pd.Timestamp("2016-07-01"))
    cfg = {**lc, "strategy": {"mode": "long_only", "swap_every": 10, "swap_count": 2}}
    events = []
    for i in range(start, start + 13):
        events += run(cfg, prices.iloc[: i + 1], str(tmp_path))["events"]
    check = next(e for e in events if e.startswith("swap check"))
    assert check == "swap check: drop ['SYN12', 'SYN18'], add ['SYN09', 'SYN04']"
    assert "executed 2016-07-15 swap" in events
    held = json.load(open(os.path.join(str(tmp_path), "account.json")))["positions"]
    assert {"SYN09", "SYN04"} <= set(held) and not {"SYN12", "SYN18"} & set(held)
