import numpy as np
import pandas as pd
import pytest

from alphaforge import models


def _close(n=2600, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2008-01-01", periods=n)
    walk = lambda s, v: pd.Series(s * np.exp(np.cumsum(rng.normal(0, v, n))), index=idx)
    return pd.DataFrame({"SPY": walk(100, 0.01), "^VIX": walk(20, 0.03), "^TNX": walk(3, 0.01), "^IRX": walk(2, 0.01),
                         "HYG": walk(80, 0.004), "IEF": walk(100, 0.003), "DX-Y.NYB": walk(95, 0.004), "CL=F": walk(70, 0.02)})


def test_ar_recovers_coefficients():
    rng = np.random.default_rng(1)
    e = rng.normal(0, 0.01, 6000)
    r = np.zeros(6000)
    for t in range(1, 6000):
        r[t] = 0.0002 + 0.3 * r[t - 1] + e[t]
    p, beta = models.ar_fit(pd.Series(r))
    assert beta[1] == pytest.approx(0.3, abs=0.03)
    assert models.ar_forecast(r, p, beta, 1) == pytest.approx(beta[0] + sum(beta[k] * r[-k] for k in range(1, p + 1)))


def test_market_walk_forward_has_no_look_ahead():
    close = _close()
    t0 = close.index[2100]
    shocked = close.copy()
    shocked.iloc[2101:] *= np.random.default_rng(2).uniform(0.7, 1.3, shocked.iloc[2101:].shape)
    kw = dict(first_oos=2013, horizons=(5,), models=("Ridge regression",))
    a, _, _ = models.walk_forward_market(close, **kw)
    b, _, _ = models.walk_forward_market(shocked, **kw)
    cols = ["Historical mean", "Ridge regression", "ARIMA(p,1,0)", "Momentum rule", "Ensemble"]
    pd.testing.assert_frame_equal(a[5].loc[:t0, cols], b[5].loc[:t0, cols])


def test_scoring_against_the_historical_mean():
    idx = pd.date_range("2020-01-03", periods=300, freq="W-FRI")
    y = pd.Series(np.random.default_rng(3).normal(0.002, 0.02, 300), index=idx)
    P = pd.DataFrame({"Historical mean": 0.002, "Perfect": y, "Ensemble": y * 0.5 + 0.001, "y": y})
    ev = models.evaluate(P, 5)
    assert ev["Historical mean"]["r2_oos"] == 0 and ev["Perfect"]["r2_oos"] == 1 and ev["Perfect"]["hit"] == 1
    assert ev["Ensemble"]["dm_p"] < 0.05


def test_panel_walk_forward_purges_and_stays_causal():
    rng = np.random.default_rng(4)
    months = pd.date_range("2010-01-31", periods=120, freq="ME")
    cols = [f"S{i}" for i in range(100)]
    feat = {k: pd.DataFrame(rng.uniform(-1, 1, (120, 100)), index=months, columns=cols) for k in ("mom_12_1", "a", "b")}
    fwd = pd.DataFrame(rng.normal(0, 0.05, (120, 100)), index=months, columns=cols)
    el = pd.DataFrame(True, index=months, columns=cols)
    kw = dict(first_oos=2016, models=("Ridge regression",))
    base = models.panel_walk_forward(feat, fwd, el, **kw)
    later = fwd.copy()
    later.loc["2016-12-31"] = rng.normal(0, 0.05, 100)  # December's target is only known at the end of January
    alt = models.panel_walk_forward(feat, later, el, **kw)
    for y in ("2016", "2017"):  # 2017's model is fitted on January 1st, so it must not see that target
        pd.testing.assert_frame_equal(base["Ridge regression"].loc[y], alt["Ridge regression"].loc[y])
    assert not base["Ridge regression"].loc["2018"].equals(alt["Ridge regression"].loc["2018"])


def test_alfred_values_are_as_first_known():
    from alphaforge.macro import known_on
    T = pd.Timestamp
    v = pd.DataFrame({  # January's payrolls: published as 100 on Feb 7, revised to 90 on Mar 6
        "date": [T("2020-01-01"), T("2020-01-01"), T("2020-02-01")],
        "value": [100.0, 90.0, 110.0],
        "realtime_start": [T("2020-02-07"), T("2020-03-06"), T("2020-03-06")],
        "realtime_end": [T("2020-03-05"), T("2262-04-11"), T("2262-04-11")]})
    assert known_on(v, T("2020-02-06")).empty                            # not yet published
    assert known_on(v, T("2020-02-20")).tolist() == [100.0]              # first release, revision not visible
    assert known_on(v, T("2020-03-10")).tolist() == [90.0, 110.0]        # after the revision
