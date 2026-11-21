# Pre-registered test 5: maximum diversification, a VaR limit, and stress de-risking

Written and committed **before** any of these was run (see this file's git history). Code: `alphaforge/test5.py`;
output: [RESEARCH_5.md](RESEARCH_5.md).

## Why

Four tests found no edge in forecasting returns. These three candidates from the Lab don't need one: they change
how risk is spread and limited, so they are judged on losses avoided at no real cost in return, not on beating
the market.

## Candidates (each against the current live strategy: momentum, two-week swap, optimizer, GARCH volatility)

| | Change | Specification (fixed now) |
|---|---|---|
| C5 | **Maximum-diversification weighting** | At each month-end, weights that maximize w'σ / √(w'Σw) over all 30 names (Choueifaty & Coignard 2008), long-only, each at most 10%, with Σ from GARCH volatilities and the 252-day correlation shrunk 30% to the identity; then the same 12% volatility target, sector and beta limits. No momentum selection and no swap (both need a forecast). |
| C6 | **Daily VaR limit** | Each day, the book's 99% one-day VaR = 2.326 × its GARCH volatility (GARCH fitted on the book's own returns at today's weights, refitted monthly). If it exceeds 3% of NAV, the whole book is scaled down to meet 3%. The scale is only changed when it moves by more than 10 percentage points, to avoid daily churn. |
| C7 | **Stress de-risking** | Stress = VIX above VIX3M, or SPY's GARCH volatility in its top 10% of the prior 10 years (the Lab's rule). In Stress the book is held at 50% of its weights; it returns to 100% after 5 consecutive days out of Stress. |

C6 and C7 act on the day after the signal, pay the same 7 bp per unit of turnover, and the freed cash earns T-bills.

## Rules

**For each candidate on the 30 names (2015 on, net of costs), all of:**
1. maximum drawdown at least 2 percentage points smaller than the current strategy's;
2. Sharpe ratio no more than 0.05 below the current one;
3. Sharpe ratio from 2020 on no more than 0.05 below the current one's from 2020 on (so the result isn't only
   pre-2020).

C6 and C7 also: turnover up by no more than 25%.

**C5 must also pass on a point-in-time universe**, so it doesn't rest on 30 hindsight-picked names: each month,
the 100 S&P 500 members with the highest 63-day dollar volume *at that date* (test 2's data). There, maximum
diversification is compared with the current signal (momentum, top 20% of those 100, equal weight) by rules
1 and 2, monthly, with the same costs.

**Combination:** the adopted candidates run together must also meet rules 1–3 against the current strategy. If
they don't, only the single candidate with the largest drawdown reduction goes live.

## What a pass means

Smaller losses at about the same return: not an edge. Three more configurations are tried here (36 in the
project so far). Anything adopted is switched on in `live.json` and documented; any one of them can be turned
off with one line.
