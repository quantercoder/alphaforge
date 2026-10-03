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


# ---------------------------------------------------------------- optimizer

def test_qp_solver_projects_onto_capped_simplex():
    import numpy as np
    from alphaforge.portfolio import solve_qp
    # min 1/2 |x - c|^2, 0 <= x <= 1, sum x <= 1  ->  known answer [0.6, 0.4, 0]
    A = np.vstack([np.eye(3), np.ones((1, 3))])
    x = solve_qp(np.eye(3), -np.array([0.8, 0.6, -0.2]), A, np.array([0, 0, 0, -np.inf]), np.array([1, 1, 1, 1.0]))
    assert x == pytest.approx([0.6, 0.4, 0.0], abs=1e-5)


def test_optimizer_respects_sector_beta_and_caps(setup):
    import numpy as np
    from alphaforge.portfolio import optimize
    prices, _, _ = setup
    rets = prices.pct_change().iloc[-252:]
    names = prices.columns
    sectors = ["A" if i < 8 else "B" if i < 16 else "C" for i in range(len(names))]
    target = pd.Series(0.0, index=names)
    target[names[:8]] = 0.1  # 80% in sector A
    w = optimize(target, rets.iloc[-63:], rets, 0.1, 1.0, max_sector=0.4, max_beta=0.9, sectors=sectors)
    assert (w >= 0).all() and w.max() <= 0.1 + 1e-9 and w.sum() <= 1 + 1e-9
    assert w[names[:8]].sum() <= 0.4 + 1e-9
    mkt = rets.mean(axis=1)
    beta = rets.apply(lambda c: c.cov(mkt)) / mkt.var()
    assert float(beta @ w) <= 0.9 + 1e-6
    # A turnover penalty keeps the book closer to where it is.
    now = pd.Series(0.05, index=names)
    lazy = optimize(target, rets.iloc[-63:], rets, 0.1, 1.0, max_sector=0.4, sectors=sectors, turnover_penalty=0.01, w_now=now)
    busy = optimize(target, rets.iloc[-63:], rets, 0.1, 1.0, max_sector=0.4, sectors=sectors, w_now=now)
    assert np.abs(lazy - now).sum() < np.abs(busy - now).sum()


def test_constrained_backtest_stays_causal(setup):
    import numpy as np
    prices, _, _ = setup
    cfg = Config(mode="long_only", target_vol=0.12, max_weight=0.1, max_leverage=1.0, max_beta=1.0, turnover_penalty=0.001)
    base = run_backtest(prices, cfg)
    cut = 600
    shocked = prices.copy()
    shocked.iloc[cut + 1:] *= np.random.default_rng(0).uniform(0.5, 1.5, shocked.iloc[cut + 1:].shape)
    alt = run_backtest(shocked, cfg)
    pd.testing.assert_series_equal(base.returns.iloc[: cut + 1], alt.returns.iloc[: cut + 1])
    w = base.weights[base.turnover > 0]
    assert w.max().max() <= 0.1 + 1e-9 and (w >= 0).all().all()


def test_shadow_backtest_starts_on_the_given_day(setup):
    prices, _, _ = setup
    day = prices.index[650]
    r = run_backtest(prices, Config(mode="long_only"), start=day)
    assert r.weights.loc[:day].abs().sum().sum() == 0 and r.weights.iloc[652].sum() > 0


def test_paper_returns_ignore_the_crypto_carve_out(tmp_path):
    from alphaforge.terminal import _paper_navs
    (tmp_path / "equity.csv").write_text(
        "date,equity,account,crypto\n2026-10-01,100000,,\n2026-10-02,101000,,\n"
        "2026-10-05,91000,101000,10000\n2026-10-06,91910,102010,10100\n")
    nav, r = _paper_navs(str(tmp_path), "equity")
    assert r.round(6).tolist() == [round(1000 / 90000, 6), 0.0, round((1010 - 100) / 91000, 6)]
    assert nav.iloc[-1] == 91910
