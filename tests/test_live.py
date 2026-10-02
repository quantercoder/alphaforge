import json
import os

import pandas as pd
import pytest

from alphaforge.broker import SimBroker
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
