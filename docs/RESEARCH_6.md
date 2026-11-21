# Research report 6: SPY forecasts with point-in-time macro data

Generated 2026-11-21 by `python -m alphaforge.macro`. Rules committed before the run: [PREREGISTRATION_6.md](PREREGISTRATION_6.md).

Features: 19 (ret_5d, ret_21d, ret_63d, ret_252d, vs_200d_avg, realized_vol_21d, garch_vol, term_spread, credit_spread, vix, dollar_63d, oil_63d, payroll_growth, unemployment_momentum, inflation_12m, industrial_6m, claims_trend, financial_conditions, permits_12m). Macro series are ALFRED vintages as known on each forecast date. First complete feature row: 2011-05-27. Out of sample from January 2014.

## 5 trading days

| Model | Out-of-sample R² | DM p | Hit rate |
|---|---|---|---|
| Historical mean | +0.00% |  | 58.5% |
| Ridge regression | -184.91% | 1.000 | 53.9% |
| Random forest | -0.10% | 0.526 | 54.8% |
| Gradient boosting | -25.30% | 1.000 | 51.5% |
| Neural network | -1014.25% | 0.996 | 47.4% |
| ARIMA(p,1,0) | +0.42% | 0.224 | 57.6% |
| Momentum rule | -0.35% | 0.778 | 50.8% |
| Ensemble | -12.33% | 0.989 | 55.0% |

Rule (ensemble R² > 0 and DM p < 0.0167): **fail** (R² -12.33%, p 0.989).

## 21 trading days

| Model | Out-of-sample R² | DM p | Hit rate |
|---|---|---|---|
| Historical mean | +0.00% |  | 68.7% |
| Ridge regression | -315.69% | 0.999 | 58.6% |
| Random forest | -5.91% | 0.935 | 58.9% |
| Gradient boosting | -79.20% | 1.000 | 49.4% |
| Neural network | -406.64% | 1.000 | 51.3% |
| ARIMA(p,1,0) | +0.20% | 0.383 | 68.7% |
| Momentum rule | -2.35% | 0.937 | 58.3% |
| Ensemble | -47.70% | 1.000 | 55.7% |

Rule (ensemble R² > 0 and DM p < 0.0167): **fail** (R² -47.70%, p 1.000).

## 63 trading days

| Model | Out-of-sample R² | DM p | Hit rate |
|---|---|---|---|
| Historical mean | +0.00% |  | 75.8% |
| Ridge regression | -1135.65% | 0.953 | 64.8% |
| Random forest | -23.73% | 0.993 | 63.0% |
| Gradient boosting | -74.28% | 0.999 | 58.7% |
| Neural network | -1061.93% | 0.916 | 56.1% |
| ARIMA(p,1,0) | +0.97% | 0.332 | 75.8% |
| Momentum rule | -8.03% | 0.985 | 64.1% |
| Ensemble | -107.81% | 0.972 | 62.0% |

Rule (ensemble R² > 0 and DM p < 0.0167): **fail** (R² -107.81%, p 0.972).

## Verdict

No horizon passes: point-in-time macro data does not make SPY forecastable beyond the historical mean either.

