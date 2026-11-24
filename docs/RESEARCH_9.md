# Research report 9: multi-asset strategies

Generated 2026-11-24 by `python -m alphaforge.multiasset`. Rules committed before the run: [PREREGISTRATION_9.md](PREREGISTRATION_9.md).

16 ETFs, from 2005, monthly rebalancing, 3 bp per unit of turnover, cash at T-bills.

| Strategy | CAGR | Vol | Sharpe | Max DD | Worst year | Global financial crisis | 2011 euro crisis | Q4 2018 selloff | COVID crash | 2022 rates shock |
|---|---|---|---|---|---|---|---|---|---|---|
| Trend following (TSMOM, candidate) | 5.1% | 7.2% | 0.48 | -14.8% | -8.1% | +10.4% | +2.8% | -10.7% | -1.3% | -0.5% |
| Risk parity | 5.5% | 9.3% | 0.43 | -32.1% | -14.2% | -24.0% | -4.0% | -8.3% | -17.3% | -12.3% |
| Dual momentum | 8.3% | 15.8% | 0.47 | -33.7% | -16.6% | -0.9% | -14.9% | -18.9% | -33.4% | -16.6% |
| 60/40 (SPY / IEF) | 7.9% | 10.7% | 0.60 | -32.2% | -17.7% | -31.9% | -4.6% | -10.3% | -18.4% | -16.6% |
| Permanent portfolio | 6.9% | 7.5% | 0.70 | -18.7% | -13.8% | -3.9% | +5.8% | -1.9% | -5.8% | -13.8% |
| Equal weight, all ETFs | 6.0% | 9.0% | 0.49 | -27.7% | -10.9% | -19.9% | -4.2% | -5.5% | -15.9% | -10.8% |
| S&P 500 (SPY) | 10.5% | 18.9% | 0.53 | -55.2% | -36.8% | -54.8% | -13.8% | -18.9% | -33.4% | -18.2% |
| 50% S&P 500 + 50% trend following | 8.1% | 10.9% | 0.61 | -28.9% | -15.5% | -27.7% | -5.7% | -14.8% | -17.9% | -9.2% |

## Rules for trend following

| Rule | Result | Evidence |
|---|---|---|
| 1. Risk-adjusted | **fail** | Sharpe 0.48 vs SPY 0.53, 60/40 0.60 |
| 2. Crisis protection | **fail** | Global financial crisis +10.4%, 2011 euro crisis +2.8%, Q4 2018 selloff -10.7%, COVID crash -1.3%, 2022 rates shock -0.5% |
| 3. Diversifying | pass | monthly correlation with SPY 0.37 |
| 4. Better together | pass | 50/50: Sharpe 0.61 vs 0.53, max drawdown -28.9% vs -55.2% |
| 5. Stable | pass | 2005–12 +0.74, 2013–19 +0.27, 2020–now +0.33 |

## Verdict

Trend following does not pass every rule; nothing changes.

