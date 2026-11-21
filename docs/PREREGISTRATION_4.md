# Pre-registered test 4: multi-model forecasting (statistical, machine learning, ensemble)

Written and committed **before** any model below was fitted (see this file's git history). Code:
`alphaforge/models.py` and `alphaforge/lab.py`; output: [RESEARCH_4.md](RESEARCH_4.md) and the Lab page.

## Two tracks

**A. The market (SPY), time series.** Forecast SPY's log return over the next 5, 21 and 63 trading days.

- Features, all known at the forecast date: SPY's past returns over 5, 21, 63 and 252 days; distance from its
  200-day average; 21-day realized and GARCH(1,1) volatility; VIX level and 21-day change; term spread (10-year
  minus 3-month Treasury yield); credit (63-day log change of HYG / IEF); dollar (63-day change of DXY); oil
  (63-day change of WTI). Sources: Yahoo.
- Sampled weekly (Fridays), so overlapping targets are fewer.
- Out of sample from January 2014. Each model is refitted every January on all data whose target ended
  before that date (purged walk-forward, López de Prado 2018).

**B. The cross-section (point-in-time S&P 500).** Forecast each member's next-month return relative to the
average member, on the universe of test 2 ([PREREGISTRATION_PIT.md](PREREGISTRATION_PIT.md)).

- Features at each month-end: 12-1 and 6-1 momentum, 1-month reversal, 52-week-high ratio, 63-day
  volatility, 252-day beta, residual momentum, largest daily return in the last 21 days, log 63-day dollar
  volume.
- Out of sample from January 2016; refitted every January on the prior months, the last month purged.

## Models (the same set in both tracks)

| Model | Specification (fixed in advance, not tuned on the test) |
|---|---|
| Historical mean | the benchmark every other forecast must beat (Campbell & Thompson 2008) |
| ARIMA(p,1,0) | track A only: AR(p) on returns, p ∈ 1..5 chosen by AIC at each refit |
| Ridge regression | standardized features, penalty 10 |
| Random forest | 300 trees, depth 4, at least 50 samples per leaf |
| Gradient boosting | scikit-learn HistGradientBoosting (XGBoost-style), depth 3, learning rate 0.05, 200 rounds |
| Neural network | MLP with 32 and 16 hidden units, early stopping |
| Momentum rule | track A: historical mean if the past year's return is positive, else 0. Track B: 12-1 momentum |
| **Ensemble** | equal-weight average of the five learning models and the momentum rule |

## Rules

**Track A (per horizon, judged on the ensemble):**

1. Out-of-sample R² against the historical mean (Campbell & Thompson) above 0, and the Diebold-Mariano test
   (Newey-West variance, lag = horizon in weeks) rejects equal accuracy at the 5% level, one-sided.
2. Directional hit rate above 50%, binomial p < 0.05 on the number of non-overlapping forecasts.

**Track B (the ensemble's top 20%, equal weight, monthly, against equal weight of all members):** the six
rules of test 2, with these changes: stability over 2016–19, 2020–22 and 2023–latest (positive in at least
2 of 3), and the deflation counts every configuration tried in the project: 29 before this test, plus
3 horizons in track A and 1 in track B = **33**.

## Decision

- The Lab page shows every model's forecasts and out-of-sample record whatever the result.
- Only a track B pass could lead to proposing a change to the live strategy, and only with your approval.
  A track A pass would be reported, not traded.
- Deep learning (LSTM, Transformer) is not in this test. PyTorch is about 800 MB per install, and the
  evidence for deep sequence models on daily returns is weak (Gu, Kelly & Xiu 2020 find shallow networks
  do as well as deep ones for return prediction). It can be added as its own pre-registered test.
