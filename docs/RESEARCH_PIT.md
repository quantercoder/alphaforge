# Research report 2: point-in-time S&P 500

Generated 2026-11-21 by `python -m alphaforge.pit`. Rules committed before the run: [PREREGISTRATION_PIT.md](PREREGISTRATION_PIT.md).

Universe: S&P 500 members at each month-end, January 2012 to October 2026. 848 tickers were members at some point since 2010; Yahoo has prices for 645. **83.9%** of member-months are priced; for 0.0% the stock has a price at the month-end but none a month later (delisted or taken over mid-month), and that month's return is counted as 0 for both the strategy and the benchmark.

Strategy: top 20% by the signal, equal weight, rebalanced monthly. Benchmark: equal weight of all priced members. Both pay 7 bp per unit of turnover.

| Signal | CAGR | Vol | Max DD | Benchmark CAGR | Active / yr | IR | t |
|---|---|---|---|---|---|---|---|
| A. Momentum 12-1 | 13.4% | 15.4% | -19.5% | 13.0% | +0.4% | +0.05 | +0.2 |
| B. Residual momentum | 13.0% | 15.1% | -22.4% | 12.4% | +0.5% | +0.08 | +0.3 |
| C. 52-week high | 11.2% | 12.4% | -17.9% | 13.0% | -1.9% | -0.26 | -1.0 |

## A. Momentum 12-1

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC +0.003, t +0.2 over 178 months |
| 2. Edge vs equal weight | **fail** | IR +0.05, t +0.2 over 14.8 years |
| 3. Deflated | **fail** | 8% after 25 trials |
| 4. Stability | **fail** | 2012–15 +0.76, 2016–19 -0.30, 2020–22 -0.43, 2023–now +0.28 |
| 5. Breadth | **fail** | liquid +0.10, less liquid -0.05 |
| 6. Coverage | **fail** | 83.9% of member-months priced |

## B. Residual momentum

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC +0.000, t +0.0 over 166 months |
| 2. Edge vs equal weight | **fail** | IR +0.08, t +0.3 over 13.8 years |
| 3. Deflated | **fail** | 10% after 25 trials |
| 4. Stability | **fail** | 2012–15 +0.55, 2016–19 -0.47, 2020–22 -0.07, 2023–now +0.44 |
| 5. Breadth | **fail** | liquid +0.18, less liquid -0.04 |
| 6. Coverage | **fail** | 83.9% of member-months priced |

## C. 52-week high

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC -0.002, t -0.1 over 178 months |
| 2. Edge vs equal weight | **fail** | IR -0.26, t -1.0 over 14.8 years |
| 3. Deflated | **fail** | 0% after 25 trials |
| 4. Stability | **fail** | 2012–15 +0.11, 2016–19 -0.62, 2020–22 -0.24, 2023–now -0.29 |
| 5. Breadth | **fail** | liquid -0.29, less liquid -0.13 |
| 6. Coverage | **fail** | 83.9% of member-months priced |

## Verdict

**No demonstrated edge.** No candidate passes all six rules, so the live strategy stays as it is. The forecast screen on the terminal uses the candidate with the strongest IC and shows how weak that forecast is.

