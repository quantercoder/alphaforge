# Research report 5: maximum diversification, VaR limit, stress de-risking

Generated 2026-11-21 by `python -m alphaforge.test5`. Rules committed before the run: [PREREGISTRATION_5.md](PREREGISTRATION_5.md). These are risk controls: a pass means smaller losses at about the same return, not an edge.

## The 30 names, 2015 on, net of costs

| Configuration | Sharpe | Sharpe from 2020 | CAGR | Vol | Max DD | Worst month | Turnover / yr |
|---|---|---|---|---|---|---|---|
| Current (momentum, swap, optimizer, GARCH) | 1.11 | 0.87 | 18.3% | 14.1% | -17.8% | -10.3% | 3.0× |
| C5 maximum diversification | 1.00 | 0.66 | 16.2% | 13.8% | -24.3% | -7.4% | 1.0× |
| C6 daily VaR limit (3%) | 1.17 | 0.93 | 18.1% | 13.2% | -17.3% | -9.7% | 3.3× |
| C7 stress de-risking (50%) | 1.13 | 0.85 | 15.3% | 11.3% | -14.0% | -8.5% | 5.3× |

The VaR limit was binding on 57% of days; the stress rule was on for 15% of days.

## Point-in-time check for C5 (100 most-traded S&P 500 members each month, 2014 on)

| Weighting | Sharpe | CAGR | Max DD |
|---|---|---|---|
| Maximum diversification | 0.76 | 10.1% | -17.9% |
| Momentum top 20% (current signal) | 0.68 | 14.4% | -43.7% |

## Rules

**C5: fail**

| Rule | Result | Evidence |
|---|---|---|
| Max drawdown at least 2 points smaller | **fail** | -17.8% → -24.3% |
| Sharpe within 0.05 | **fail** | 1.11 → 1.00 |
| Sharpe from 2020 within 0.05 | **fail** | 0.87 → 0.66 |

**C6: fail**

| Rule | Result | Evidence |
|---|---|---|
| Max drawdown at least 2 points smaller | **fail** | -17.8% → -17.3% |
| Sharpe within 0.05 | pass | 1.11 → 1.17 |
| Sharpe from 2020 within 0.05 | pass | 0.87 → 0.93 |
| Turnover up at most 25% | pass | 3.0× → 3.3× a year |

**C7: fail**

| Rule | Result | Evidence |
|---|---|---|
| Max drawdown at least 2 points smaller | pass | -17.8% → -14.0% |
| Sharpe within 0.05 | pass | 1.11 → 1.13 |
| Sharpe from 2020 within 0.05 | pass | 0.87 → 0.85 |
| Turnover up at most 25% | **fail** | 3.0× → 5.3× a year |

**C5 point-in-time: pass**

| Rule | Result | Evidence |
|---|---|---|
| Max drawdown at least 2 points smaller | pass | -43.7% → -17.9% |
| Sharpe within 0.05 | pass | 0.68 → 0.76 |

## Decision

Adopt: nothing; the live strategy is unchanged.

