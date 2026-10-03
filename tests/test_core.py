import numpy as np
import pandas as pd
import pytest

from alphaforge import metrics, portfolio
from alphaforge.backtest import Config, run_backtest
from alphaforge.data import synthetic_prices


@pytest.fixture(scope="module")
def data():
    return synthetic_prices(n_assets=20, n_days=900, seed=1)


def test_no_lookahead(data):
    """Corrupting prices after day T must not change any return up to T."""
    prices, _ = data
    base = run_backtest(prices)
    cut = 600
    shocked = prices.copy()
    shocked.iloc[cut + 1:] *= np.random.default_rng(0).uniform(0.5, 1.5, shocked.iloc[cut + 1:].shape)
    alt = run_backtest(shocked)
    pd.testing.assert_series_equal(base.returns.iloc[: cut + 1], alt.returns.iloc[: cut + 1])
    pd.testing.assert_frame_equal(base.weights.iloc[: cut + 1], alt.weights.iloc[: cut + 1])
    pd.testing.assert_series_equal(base.turnover.iloc[: cut + 1], alt.turnover.iloc[: cut + 1])


def test_zero_costs_means_gross_equals_net(data):
    prices, _ = data
    r = run_backtest(prices, Config(cost_bps=0, slippage_bps=0))
    pd.testing.assert_series_equal(r.returns, r.gross_returns)
    assert r.turnover.sum() > 0


def test_costs_reduce_returns(data):
    prices, _ = data
    cheap = run_backtest(prices, Config(cost_bps=0, slippage_bps=0)).returns.sum()
    dear = run_backtest(prices, Config(cost_bps=20, slippage_bps=20)).returns.sum()
    assert dear < cheap


def test_risk_limits_respected(data):
    prices, _ = data
    cfg = Config(max_weight=0.08, max_leverage=1.5, target_vol=0.5)
    r = run_backtest(prices, cfg)
    trade_days = r.turnover > 0
    w = r.weights[trade_days]
    assert w.abs().max().max() <= 0.08 + 1e-9
    assert w.abs().sum(axis=1).max() <= 1.5 + 1e-9


def test_long_only_has_no_shorts(data):
    prices, _ = data
    r = run_backtest(prices, Config(mode="long_only"))
    assert (r.weights >= -1e-12).all().all()


def test_long_short_is_roughly_neutral():
    w = portfolio.alpha_to_weights(pd.Series([2.0, 1.0, 0.0, -1.0, -2.0]))
    assert abs(w.sum()) < 1e-12 and abs(w.abs().sum() - 1) < 1e-12


def test_cap_weights_preserves_gross():
    w = portfolio.cap_weights(np.array([0.6, 0.2, 0.1, 0.1]), 0.3)
    assert np.abs(w).max() <= 0.3 + 1e-12
    assert abs(np.abs(w).sum() - 1) < 1e-9


def test_metrics_known_values():
    r = pd.Series([0.01, -0.01] * 126, index=pd.bdate_range("2020-01-01", periods=252))
    assert metrics.sharpe(r) == pytest.approx(0.0, abs=1e-9)
    dd = metrics.drawdown(pd.Series([0.1, -0.5, 0.0]))
    assert dd.min() == pytest.approx(-0.5)
    var, cvar = metrics.var_cvar(pd.Series(np.linspace(-0.05, 0.05, 101)))
    assert var == pytest.approx(0.045, abs=1e-3) and cvar >= var


def test_summary_runs_with_benchmark(data):
    prices, bench = data
    s = metrics.summary(run_backtest(prices, benchmark=bench))
    assert {"Sharpe", "Max Drawdown", "Beta"} <= s.keys()
    assert np.isfinite(s["Sharpe"])


def test_cash_earns_risk_free_and_sharpe_uses_excess(data):
    prices, bench = data
    rf = pd.Series(0.04 / 252, index=prices.index)
    cfg = Config(mode="long_only", max_weight=0.05)  # caps leave cash idle
    no_rf, with_rf = run_backtest(prices, cfg, bench), run_backtest(prices, cfg, bench, rf)
    live = with_rf.weights.abs().sum(axis=1) > 0
    assert (with_rf.returns[live] > no_rf.returns[live]).mean() > 0.99  # idle cash adds rf every day
    s = metrics.summary(with_rf)
    r = with_rf.returns.loc[metrics.first_trade(with_rf):]
    assert s["Sharpe"] == pytest.approx(metrics.sharpe(r, rf))
    assert s["Sharpe"] < metrics.sharpe(r)


def test_monthly_table_labels_partial_first_year():
    r = pd.Series(0.001, index=pd.bdate_range("2020-03-02", "2021-02-26"))
    t = metrics.monthly_table(r)
    assert list(t.columns[:3]) == ["Jan", "Feb", "Mar"] and np.isnan(t.loc[2020, "Jan"])
