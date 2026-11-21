# Research report 4: multi-model forecasting

Generated 2026-11-21 by `python -m alphaforge.lab`. Rules committed before the run: [PREREGISTRATION_4.md](PREREGISTRATION_4.md).

## Track A: SPY

Weekly forecasts out of sample from January 2014; each model refitted every January on data whose target ended before it.

### 5 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 57.3% | 0.0172 |
| Ridge regression | -96.36% | 1.00 | 55.3% | 0.0241 |
| Random forest | +2.60% | 0.09 | 55.3% | 0.0170 |
| Gradient boosting | -12.25% | 0.98 | 53.5% | 0.0183 |
| Neural network | -1698.67% | 1.00 | 50.5% | 0.0731 |
| ARIMA(p,1,0) | +0.97% | 0.09 | 57.1% | 0.0171 |
| Momentum rule | -0.68% | 0.90 | 48.7% | 0.0173 |
| Ensemble | -29.86% | 0.98 | 56.8% | 0.0196 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -29.86%, DM p 0.98 |
| Hit rate above 50%, binomial p < 0.05 | pass | 56.8% of 620 forecasts (620 independent), p 0.00 |

### 21 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 65.9% | 0.0384 |
| Ridge regression | -423.42% | 1.00 | 53.7% | 0.0879 |
| Random forest | -4.81% | 0.97 | 59.1% | 0.0393 |
| Gradient boosting | -55.25% | 1.00 | 58.3% | 0.0479 |
| Neural network | -1934.69% | 0.97 | 58.3% | 0.1733 |
| ARIMA(p,1,0) | +0.43% | 0.26 | 65.9% | 0.0383 |
| Momentum rule | -2.14% | 0.92 | 55.8% | 0.0388 |
| Ensemble | -37.85% | 1.00 | 60.4% | 0.0451 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -37.85%, DM p 1.00 |
| Hit rate above 50%, binomial p < 0.05 | pass | 60.4% of 618 forecasts (147 independent), p 0.01 |

### 63 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 73.2% | 0.0617 |
| Ridge regression | -834.87% | 0.98 | 62.1% | 0.1886 |
| Random forest | -14.17% | 0.97 | 62.6% | 0.0659 |
| Gradient boosting | -88.91% | 1.00 | 56.2% | 0.0848 |
| Neural network | -330.97% | 0.96 | 57.8% | 0.1280 |
| ARIMA(p,1,0) | +1.92% | 0.18 | 73.2% | 0.0611 |
| Momentum rule | -4.43% | 0.91 | 62.3% | 0.0630 |
| Ensemble | -55.44% | 1.00 | 61.1% | 0.0769 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -55.44%, DM p 1.00 |
| Hit rate above 50%, binomial p < 0.05 | **fail** | 61.1% of 612 forecasts (48 independent), p 0.06 |

## Track B: point-in-time S&P 500 cross-section

| Model | Rank IC | IC t | Top 20% vs equal weight, IR | t |
|---|---|---|---|---|
| Ridge regression | -0.009 | -0.5 | -0.02 | -0.1 |
| Random forest | -0.006 | -0.4 | +0.00 | +0.0 |
| Gradient boosting | -0.004 | -0.3 | +0.03 | +0.1 |
| Neural network | +0.001 | +0.1 | +0.11 | +0.4 |
| Momentum rule | -0.010 | -0.5 | -0.09 | -0.3 |
| Ensemble | -0.005 | -0.3 | +0.04 | +0.1 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC -0.005, t -0.3 |
| 2. Edge vs equal weight | **fail** | IR +0.04, t +0.1 over 10.8 years |
| 3. Deflated | **fail** | 6% after 33 trials |
| 4. Stability | pass | 2016–19 -0.07, 2020–22 +0.16, 2023–now +0.04 |
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
