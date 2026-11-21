import pandas as pd
import pytest

from alphaforge import fundamentals as fu


def _cf():
    q = lambda s, e, v, f, form="10-Q": {"start": s, "end": e, "val": v, "filed": f, "form": form, "accn": f}
    eps = [q("2022-01-01", "2022-03-31", 1.0, "2022-04-28"), q("2022-04-01", "2022-06-30", 1.1, "2022-07-28"),
           q("2022-07-01", "2022-09-30", 1.2, "2022-10-27"),
           q("2022-01-01", "2022-12-31", 5.0, "2023-02-01", "10-K"),
           q("2022-01-01", "2022-03-31", 0.9, "2023-04-27")]            # a restated Q1, filed a year later
    eq = [{"end": "2022-12-31", "val": 100.0, "filed": "2023-02-01", "form": "10-K", "accn": "a"},
          {"end": "2022-12-31", "val": 80.0, "filed": "2024-02-01", "form": "10-K", "accn": "b"}]  # restated later
    sh = [{"end": "2023-01-20", "val": 6.0, "filed": "2023-02-01", "form": "10-K", "accn": "a"},
          {"end": "2023-01-20", "val": 4.0, "filed": "2023-02-01", "form": "10-K", "accn": "a"}]   # two share classes
    return {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": eps}},
                                  "StockholdersEquity": {"units": {"USD": eq}}},
                      "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": sh}}}}}


def test_first_filed_values_and_availability():
    ev = pd.DataFrame(fu.company_events(_cf()))
    eq = ev[ev["field"] == "equity"]
    assert eq["value"].tolist() == [100.0]                                  # the restatement never replaces it
    assert eq["available"].iloc[0] == pd.Timestamp("2023-02-02")             # usable the day after filing
    assert ev[ev["field"] == "shares"]["value"].tolist() == [10.0]           # share classes added up
    q = ev[ev["field"] == "eps_quarter"].set_index("end")["value"]
    assert q[pd.Timestamp("2022-03-31")] == 1.0                              # original Q1, not the restated 0.9
    assert q[pd.Timestamp("2022-12-31")] == pytest.approx(5.0 - 3.3)         # Q4 = year minus three quarters


def test_sue_uses_the_same_quarter_a_year_earlier_and_prior_changes_only():
    ends = pd.date_range("2018-03-31", periods=16, freq="QE")
    vals = [1.0 + 0.1 * i for i in range(16)]
    vals[-1] += 1.0                                                          # a big surprise in the last quarter
    q = pd.DataFrame({"end": ends, "value": vals, "available": ends + pd.Timedelta(days=30)})
    s = fu.sue_events(q)
    assert s and s[-1]["end"] == ends[-1] and s[-1]["value"] > 3
    assert all(e["available"] > e["end"] for e in s)


def test_asof_panel_respects_availability_and_age():
    ev = pd.DataFrame({"ticker": ["A", "A"], "field": ["sue", "sue"], "value": [1.0, 2.0],
                       "available": pd.to_datetime(["2023-02-02", "2023-05-02"]), "end": pd.to_datetime(["2022-12-31", "2023-03-31"])})
    months = pd.to_datetime(["2023-01-31", "2023-02-28", "2023-04-28", "2023-05-31", "2023-10-31"])
    p = fu.asof_panel(ev, "sue", months, ["A"], max_age_days=122)["A"]
    assert pd.isna(p.iloc[0]) and p.iloc[1] == 1.0 and p.iloc[2] == 1.0 and p.iloc[3] == 2.0 and pd.isna(p.iloc[4])
