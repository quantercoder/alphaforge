# Pre-registered edge test: momentum only

Written and committed **before** the test was run (see this file's git history), so the result can't
shape the rules. The code that applies it is `research.edge_test`; its output is
[RESEARCH.md §7](RESEARCH.md#7-pre-registered-edge-test).

## Why this candidate

The dashboard's IC table showed the four-factor blend has no predictive power (IC ≈ 0.01, t ≈ 0.6):
low volatility predicts *backwards* on these 30 names (t ≈ −4.9), reversal is zero, trend quality is
weak (t ≈ 1.2 at 63 days), and momentum is the only factor near significance (t ≈ 2.2). Momentum also
has decades of independent evidence (Jegadeesh & Titman 1993; Asness, Moskowitz & Pedersen 2013), so it
doesn't rest on this sample alone. Low volatility is dropped, not flipped: "buy high volatility" would
fit the survivorship bias of a universe made of today's winners.

Choosing the candidate after looking at the IC table is itself data snooping. That's why the test
below deflates for every configuration tried so far and is judged against equal weight, not zero.

## Candidate

`factor_weights = {momentum: 1}`, everything else as in `live.json` (long-only top 30%, rank-weighted,
10% cap, 12% vol target, 2-week swap of the worst 2). Trend quality is added as a second signal only if
its own rank IC has t ≥ 2.0 at 21 or 63 days.

## Benchmark

Equal weight of the same 30 names, rebalanced monthly, same costs. Beating SPY or zero is not the bar:
almost any portfolio of today's mega caps did from 2015 to 2026.

## Rules (all must pass)

| # | Test | Pass if |
|---|---|---|
| 1 | Signal | momentum's monthly rank IC is positive at 21 and 63 days on the 30 names with t ≥ 2.0 at one of them, and positive at 63 days on the S&P 100 |
| 2 | Edge vs equal weight | information ratio of daily returns in excess of equal weight, t = IR × √years ≥ 2.0 |
| 3 | Deflated | deflated probability that the candidate's true IR vs equal weight is above zero, counting every configuration tried (the 20-setting grid plus the candidates), ≥ 95% |
| 4 | Stability | IR vs equal weight positive in at least 3 of 4 periods: 2015–17, 2018–20, 2021–23, 2024–26 |
| 5 | Breadth | IR vs equal weight positive on the S&P 100 universe |
| 6 | Survivorship-free confirmation | rules 2–4 hold on a point-in-time universe including delisted stocks |

**Rule 6 can't be run with free data** (Yahoo has no delisted stocks and no historical index membership).
So even if rules 1–5 pass, the most this test can say is *provisionally demonstrated, pending
point-in-time data*. If any of rules 1–5 fails, the verdict is **no demonstrated edge**, and the strategy is
not suitable for outside money in its current form, whatever its Sharpe ratio.

## What happens either way

The live paper strategy switches to the candidate regardless, because the blend is demonstrably worse
(it includes a signal that predicts backwards). That is a decision about the paper account, not a claim
of an edge.
