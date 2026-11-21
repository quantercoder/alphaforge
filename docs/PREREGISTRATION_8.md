# Pre-registered test 8: beating the S&P 500 by taking more risk, with control

Written and committed **before** the test ran (see this file's git history). Code: `alphaforge/test8.py`;
output: [RESEARCH_8.md](RESEARCH_8.md).

## Why

Seven tests found no forecasting edge. The remaining way to earn more than the index is to **carry more market risk
than it**, and to manage that risk so a crash doesn't wipe the gain out. This is not an edge, and the page says so:
it is a choice to take more risk, made systematically.

## Candidates (trading SPY itself: an index fund, so no survivorship bias)

Each decides at a close and trades at the next close. It holds SPY with weight $w_t$, borrows when $w_t > 1$ at
T-bills + 1%, and earns T-bills on cash. Costs are 2 bp per unit of turnover. $w$ only changes when the target moves
by more than 0.10, to avoid daily churn.

| | Name | Target weight in SPY |
|---|---|---|
| R1 | **Risk-targeted** | $w = \min(1.5,\ 0.20 / \sigma^{\text{GARCH}}_t)$: aim for 20% annual volatility (the S&P's own is about 17–19%), at most 1.5× |
| R2 | **Risk-targeted with trend filter** | R1's weight while SPY is above its 200-day average; below it, half of R1's weight, at most 1.0× |

$\sigma^{\text{GARCH}}_t$ is SPY's GARCH(1,1) volatility with parameters refitted every January on prior data only.

**Benchmark:** buying and holding SPY (total return, dividends reinvested).

**Period:** from January 1998 (the first date with three years of data for the GARCH fit) to the latest, which
includes 2000–02, 2008, 2020 and 2022.

## Rules (all must pass for a candidate)

1. **Higher return:** annual return (CAGR) above SPY's over the full period.
2. **Consistently:** above SPY's in at least 70% of all rolling 10-year windows (monthly steps).
3. **In each era:** CAGR above SPY's in at least 2 of 3 periods: 1998–2007, 2008–2015, 2016–latest.
4. **Not a worse crash:** maximum drawdown no deeper than SPY's own.
5. **Not just leverage:** Sharpe ratio (excess of T-bills) at least SPY's.

## Decision

If one candidate passes, it goes live on the **paper** account as the equity sleeve's strategy, trading SPY with up
to 1.5× margin. If both pass, R2 wins if its drawdown is smaller, else R1. If neither passes, nothing changes. Real
money remains your decision; the `live_money` switches are not touched. Trials: 2 more (45 in the project).
