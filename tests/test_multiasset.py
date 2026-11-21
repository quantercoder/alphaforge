import numpy as np
import pandas as pd
import pytest

from alphaforge import multiasset as ma


def _rets(n=600, seed=0):
    idx = pd.bdate_range("2015-01-01", periods=n)
    rng = np.random.default_rng(seed)
    return pd.DataFrame({"SPY": rng.normal(0.0004, 0.01, n), "IEF": rng.normal(0.0001, 0.004, n)}, index=idx), pd.Series(0.0001, index=idx)


def test_holding_one_asset_reproduces_its_returns():
    rets, rf = _rets()
    dates = ma.month_ends(rets.index, "2015-01-01")
    r, turn = ma.simulate(rets, rf, ma.fixed({"SPY": 1.0}), dates)
    first = rets.index.get_loc(dates[0]) + 1            # bought at the close after the first month-end
    assert turn.iloc[first] == pytest.approx(1.0)
    after = rets.index[first + 1:]
    np.testing.assert_allclose(r[after], rets["SPY"][after], atol=1e-12)   # no further trading at 100%


def test_sixty_forty_rebalances_monthly_and_pays_costs():
    rets, rf = _rets()
    dates = ma.month_ends(rets.index, "2015-01-01")
    r, turn = ma.simulate(rets, rf, ma.fixed({"SPY": 0.6, "IEF": 0.4}), dates)
    trades = turn[turn > 0]
    assert len(trades) == len(dates) - (1 if dates[-1] == rets.index[-1] else 0) and trades.iloc[1:].max() < 0.1


def test_leverage_and_loss_odds():
    idx = pd.bdate_range("2015-01-01", periods=10)
    r, rf = pd.Series(0.01, index=idx), pd.Series(0.0001, index=idx)
    assert ma.levered(r, rf, 2.0).iloc[0] == pytest.approx(2 * 0.01 - 0.0001 - 0.02 / 252)
    assert ma.levered(r, rf, 0.5).iloc[0] == pytest.approx(0.5 * 0.01 + 0.5 * 0.0001)
    up = pd.Series(0.0005, index=pd.bdate_range("2010-01-01", periods=2000))
    assert ma.loss_odds(up, 1) == 0 and ma.loss_odds(-up, 1) == 1
