import pandas as pd
import pytest

from alphaforge import analytics, signals
from alphaforge.backtest import Config, run_backtest
from alphaforge.data import synthetic_prices
from alphaforge.live import load_config, run


@pytest.fixture(scope="module")
def setup():
    prices, bench = synthetic_prices(n_assets=24, n_days=700, seed=11)
    sectors = {s: ["A", "B", "C", "D"][i % 4] for i, s in enumerate(prices.columns)}
    model = analytics.risk_model(prices.pct_change(), signals.factor_scores(prices), sectors)
    res = run_backtest(prices, Config(mode="long_only", target_vol=0.12, max_weight=0.1, max_leverage=1.0), bench)
    return prices, model, res


def test_risk_decomposition_adds_up(setup):
    prices, model, _ = setup
    w = pd.Series(1 / 12, index=prices.columns[:12])
    d = analytics.decompose(w, model, 252)
    assert sum(d["groups"].values()) == pytest.approx(1.0)
    assert sum(n["share"] for n in d["names"].values()) == pytest.approx(1.0)
    assert d["vol"] ** 2 == pytest.approx(d["factor_vol"] ** 2 + d["specific_vol"] ** 2)


def test_attribution_is_exact(setup):
    prices, model, res = setup
    a = analytics.attribution(res, model, prices.pct_change(), "W-FRI")
    assert abs(a["residual"]) < 1e-9
    assert sum(a["parts"].values()) == pytest.approx(a["total"])
    assert sum(a["styles"].values()) == pytest.approx(a["parts"]["Style"])


def test_tca_splits_slippage_into_delay_and_impact():
    idx = pd.to_datetime(["2026-10-01", "2026-10-02"])
    raw = pd.concat({"Open": pd.DataFrame({"X": [100, 101.0]}, index=idx),
                     "Volume": pd.DataFrame({"X": [1e6, 1e6]}, index=idx)}, axis=1)
    o = {"time": "2026-10-02T13:30:05Z", "symbol": "X", "qty": 100, "filled": 100, "price": 101.5, "status": "filled",
         "ref": 100.0, "slip_bps": 150.0}
    t = analytics.tca([o], raw, lambda s: s, False, 7)
    r = t["rows"][0]
    assert r["delay_bps"] == pytest.approx(100.0) and r["impact_bps"] == pytest.approx(49.5, abs=0.1)
    assert r["participation"] == pytest.approx(1e-4) and t["summary"]["fill_rate"] == 1.0


def test_limits_traffic_lights():
    rows = analytics.limits([("a", 0.5, 1, "soft", "pct"), ("b", 0.95, 1, "soft", "pct"), ("c", -0.3, 0.2, "hard", "pct")])
    assert [r["light"] for r in rows] == ["green", "amber", "red"]


def test_approval_holds_the_rebalance_until_approved(tmp_path, monkeypatch):
    lc = {**load_config(None), "strategy": {"mode": "long_only"}, "max_data_age_days": 10_000, "require_approval": True}
    prices, _ = synthetic_prices(n_assets=12, n_days=400, seed=3)
    state = str(tmp_path)
    monkeypatch.delenv("ALPHAFORGE_APPROVE", raising=False)
    r = run(lc, prices.iloc[:-2], state)
    assert "rebalance waiting for approval" in r["events"] and r["alerts"]
    r = run(lc, prices.iloc[:-1], state)  # still waiting: no new alert, no signal
    assert "rebalance waiting for approval" in r["events"] and not r["alerts"]
    monkeypatch.setenv("ALPHAFORGE_APPROVE", "equity")
    r = run(lc, prices, state)
    assert "generated month-end signal" in r["events"]
    assert (tmp_path / "audit.jsonl").read_text().count("\n") == 3
