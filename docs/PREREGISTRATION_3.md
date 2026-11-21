# Pre-registered test 3: fewer sells into dips, and a real volatility model

Written and committed **before** any of these changes was run (see this file's git history). Code:
`alphaforge/improve.py`; output: [RESEARCH_3.md](RESEARCH_3.md).

## Why

Two pre-registered tests found no edge in the stock signals, so no change here claims one. What can
still improve is *how* the book trades and *how well it forecasts risk*:

- In seven weeks of paper trading, every stock sale came from the two-week swap, which by design sells
  the holdings that fell most. The crypto trend filter sold step by step into a decline and has been in
  cash since 16 November. Selling right after a drop locks in losses whenever the drop reverses.
- Returns are close to unpredictable, but **volatility is predictable**: it clusters (Engle 1982;
  Bollerslev 1986). The book's volatility target currently uses a plain 63-day sample.

## Changes (each tested on its own against the current live configuration)

| | Change | Technique |
|---|---|---|
| C1 | No two-week swap (`swap_every` 0): hold until the month-end rebalance | removes the "sell the biggest losers" rule |
| C2 | Rank buffer: buy into the top 30% by score, but keep a held stock while it stays in the top 50% (`hold_buffer` 0.5) | hysteresis / no-trade band (Novy-Marx & Velikov 2016) |
| C3 | GARCH(1,1) volatility per stock, fitted by maximum likelihood on the prior 3 years, with the 252-day correlation, replaces the 63-day sample covariance in the volatility target (`vol_model` "garch") | Bollerslev (1986); constant-correlation covariance (Bollerslev 1990) |
| C4 | Crypto exit buffer: buy a coin when its trend score is above 0, sell only when it falls to −1/3 or below, so one short-term dip doesn't sell (`trend_exit` −1/3) | hysteresis |

## Rules

**C1, C2, C4 (trading changes):** adopted only if, over the full backtest,
1. turnover per year falls by at least 15%,
2. the net Sharpe ratio is no more than 0.05 below the current one, and
3. the maximum drawdown is no more than 2 percentage points worse.

C2 must also pass 1–3 on the point-in-time S&P 500 of test 2 (momentum, top 20% entry, keep while in the
top 40%), so the result doesn't rest on 30 hindsight-picked names.

**C3 (forecasting model):** adopted only if
1. out of sample (each month-end from 2016, forecasting the next 21 days' volatility of every stock on the
   terminal with at least 4 years of prices), GARCH's average QLIKE loss is lower than the 63-day sample's
   in aggregate **and** for at least 70% of the stocks,
2. in the backtest, the book's realized 63-day volatility stays closer to the 12% target (lower mean absolute
   gap), and
3. the net Sharpe ratio is no more than 0.05 below the current one.

QLIKE $= \frac{\sigma^2}{\hat\sigma^2} - \ln\frac{\sigma^2}{\hat\sigma^2} - 1$ with $\sigma^2$ the realized
variance (sum of squared daily returns) and $\hat\sigma^2$ the forecast; it is the standard loss for
comparing variance forecasts (Patton 2011). The Mincer-Zarnowitz $R^2$ and the 68% range coverage are
reported alongside.

**Combination:** the adopted changes are then run together, and the combination must also meet rules 2–3
of the trading changes against the current configuration. Otherwise only the single best adopted change goes
live.

## What this test cannot show

None of these changes adds predictive power for returns. A pass means fewer trades, fewer sales into dips,
or better risk forecasts at no measured cost. It does not mean an edge. Four more configurations are tried
here (29 in the project so far).
