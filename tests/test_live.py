import json
import os

import numpy as np
import pandas as pd
import pytest

from alphaforge import backtest, portfolio, signals
from alphaforge.backtest import Config, run_backtest
from alphaforge.broker import AlpacaBroker, SimBroker
from alphaforge.data import synthetic_prices
from alphaforge.live import CRYPTO_DEFAULTS, is_signal_day, load_config, plan_orders, run


@pytest.fixture
def lc():
    return {**load_config(None), "strategy": {"mode": "long_only"}, "max_data_age_days": 10_000}


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


def test_plan_orders_fractional_for_crypto(lc):
    sc = {**lc, "fractional": True, "min_trade_notional": 10, "max_order_notional": 1e9}
    orders = plan_orders({"BTC/USD": 0.5}, {}, 10_000, pd.Series({"BTC/USD": 61234.5}), sc)
    assert orders == [("BTC/USD", 0.081653)]


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
    assert any("drawdown halt" in a for a in r["alerts"])


def test_stale_data_refuses(tmp_path, lc):
    prices, _ = synthetic_prices(n_assets=12, n_days=400)
    with pytest.raises(RuntimeError, match="older than"):
        run({**lc, "max_data_age_days": 4}, prices, str(tmp_path), today="2030-01-01")


def test_old_meta_migrates_to_sleeves(tmp_path, lc):
    state = tmp_path
    (state / "meta.json").write_text(json.dumps({"last_signal": "2016-06-30", "pending": None,
                                                  "high_water": 150000.0, "halted": False}))
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    run(lc, prices, str(state))
    meta = json.loads((state / "meta.json").read_text())
    assert "last_signal" not in meta and meta["equity"]["last_signal"]
    assert meta["equity"]["high_water"] <= 100_000   # old whole-account mark is not carried over


# ---------------------------------------------------------------- Alpaca

