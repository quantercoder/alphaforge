# Research report

Generated 2026-10-03 by `python -m alphaforge.research`. Live configuration: `{"mode": "long_only", "target_vol": 0.12, "max_weight": 0.1, "max_leverage": 1.0, "swap_every": 10, "swap_count": 2, "factor_weights": {"momentum": 1.0, "reversal": 0.0, "low_vol": 0.0, "quality_trend": 0.0}, "max_sector": 0.4, "max_beta": 1.2, "turnover_penalty": 0.001}`.

**Read every number here as an upper bound.** Each universe is today's membership projected backward (survivorship bias), and this report itself is one more trial.

## 1. Each factor on its own

Monthly cross-sectional rank IC (Spearman correlation between the factor z-score and the next *h* days' return) on the 30-stock universe. t-stat = mean / sd × √n. |t| above about 2 is the usual bar.

| Factor | IC 5d | IC 21d (t) | IC 63d (t) | Top-third turnover / month |
|---|---|---|---|---|
| momentum | +0.022 | +0.035 (+1.3) | +0.057 (+2.2) | 19% |
| reversal | +0.008 | -0.000 (-0.0) | -0.006 (-0.2) | 64% |
| low_vol | -0.097 | -0.087 (-2.9) | -0.138 (-4.7) | 18% |
| quality_trend | -0.000 | +0.012 (+0.5) | +0.021 (+0.9) | 27% |

## 2. Live strategy against benchmarks

From 2015-02-02, net of costs; Sharpe is excess of T-bills, ± one standard error.

| Series | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Live strategy (30 names) | 18.8% | 15.1% | 1.08 ± 0.37 | -21.7% |
| Same, without the 2-week swap | 19.1% | 15.1% | 1.10 ± 0.37 | -21.8% |
| Old 4-factor blend (replaced in October 2026) | 18.8% | 15.4% | 1.06 ± 0.37 | -22.8% |
| Equal weight, same 30 names | 22.5% | 17.8% | 1.11 ± 0.37 | -29.4% |
| SPY | 14.2% | 17.5% | 0.73 ± 0.33 | -33.7% |

Against the equal-weight portfolio of the same names, the strategy's beta is 0.72 and its annual alpha is +2.1%. That alpha is what the factors add beyond simply owning these winners.

## 3. Walk-forward

Grid of 20 settings: 5 factor-weight presets × swap on/off × 10% or 15% position cap. Each calendar year from 2018 is traded with the setting that had the best Sharpe on all earlier years.

| Year | Setting chosen (preset, swap days, cap) | Train Sharpe | Year return |
|---|---|---|---|
| 2018 | equal 25 each, 0, 15% | 1.62 | +4.3% |
| 2019 | equal 25 each, 10, 10% | 1.23 | +20.9% |
| 2020 | equal 25 each, 10, 10% | 1.28 | +11.8% |
| 2021 | momentum only, 0, 15% | 1.10 | +22.3% |
| 2022 | momentum only, 0, 15% | 1.15 | +4.4% |
| 2023 | momentum only, 0, 15% | 1.04 | +27.7% |
| 2024 | momentum only, 0, 15% | 1.09 | +34.1% |
| 2025 | momentum only, 0, 15% | 1.15 | +11.7% |
| 2026 | momentum only, 0, 15% | 1.09 | +23.6% |

| | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Walk-forward, out of sample (2018 on) | 18.0% | 15.8% | 0.96 ± 0.41 | -23.8% |
| Best setting chosen with hindsight: momentum only, 0, 15% | 18.8% | 15.5% | 1.02 ± 0.42 | -21.1% |

## 4. Deflated Sharpe ratio

Across the 20 trials, full-period Sharpe ratios range from 0.79 to 1.14. With that many tries, the best Sharpe expected from luck alone is about **0.20**. The probability that the best setting's true Sharpe is above zero, after correcting for the number of trials and for skew and fat tails, is **99.9%** (deflated Sharpe ratio; 95% is the usual bar).

That clears the bar, but zero is a low bar: almost any long-only stock portfolio from 2015 to 2026 does. The harder test is whether a setting beats **holding the same 30 names in equal weight**. On daily returns in excess of the equal-weight portfolio:

| Setting | Information ratio vs equal weight | t-stat |
|---|---|---|
| momentum only, swap 0, cap 15% | -0.24 | -0.8 |
| momentum only, swap 10, cap 15% | -0.25 | -0.9 |
| no reversal 50/0/25/25, swap 0, cap 15% | -0.31 | -1.1 |
| no reversal 50/0/25/25, swap 10, cap 15% | -0.33 | -1.1 |
| momentum only, swap 0, cap 10% | -0.34 | -1.1 |
| **live setting** (momentum only, swap 10, cap 10%) | -0.34 | -1.2 |

Corrected for 20 trials, the probability that even the best setting truly beats equal weight is **2%**. Below 95%, the honest reading is: **no demonstrated edge over equal weight**; the factors mostly trade return for lower volatility and drawdown.

## 5. Breadth: 100 names instead of 30

| Universe | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| S&P 100 (98 names with full history) | 14.6% | 15.7% | 0.82 ± 0.34 | -25.7% |
| 30 mega caps (live) | 18.8% | 15.1% | 1.08 ± 0.37 | -21.7% |

Wider universes need a point-in-time constituent list (Norgate, Sharadar or CRSP) before the comparison means much; today's S&P 100 is just as survivorship-biased as today's top 30.

## 7. Pre-registered edge test

The rules were committed before this test ran ([PREREGISTRATION.md](PREREGISTRATION.md)). Candidate: momentum only (trend quality's IC t-stat was +0.5 at 21 days and +0.9 at 63 days, under the 2.0 needed to join). Benchmark: equal weight of the same names.

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | pass | IC 21d +0.035 (t +1.3), 63d +0.057 (t +2.2); S&P 100 63d +0.014 (t +0.7) |
| 2. Edge vs equal weight | **fail** | IR -0.34 over 11.6 years, t = -1.2 |
| 3. Deflated | **fail** | 1% after 22 trials (luck alone gives IR ≈ +0.35) |
| 4. Stability | **fail** | 2015–17 -0.40, 2018–20 -0.91, 2021–23 -0.05, 2024–26 +0.12 |
| 5. Breadth | **fail** | S&P 100 IR vs its equal weight -0.15 |
| 6. Survivorship-free | not run | not run: needs point-in-time data with delisted stocks (Norgate, Sharadar, CRSP) |

| Series | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Candidate | 18.9% | 15.3% | 1.08 ± 0.37 | -21.2% |
| Equal weight, same 30 names | 22.5% | 17.8% | 1.11 ± 0.37 | -29.4% |

Supplementary, not one of the rules: the candidate holds less market than equal weight (beta 0.71 against it), which costs return in a rising market. Adjusted for that, its alpha over equal weight is +2.3% a year (t = +0.9). This doesn't change the verdict.

**Verdict: no demonstrated edge.** At least one rule failed. On this evidence the strategy is not suitable for outside money: it has not shown that it beats holding the same stocks in equal weight by more than luck and the number of tries explain.

## 8. Constrained construction (optimizer)

Risk control, not a source of return: the settings (max_sector 0.4, max_beta 1.2, turnover_penalty 0.001) were fixed before this ran and were not tuned on it. At each rebalance the optimizer finds the long-only portfolio closest to the simple target (in tracking variance) that keeps every sector at or under 40% and beta to the equal-weighted universe at or under 1.2, with a turnover penalty ([MATH.md §6.4](MATH.md#64-constrained-construction-optimizer)).

| Construction | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Momentum, simple construction | 18.9% | 15.3% | 1.08 ± 0.37 | -21.2% |
| Momentum, optimizer | 18.8% | 15.1% | 1.08 ± 0.37 | -21.7% |

| Construction | Largest sector, average | Largest sector, worst | Rebalances over 40% | Turnover / year | IR vs equal weight |
|---|---|---|---|---|---|
| Momentum, simple construction | 29% | 53% | 10% | 5.7× | -0.34 |
| Momentum, optimizer | 28% | 43% | 2% | 3.6× | -0.37 |

With the optimizer every rebalance ends at or under the 40% sector cap. The remaining breaches are swap days: prices moved a sector above 40% between rebalances, and a swap refuses to add to a full sector but doesn't trim it. The next month-end rebalance brings it back.

It changes where the risk sits, not whether there is an edge: §7's verdict applies to both.

## 6. Crypto trend sleeve

From 2019-05-04, 8 coins, 365-day annualization, no risk-free rate.

| Series | CAGR | Vol | Sharpe | Max DD |
|---|---|---|---|---|
| Trend sleeve (live settings) | 32.7% | 32.2% | 1.04 ± 0.46 | -47.6% |
| Bitcoin buy and hold | 43.6% | 61.0% | 0.90 ± 0.44 | -76.6% |
| Equal weight, same coins | 69.4% | 79.9% | 1.06 ± 0.46 | -81.3% |

Trend-following's case in crypto is drawdown control, not a higher Sharpe ratio.

