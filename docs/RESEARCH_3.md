# Research report 3: fewer sells into dips, and GARCH volatility

Generated 2026-11-21 by `python -m alphaforge.improve`. Rules committed before the run: [PREREGISTRATION_3.md](PREREGISTRATION_3.md). None of these changes claims an edge (see [RESEARCH_PIT.md](RESEARCH_PIT.md)); they change how the book trades and how it forecasts risk.

## Stocks (30 names, 2015 on, net of costs)

| Configuration | Sharpe | CAGR | Vol | Max DD | Turnover / yr | Trade days / yr | Gap to 12% vol |
|---|---|---|---|---|---|---|---|
| Current (momentum, 2-week swap, optimizer) | 1.04 | 18.1% | 15.1% | -21.7% | 3.6× | 21 | 3.4% |
| C1 no swap | 1.06 | 18.4% | 15.1% | -21.8% | 3.3× | 12 | 3.4% |
| C2 rank buffer | 1.04 | 18.1% | 15.1% | -20.5% | 3.6× | 22 | 3.4% |
| C3 GARCH volatility | 1.08 | 17.9% | 14.2% | -17.3% | 3.3× | 20 | 2.8% |

## Point-in-time S&P 500 (momentum, top 20%)

| | Sharpe | Max DD | Turnover / yr |
|---|---|---|---|
| Current | 0.90 | -19.5% | 6.3× |
| C2 rank buffer (keep while top 40%) | 0.88 | -19.1% | 3.0× |

## Volatility forecasts (out of sample, 21 days ahead)

11,654 forecasts: 101 stocks at every month-end from 2016, each GARCH fitted on the prior 3 years only.

| Model | QLIKE (lower is better) | Mincer-Zarnowitz R² | 68% range coverage |
|---|---|---|---|
| 63-day sample (current) | 0.473 | 0.13 | 67% |
| GARCH(1,1) | 0.371 | 0.16 | 69% |

A well-calibrated 68% range contains the next month's move 68% of the time.

## Crypto (8 coins, 2019 on)

| | Sharpe | CAGR | Max DD | Turnover / yr | Trade days / yr |
|---|---|---|---|---|---|
| Current | 0.92 | 27.8% | -47.6% | 13.2× | 44 |
| C4 exit buffer (sell only when all three lookbacks are negative) | 0.69 | 19.6% | -55.6% | 11.3× | 46 |

## Rules

**C1: fail**

| Rule | Result | Evidence |
|---|---|---|
| Turnover down at least 15% | **fail** | 3.6× → 3.3× a year (-10%) |
| Sharpe within 0.05 | pass | 1.04 → 1.06 |
| Max drawdown within 2 points | pass | -21.7% → -21.8% |

**C2: fail**

| Rule | Result | Evidence |
|---|---|---|
| Turnover down at least 15% | **fail** | 3.6× → 3.6× a year (+0%) |
| Sharpe within 0.05 | pass | 1.04 → 1.04 |
| Max drawdown within 2 points | pass | -21.7% → -20.5% |

**C2 point-in-time: pass**

| Rule | Result | Evidence |
|---|---|---|
| Turnover down at least 15% | pass | 6.3× → 3.0× a year (-52%) |
| Sharpe within 0.05 | pass | 0.90 → 0.88 |
| Max drawdown within 2 points | pass | -19.5% → -19.1% |

**C3: pass**

| Rule | Result | Evidence |
|---|---|---|
| Lower QLIKE in aggregate | pass | 0.473 → 0.371 |
| Lower QLIKE for at least 70% of stocks | pass | 96% of 101 stocks |
| Closer to the 12% volatility target | pass | average gap 3.4% → 2.8% |
| Sharpe within 0.05 | pass | 1.04 → 1.08 |

**C4: fail**

| Rule | Result | Evidence |
|---|---|---|
| Turnover down at least 15% | **fail** | 13.2× → 11.3× a year (-14%) |
| Sharpe within 0.05 | **fail** | 0.92 → 0.69 |
| Max drawdown within 2 points | **fail** | -47.6% → -55.6% |

## Decision

Stocks: adopt C3. Crypto: no change.

