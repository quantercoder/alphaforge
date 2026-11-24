# Research report 4: multi-model forecasting

Generated 2026-11-24 by `python -m alphaforge.lab`. Rules committed before the run: [PREREGISTRATION_4.md](PREREGISTRATION_4.md).

## Track A: SPY

Weekly forecasts out of sample from January 2014; each model refitted every January on data whose target ended before it.

### 5 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 57.3% | 0.0172 |
| Ridge regression | -96.35% | 1.00 | 55.3% | 0.0241 |
| Random forest | +2.60% | 0.09 | 55.3% | 0.0170 |
| Gradient boosting | -12.23% | 0.98 | 53.7% | 0.0183 |
| Neural network | -1698.69% | 1.00 | 50.5% | 0.0731 |
| ARIMA(p,1,0) | +0.97% | 0.09 | 57.1% | 0.0171 |
| Momentum rule | -0.68% | 0.90 | 48.7% | 0.0173 |
| Ensemble | -29.86% | 0.98 | 56.6% | 0.0196 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -29.86%, DM p 0.98 |
| Hit rate above 50%, binomial p < 0.05 | pass | 56.6% of 620 forecasts (620 independent), p 0.00 |

### 21 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 65.9% | 0.0384 |
| Ridge regression | -423.42% | 1.00 | 53.7% | 0.0879 |
| Random forest | -4.81% | 0.97 | 59.1% | 0.0393 |
| Gradient boosting | -54.94% | 1.00 | 58.3% | 0.0478 |
| Neural network | -1930.97% | 0.97 | 57.4% | 0.1731 |
| ARIMA(p,1,0) | +0.43% | 0.26 | 65.9% | 0.0383 |
| Momentum rule | -2.14% | 0.92 | 55.8% | 0.0388 |
| Ensemble | -37.71% | 1.00 | 60.4% | 0.0451 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -37.71%, DM p 1.00 |
| Hit rate above 50%, binomial p < 0.05 | pass | 60.4% of 618 forecasts (147 independent), p 0.01 |

### 63 trading days

| Model | Out-of-sample R² | DM p | Hit rate | RMSE |
|---|---|---|---|---|
| Historical mean | +0.00% |  | 73.2% | 0.0617 |
| Ridge regression | -834.87% | 0.98 | 62.1% | 0.1886 |
| Random forest | -14.17% | 0.97 | 62.6% | 0.0659 |
| Gradient boosting | -89.38% | 1.00 | 56.5% | 0.0849 |
| Neural network | -344.50% | 0.96 | 58.5% | 0.1300 |
| ARIMA(p,1,0) | +1.92% | 0.18 | 73.2% | 0.0611 |
| Momentum rule | -4.43% | 0.91 | 62.3% | 0.0630 |
| Ensemble | -56.17% | 0.99 | 60.9% | 0.0771 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| Out-of-sample R² above 0 and Diebold-Mariano p < 0.05 | **fail** | R² -56.17%, DM p 0.99 |
| Hit rate above 50%, binomial p < 0.05 | **fail** | 60.9% of 612 forecasts (48 independent), p 0.06 |

## Track B: point-in-time S&P 500 cross-section

| Model | Rank IC | IC t | Top 20% vs equal weight, IR | t |
|---|---|---|---|---|
| Ridge regression | -0.008 | -0.5 | -0.03 | -0.1 |
| Random forest | -0.007 | -0.5 | +0.01 | +0.0 |
| Gradient boosting | -0.003 | -0.3 | +0.06 | +0.2 |
| Neural network | -0.000 | -0.0 | +0.10 | +0.3 |
| Momentum rule | -0.010 | -0.5 | -0.09 | -0.3 |
| Ensemble | -0.005 | -0.3 | -0.02 | -0.1 |

| Rule (ensemble) | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC -0.005, t -0.3 |
| 2. Edge vs equal weight | **fail** | IR -0.02, t -0.1 over 10.8 years |
| 3. Deflated | **fail** | 4% after 33 trials |
| 4. Stability | **fail** | 2016–19 -0.14, 2020–22 +0.08, 2023–now -0.01 |
| 5. Breadth | **fail** | liquid +0.16, less liquid -0.17 |
| 6. Coverage | **fail** | 83.8% of member-months priced |

## Verdict

Track A: no horizon shows out-of-sample skill over the historical mean. Track B: fails; the live strategy is unchanged.

## Amendment: first run

The first run (21 November 2026) had a defect: the neural network's target was not standardized and its forecasts diverged. Its out-of-sample R² was −1,696% (5 days), −669% (21 days) and −291% (63 days), which dragged the ensemble to −46%, −19% and −6%. Every rule failed in that run too. The tables above are after the fix ([PREREGISTRATION_4.md](PREREGISTRATION_4.md), amendment); a pass appearing only after the fix would be exploratory, not demonstrated.

## Strategy lab

| Strategy | Universe | Sharpe | Sortino | CAGR | Max DD | Since |
|---|---|---|---|---|---|---|
| Crypto trend (live sleeve) | 8 coins, daily (survivorship-biased) | 0.92 | 1.35 | 27.8% | -47.6% | 2019-05-04 |
| Bitcoin buy and hold | BTC, daily | 0.82 | 1.21 | 36.6% | -76.6% | 2019-05-04 |
| Low volatility, long-only | Point-in-time S&P 500, monthly | 0.78 | 1.26 | 11.8% | -18.7% | 2012-01-31 |
| Momentum, long-only top 20% | Point-in-time S&P 500, monthly | 0.76 | 1.22 | 13.6% | -19.5% | 2012-01-31 |
| Multi-factor (momentum + low vol + reversal) | Point-in-time S&P 500, monthly | 0.75 | 1.15 | 12.2% | -21.9% | 2012-01-31 |
| Equal weight S&P 500 (benchmark) | Point-in-time S&P 500, monthly | 0.74 | 1.14 | 13.2% | -26.9% | 2012-01-31 |
| Buy and hold SPY | SPY, daily | 0.61 | 0.86 | 10.1% | -33.7% | 2010-01-04 |
| Volatility targeting (GARCH, 15%) | SPY, daily | 0.60 | 0.83 | 9.8% | -23.8% | 2010-01-04 |
| Mean reversion (RSI-2 dips) | SPY, daily | 0.58 | 0.84 | 5.0% | -14.8% | 2010-01-04 |
| Trend following (200-day average) | SPY, daily | 0.44 | 0.59 | 5.8% | -22.0% | 2010-01-04 |
| Momentum, market-neutral long/short | Point-in-time S&P 500, monthly | 0.03 | 0.04 | 1.5% | -40.2% | 2012-01-31 |
| Short-term reversal, long/short | Point-in-time S&P 500, monthly | -0.15 | -0.21 | -0.6% | -42.5% | 2012-01-31 |
| Pairs trading (distance method) | Today's S&P 100, daily (survivorship-biased) | -0.27 | -0.39 | -1.0% | -16.5% | 2014-01-02 |
