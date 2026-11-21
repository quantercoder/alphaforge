# Research report 4: multi-model forecasting

Generated 2026-11-21 by `python -m alphaforge.lab`. Rules committed before the run: [PREREGISTRATION_4.md](PREREGISTRATION_4.md).

## Track A: SPY

Weekly forecasts out of sample from January 2014; each model refitted every January on data whose target ended before it.

### 5 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 57.7% | 0.0169 |
| Ridge regression | -3.10% | 0.86 | 55.1% | 0.0172 |
| Random forest | +1.22% | 0.22 | 55.7% | 0.0168 |
| Gradient boosting | -1.90% | 0.66 | 55.7% | 0.0171 |
| Neural network | -10.18% | 0.97 | 51.3% | 0.0178 |
| ARIMA(p,1,0) | +0.66% | 0.18 | 56.7% | 0.0169 |
| Momentum rule | -0.47% | 0.90 | 49.9% | 0.0170 |
| Ensemble | +2.69% | 0.06 | 57.0% | 0.0167 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² +2.69%, DM p 0.06 |
| Hit rate above 50%, binomial p < 0.05 | pass | 57.0% of 672 forecasts (672 independent), p 0.00 |

### 21 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 66.0% | 0.0375 |
| Ridge regression | -13.35% | 0.99 | 62.4% | 0.0399 |
| Random forest | -2.70% | 0.74 | 64.6% | 0.0380 |
| Gradient boosting | -34.12% | 1.00 | 53.9% | 0.0434 |
| Neural network | -17.15% | 1.00 | 61.8% | 0.0406 |
| ARIMA(p,1,0) | -0.28% | 0.69 | 66.0% | 0.0375 |
| Momentum rule | -1.71% | 0.93 | 56.7% | 0.0378 |
| Ensemble | -1.63% | 0.75 | 63.9% | 0.0378 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -1.63%, DM p 0.75 |
| Hit rate above 50%, binomial p < 0.05 | pass | 63.9% of 670 forecasts (159 independent), p 0.00 |

### 63 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 74.1% | 0.0591 |
| Ridge regression | -34.63% | 1.00 | 68.8% | 0.0685 |
| Random forest | -8.83% | 0.95 | 66.7% | 0.0616 |
| Gradient boosting | -51.38% | 1.00 | 57.8% | 0.0727 |
| Neural network | -28.25% | 1.00 | 60.8% | 0.0669 |
| ARIMA(p,1,0) | -0.73% | 0.66 | 74.1% | 0.0593 |
| Momentum rule | -3.70% | 0.94 | 64.0% | 0.0601 |
| Ensemble | -0.17% | 0.51 | 69.6% | 0.0591 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -0.17%, DM p 0.51 |
| Hit rate above 50%, binomial p < 0.05 | pass | 69.6% of 664 forecasts (52 independent), p 0.00 |

## Track B: point-in-time S&P 500 cross-section

| Model | Rank IC | IC t | Top 20% vs equal weight, IR | t |
|---|---|---|---|---|
| Ridge regression | -0.009 | -0.5 | -0.02 | -0.1 |
| Random forest | -0.007 | -0.4 | +0.01 | +0.0 |
| Gradient boosting | -0.003 | -0.2 | +0.09 | +0.3 |
| Neural network | -0.001 | -0.1 | +0.14 | +0.5 |
| Momentum rule | -0.010 | -0.5 | -0.09 | -0.3 |
| Ensemble | -0.005 | -0.3 | +0.00 | +0.0 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC -0.005, t -0.3 |
| 2. Edge vs equal weight | **fail** | IR +0.00, t +0.0 over 10.8 years |
| 3. Deflated | **fail** | 4% after 33 trials |
| 4. Stability | pass | 2016–19 -0.19, 2020–22 +0.12, 2023–now +0.03 |
| 5. Breadth | **fail** | liquid +0.13, less liquid -0.12 |
| 6. Coverage | **fail** | 83.9% of member-months priced |

## Verdict

Track A: no horizon shows out-of-sample skill over the historical mean. Track B: fails; the live strategy is unchanged.

## Amendment: first run

The first run (21 November 2026) had a defect: the neural network's target was not standardized and its forecasts diverged. Its out-of-sample R² was −1,696% (5 days), −669% (21 days) and −291% (63 days), which dragged the ensemble to −46%, −19% and −6%. Every rule failed in that run too. The tables above are after the fix ([PREREGISTRATION_4.md](PREREGISTRATION_4.md), amendment); a pass appearing only after the fix would be exploratory, not demonstrated.

## Strategy lab

| Strategy | Universe | Sharpe | Sortino | CAGR | Max DD | Since |
|---|---|---|---|---|---|---|
| Crypto trend (live sleeve) | 8 coins, daily (survivorship-biased) | 0.92 | 1.35 | 27.8% | -47.6% | 2019-05-04 |
| Bitcoin buy and hold | BTC, daily | 0.81 | 1.20 | 36.0% | -76.6% | 2019-05-04 |
| Low volatility, long-only | Point-in-time S&P 500, monthly | 0.77 | 1.24 | 11.5% | -18.7% | 2012-01-31 |
| Momentum, long-only top 20% | Point-in-time S&P 500, monthly | 0.74 | 1.17 | 13.4% | -19.5% | 2012-01-31 |
| Equal weight S&P 500 (benchmark) | Point-in-time S&P 500, monthly | 0.72 | 1.11 | 13.0% | -26.9% | 2012-01-31 |
| Multi-factor (momentum + low vol + reversal) | Point-in-time S&P 500, monthly | 0.72 | 1.11 | 11.9% | -21.9% | 2012-01-31 |
| Buy and hold SPY | SPY, daily | 0.60 | 0.85 | 9.9% | -33.7% | 2010-01-04 |
| Volatility targeting (GARCH, 15%) | SPY, daily | 0.60 | 0.82 | 9.6% | -23.8% | 2010-01-04 |
| Mean reversion (RSI-2 dips) | SPY, daily | 0.58 | 0.84 | 5.0% | -14.8% | 2010-01-04 |
| Trend following (200-day average) | SPY, daily | 0.44 | 0.59 | 5.8% | -22.0% | 2010-01-04 |
| Momentum, market-neutral long/short | Point-in-time S&P 500, monthly | 0.03 | 0.04 | 1.4% | -40.2% | 2012-01-31 |
| Short-term reversal, long/short | Point-in-time S&P 500, monthly | -0.12 | -0.18 | -0.2% | -38.8% | 2012-01-31 |
| Pairs trading (distance method) | Today's S&P 100, daily (survivorship-biased) | -0.27 | -0.39 | -1.0% | -16.5% | 2014-01-02 |
