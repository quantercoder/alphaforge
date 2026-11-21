# Research report 9: multi-asset strategies

Generated 2026-11-21 by `python -m alphaforge.multiasset`. Rules committed before the run: [PREREGISTRATION_9.md](PREREGISTRATION_9.md).

16 ETFs, from 2005, monthly rebalancing, 3 bp per unit of turnover, cash at T-bills.

| Strategy | CAGR | Vol | Sharpe | Max DD | Worst year | Global financial crisis | 2011 euro crisis | Q4 2018 selloff | COVID crash | 2022 rates shock |
|---|---|---|---|---|---|---|---|---|---|---|
| Trend following (TSMOM, candidate) | 5.1% | 7.2% | 0.48 | -14.8% | -8.1% | +10.4% | +2.8% | -10.7% | -1.3% | -0.5% |
| Risk parity | 5.5% | 9.3% | 0.43 | -32.1% | -14.2% | -24.0% | -4.0% | -8.3% | -17.3% | -12.3% |
| Dual momentum | 8.1% | 15.8% | 0.46 | -33.7% | -16.6% | -0.9% | -14.9% | -18.9% | -33.4% | -16.6% |
| 60/40 (SPY / IEF) | 7.8% | 10.6% | 0.59 | -32.2% | -17.7% | -31.9% | -4.6% | -10.3% | -18.4% | -16.6% |
| Permanent portfolio | 6.9% | 7.4% | 0.69 | -18.7% | -13.8% | -3.9% | +5.8% | -1.9% | -5.8% | -13.8% |
| Equal weight, all ETFs | 5.9% | 9.0% | 0.49 | -27.7% | -10.9% | -19.9% | -4.2% | -5.5% | -15.9% | -10.8% |
| S&P 500 (SPY) | 10.3% | 18.9% | 0.52 | -55.2% | -36.8% | -54.8% | -13.8% | -18.9% | -33.4% | -18.2% |
| 50% S&P 500 + 50% trend following | 8.0% | 10.8% | 0.60 | -28.9% | -15.5% | -27.7% | -5.7% | -14.8% | -17.9% | -9.2% |

## Rules for trend following

| Rule | Result | Evidence |
|---|---|---|
| 1. Risk-adjusted | **fail** | Sharpe 0.48 vs SPY 0.52, 60/40 0.59 |
| 2. Crisis protection | **fail** | Global financial crisis +10.4%, 2011 euro crisis +2.8%, Q4 2018 selloff -10.7%, COVID crash -1.3%, 2022 rates shock -0.5% |
| 3. Diversifying | pass | monthly correlation with SPY 0.38 |
| 4. Better together | pass | 50/50: Sharpe 0.60 vs 0.52, max drawdown -28.9% vs -55.2% |
| 5. Stable | pass | 2005–12 +0.74, 2013–19 +0.27, 2020–now +0.32 |

## Verdict

Trend following does not pass every rule; nothing changes.

