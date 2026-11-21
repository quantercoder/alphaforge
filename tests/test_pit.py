import numpy as np
import pandas as pd

from alphaforge import pit
from alphaforge.data import synthetic_prices


def _monthly():
    prices, _ = synthetic_prices(n_assets=80, n_days=1500, seed=5)
    return prices, pit.month_ends(prices)


def test_membership_spells_and_ticker_format(tmp_path):
    f = tmp_path / "m.csv"
    f.write_text("ticker,start_date,end_date\nAAL,1996-01-02,1997-01-15\nAAL,2015-03-23,2024-09-23\nBRK.B,2010-02-16,\n")
    sp = pit.membership(str(f))
    assert set(sp) == {"AAL", "BRK-B"} and len(sp["AAL"]) == 2
    d = pd.to_datetime(["1996-06-28", "2010-01-29", "2016-01-29", "2024-09-30", "2026-01-30"])
    m = pit.member_mask(sp, d, ["AAL", "BRK-B"])
    assert m["AAL"].tolist() == [True, False, True, False, False]
    assert m["BRK-B"].tolist() == [False, False, True, True, True]


def test_signals_use_only_the_past():
    prices, monthly = _monthly()
    members = monthly.notna()
    t = 40
    shocked = prices.copy()
    cut = prices.index.get_loc(monthly.index[t])
    shocked.iloc[cut + 1:] *= np.random.default_rng(1).uniform(0.5, 1.5, shocked.iloc[cut + 1:].shape)
    m2 = pit.month_ends(shocked)
    for f in (pit.momentum, lambda m: pit.residual_momentum(m, members), None):
        a = f(monthly) if f else pit.high52(prices, monthly)
        b = f(m2) if f else pit.high52(shocked, m2)
        pd.testing.assert_frame_equal(a.iloc[: t + 1], b.iloc[: t + 1])


def test_a_cheating_signal_is_caught():
    _, monthly = _monthly()
    fwd = monthly.shift(-1) / monthly - 1
    el = monthly.notna().iloc[13:-1]
    s, b, ic = pit.simulate(fwd.iloc[13:-1], fwd.iloc[13:-1], el)  # "signal" = next month's return
    assert ic.mean() > 0.99 and (s - b).mean() > 0.02
    noise = pd.DataFrame(np.random.default_rng(2).normal(size=fwd.shape), index=fwd.index, columns=fwd.columns)
    _, _, ic0 = pit.simulate(noise.iloc[13:-1], fwd.iloc[13:-1], el)
    assert abs(ic0.mean()) < 0.05