class FakeAlpaca(AlpacaBroker):
    """AlpacaBroker with canned REST responses; records every call."""

    def __init__(self):
        super().__init__("k", "s")
        self.calls = []
        self.seen_ids = set()

    def _req(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/v2/account":
            return {"equity": "101000", "cash": "40000", "buying_power": "80000", "last_equity": "100000"}
        if path == "/v2/positions":
            return [{"symbol": "AAPL", "qty": "10", "avg_entry_price": "200", "current_price": "210",
                     "asset_class": "us_equity", "market_value": "2100", "cost_basis": "2000",
                     "unrealized_pl": "100", "unrealized_plpc": "0.05", "unrealized_intraday_pl": "20",
                     "change_today": "0.0096", "lastday_price": "208"},
                    {"symbol": "BTCUSD", "qty": "0.01", "avg_entry_price": "60000", "current_price": "62000",
                     "asset_class": "crypto"}]
        if path.startswith("/v2/orders?status=open"):
            return [{"id": "old", "client_order_id": "af-equ-2000-01-03-rb-AAPL-0", "symbol": "AAPL",
                     "asset_class": "us_equity"},
                    {"id": "manual", "client_order_id": "my-own-order", "symbol": "MSFT", "asset_class": "us_equity"},
                    {"id": "coin", "client_order_id": "af-cry-2000-01-03-rb-BTCUSD-0", "symbol": "BTC/USD",
                     "asset_class": "crypto"}]
        if path.startswith("/v2/orders?"):
            return [{"symbol": "AAPL", "side": "sell", "qty": "5", "filled_qty": "5", "filled_avg_price": "211.5",
                     "status": "filled", "filled_at": "2026-10-05T13:30:02Z", "submitted_at": "2026-10-04T21:16:00Z",
                     "asset_class": "us_equity", "client_order_id": "x", "id": "o1"}]
        if path.startswith("/v2/account/portfolio/history"):
            return {"timestamp": [1790899200, 1790985600], "equity": [0, 101000]}
        if method == "POST":
            cid = body.get("client_order_id")
            if cid in self.seen_ids:
                raise RuntimeError("Alpaca POST /v2/orders -> 422: client_order_id must be unique")
            self.seen_ids.add(cid)
            return {"id": f"id-{cid}", "status": "accepted"}
        return None


def test_alpaca_paper_is_default_endpoint():
    assert FakeAlpaca().base == AlpacaBroker.PAPER


def test_alpaca_normalization():
    b = FakeAlpaca()
    assert b.account() == {"equity": 101000.0, "cash": 40000.0, "buying_power": 80000.0, "day_pl": 1000.0}
    pos = b.positions()
    assert pos["AAPL"]["upl"] == 100.0 and pos["AAPL"]["day_pl"] == 20.0 and pos["AAPL"]["lastday"] == 208.0
    assert "BTC/USD" in pos and pos["BTC/USD"]["cls"] == "crypto"  # BTCUSD normalized to the pair
    o = b.orders()[0]
    assert (o["qty"], o["filled"], o["price"], o["time"], o["cls"]) == \
        (-5.0, -5.0, 211.5, "2026-10-05T13:30:02Z", "us_equity")
    assert b.history() == [("2026-10-03", 101000)]  # unfunded day dropped


def test_alpaca_crypto_orders_are_fractional_gtc():
    b = FakeAlpaca()
    b.submit("BTC/USD", 0.0123456, 62000, client_id="c1")
    b.submit("AAPL", 7, 210, client_id="c2")
    bodies = [c[2] for c in b.calls if c[0] == "POST"]
    assert bodies[0]["qty"] == "0.0123456" and bodies[0]["time_in_force"] == "gtc"
    assert bodies[1]["qty"] == "7" and bodies[1]["time_in_force"] == "day"


def test_retried_run_is_idempotent(tmp_path, lc):
    """Same day, same orders: the second run's orders come back 'duplicate' and raise no alert."""
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    b = FakeAlpaca()
    r1 = run(lc, prices, str(tmp_path / "a"), broker=b)
    assert r1["fills"] and all(f["status"] == "accepted" for f in r1["fills"])
    assert all(f["client_id"].startswith("af-equ-") for f in r1["fills"])
    r2 = run(lc, prices, str(tmp_path / "b"), broker=b)  # fresh state forces the same signal again
    assert r2["fills"] and all(f["status"] == "duplicate" for f in r2["fills"]) and not r2["alerts"]


def test_cancel_stale_only_touches_own_old_orders_in_its_class(tmp_path, lc):
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    b = FakeAlpaca()
    run(lc, prices, str(tmp_path), broker=b)
    assert [p for m, p, _ in b.calls if m == "DELETE"] == ["/v2/orders/old"]  # not manual, not crypto


def test_equity_sizing_excludes_crypto(tmp_path, lc):
    """Coins held in the account never count toward the stock sleeve's NAV, and are never sold by it."""
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    r = run(lc, prices, str(tmp_path), broker=FakeAlpaca())
    assert r["navs"]["equity"] == pytest.approx(101000 - 0.01 * 62000)
    assert not any("/" in f["symbol"] for f in r["fills"])


# ---------------------------------------------------------------- crypto sleeve

def _coins(n_days=400, seed=11):
    p, _ = synthetic_prices(n_assets=4, n_days=n_days, seed=seed)
    return p.set_axis(["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD"], axis=1)


def _crypto_lc(lc, **kw):
    c = {**CRYPTO_DEFAULTS, "enabled": True, "budget": 10_000, "max_data_age_days": 10_000,
         "universe": ["BTC/USD", "ETH/USD", "SOL/USD", "LTC/USD"], **kw}
    return {**lc, "crypto": c}


def _held(state):
    return json.load(open(os.path.join(state, "account.json")))["positions"]


def test_crypto_sleeve_nav_and_separation(tmp_path, lc):
    stocks, coins = synthetic_prices(n_assets=12, n_days=400, seed=3)[0], _coins()
    cfg, state = _crypto_lc(lc), str(tmp_path)
    run(cfg, stocks.iloc[:-1], state, crypto_prices=coins.iloc[:-1])   # both sleeves signal
    r = run(cfg, stocks, state, crypto_prices=coins)                    # both fill (sim: next close)
    assert any(e.startswith("crypto: executed") for e in r["events"])
    assert r["navs"]["equity"] + r["navs"]["crypto"] == pytest.approx(r["account"])
    assert abs(r["navs"]["crypto"] - 10_000) < 1_500                    # budget plus one day's P&L
    held = _held(state)
    coin_mv = sum(p["qty"] * coins.iloc[-1][s] for s, p in held.items() if "/" in s)
    assert 0 < coin_mv <= r["navs"]["crypto"] + 1e-6                    # never sized past its sleeve
    assert any("/" not in s for s in held)
    assert any(p["qty"] != int(p["qty"]) for s, p in held.items() if "/" in s)  # fractional coins


def test_crypto_halt_does_not_touch_stocks(tmp_path, lc):
    stocks, coins = synthetic_prices(n_assets=12, n_days=400, seed=3)[0], _coins()
    cfg, state = _crypto_lc(lc, max_drawdown_halt=0.05), str(tmp_path)
    run(cfg, stocks.iloc[:-1], state, crypto_prices=coins.iloc[:-1])
    run(cfg, stocks, state, crypto_prices=coins)
    crash = coins.copy()
    crash.loc[crash.index[-1] + pd.offsets.BDay()] = coins.iloc[-1] * 0.5
    nxt = stocks.copy()
    nxt.loc[nxt.index[-1] + pd.offsets.BDay()] = stocks.iloc[-1]
    before = {s: p["qty"] for s, p in _held(state).items() if "/" not in s}
    r = run(cfg, nxt, state, crypto_prices=crash)
    assert os.path.exists(os.path.join(state, "KILL_CRYPTO")) and not os.path.exists(os.path.join(state, "KILL"))
    after = _held(state)
    assert not any("/" in s for s in after)                             # crypto flattened
    assert {s: p["qty"] for s, p in after.items()} == before            # stocks untouched
    assert r["alerts"]


def test_trend_weights_go_to_cash_in_downtrends():
    idx = pd.bdate_range("2020-01-01", periods=200)
    down = pd.DataFrame({"A": np.linspace(100, 50, 200), "B": np.linspace(80, 40, 200)}, index=idx)
    cfg = Config(model="trend", mode="trend", target_vol=0.3, max_weight=0.5, max_leverage=1.0, warmup=120)
    w = backtest.targets_at(signals.alpha_panel(down, cfg), down.pct_change(), 199, cfg)
    assert (w == 0).all()
    up = down.iloc[::-1].set_axis(idx)
    w = backtest.targets_at(signals.alpha_panel(up, cfg), up.pct_change(), 199, cfg)
    assert (w > 0).all() and w.sum() <= 1.0 + 1e-9


# ---------------------------------------------------------------- swap overlay

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
    alt = run_backtest(shocked, cfg)
    pd.testing.assert_series_equal(swp.returns.iloc[: cut + 1], alt.returns.iloc[: cut + 1])
    pd.testing.assert_frame_equal(swp.weights.iloc[: cut + 1], alt.weights.iloc[: cut + 1])


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
    held = _held(str(tmp_path))
    assert {"SYN09", "SYN04"} <= set(held) and not {"SYN12", "SYN18"} & set(held)
