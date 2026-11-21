# Pre-registered test 2: three signals on a point-in-time S&P 500

Written and committed **before** any of these signals was run on this data (see this file's git
history). The code that applies it is `alphaforge/pit.py`; its output is
[RESEARCH_PIT.md](RESEARCH_PIT.md).

## Why

The first test ([PREREGISTRATION.md](PREREGISTRATION.md)) found no demonstrated edge for momentum on
30 of today's mega caps. Two things made that test weak: the universe was chosen with hindsight
(today's winners), and 30 names is too few to measure a cross-sectional signal. This test fixes both
as far as free data allows.

## Universe and data

- **Members:** at each month-end, the stocks that were in the S&P 500 *on that date*, from the free
  historical membership list `fja05680/sp500` (`sp500_ticker_start_end.csv`, MIT licence).
- **Prices:** Yahoo daily adjusted closes from 2010. A member with no Yahoo prices at a month-end is
  left out of both the strategy and the benchmark that month. Coverage (share of member-months with
  prices) is reported.
- **Test period:** month-ends from January 2012 (so every signal has its full history) to the latest.

## Candidates (each tested on its own; nothing else is tried)

| | Signal at month-end *t* | Evidence outside this data |
|---|---|---|
| A | **Momentum 12-1:** return from *t*−12 to *t*−1 months | Jegadeesh & Titman (1993) |
| B | **Residual momentum:** sum of the last 12-to-1 months' residuals from a regression of the stock's monthly return on the equal-weighted universe over the prior 36 months (at least 24), divided by the residuals' standard deviation | Blitz, Huij & Martens (2011) |
| C | **52-week high:** price at *t* ÷ highest close over the prior 252 trading days | George & Hwang (2004) |

## Portfolio and benchmark

- **Strategy:** each month-end, buy the top 20% of members by the signal, equal weight, hold one month.
  Costs 7 bp per unit of one-way turnover, as in the backtest.
- **Benchmark:** equal weight of all members with prices, rebalanced monthly, same costs.
- Returns are monthly. Information ratio (IR) = mean ÷ standard deviation of monthly active return × √12;
  t = IR × √years.

## Rules (all must pass for a candidate)

| # | Test | Pass if |
|---|---|---|
| 1 | Signal | monthly rank IC against the next month's return is positive with t ≥ 2.0 |
| 2 | Edge vs equal weight | t of the active return ≥ 2.0 |
| 3 | Deflated | deflated probability that the true IR is above zero ≥ 95%, counting every configuration tried in this project: 22 before this test plus these 3 = **25** |
| 4 | Stability | IR positive in at least 3 of 4 periods: 2012–15, 2016–19, 2020–22, 2023–latest |
| 5 | Breadth | IR positive in both halves of the universe, split each month by median 63-day dollar volume |
| 6 | Coverage | at least 90% of member-months have prices |

## Decision

- If exactly one candidate passes, it is **provisionally demonstrated** (still pending 6–12 months of paper
  trading), and it becomes the live signal.
- If more than one passes, the one with the highest deflated probability wins. Nothing is combined.
- If none passes, the verdict is **no demonstrated edge** and the live strategy stays as it is.

## Known limits, stated in advance

- Yahoo lacks prices for many delisted stocks, so the worst outcomes (bankruptcies) are partly missing.
  Because missing names leave both the strategy and the benchmark, the bias is smaller than with a
  hindsight universe, but not zero.
- Tickers reused by a different company can attach the wrong prices to a former member.
- No sector data for former members, so no sector-neutral versions are tested.
