# AlphaForge

**Terminal: [Equities](https://quantercoder.github.io/alphaforge/) · [Crypto](https://quantercoder.github.io/alphaforge/crypto.html)** · [Math model](docs/MATH.md) · [Research](docs/RESEARCH.md) · [Live trading](docs/LIVE_TRADING.md)

A multi-factor equity strategy and a separate trend-following crypto strategy, with a Bloomberg-style web terminal, a paper/live trading job and a Streamlit research dashboard. It follows the workflow a systematic equity desk uses: cross-sectional factor signals, risk-aware portfolio construction, and a backtest with execution lag, weight drift and transaction costs. The backtest is tested for look-ahead bias.

```bash
pip install -r requirements.txt
streamlit run app.py            # dashboard
python -m alphaforge --synthetic  # CLI, offline
python -m alphaforge --mode long_only --start 2015-01-01
pytest -q
python -m alphaforge.live         # one trading day (paper simulator by default)
python -m alphaforge.research     # factor ICs, benchmarks, walk-forward, deflated Sharpe -> docs/RESEARCH.md
```

## Terminal

Two static, keyboard-driven pages on GitHub Pages, one per sleeve, sharing `site/terminal.js` and `site/terminal.css`: **Equities** (`index.html`, reads `data.json`) and **Crypto** (`crypto.html`, reads `crypto.json`). Tabs at the top switch between them; both can be open at once.

- Command line with suggestions: type a ticker, part of a company or coin name ("apple", "ether"), or a function. Arrow keys and Enter pick, Tab completes. `PORT`, `SIG`, `RISK`, `BT`, `BLTR`, `MTH`, `ATTR`, `FACT`, `STRESS`, `LIQ`, `LIM`, `EXP`, `TCA`, `IC`, `PREV`, `DATA`, `AUD`, `EQUITY`, `CRYPTO` and `HELP` work as commands, and F1–F9 jump to panels.
- **Book with live P&L, the way Alpaca shows it:** quantity, average cost, value, today's P&L and unrealized P&L per position, with totals, for that sleeve only. With live prices on, every number updates tick by tick.
- Market strip (SPX, NDX, RTY, VIX, 10Y, DXY, gold, WTI, BTC, EURUSD), and a monitor of the S&P 100 plus the strategy's names, with All / Strategy / Live tabs, sparklines and candlestick charts. The strategy trades only its 30 names; the rest are watch-only (`"watchlist"` in `live.json`).
- Order blotter (times in New York, slippage of each fill against the signal price), signals, and a monthly returns grid.
- Risk for the sleeve: forecast vs realized volatility, parametric and historical VaR, beta, a stress test, sector exposure, each name's share of risk, distance to the drawdown halt, a labelled correlation map, and one line for the whole account.
- Backtest panel: growth and underwater charts against SPY (or Bitcoin), an equal-weight portfolio of the same names, and momentum alone, plus a comparison table with tracking error and information ratio.
- **Desk analytics** ([MATH.md §17](docs/MATH.md#17-desk-analytics)):
  - *Attribution:* the strategy's return split into market, sector, style factors, stock-specific, cash and costs by a factor risk model; also by sector and by stock. The parts add up exactly.
  - *Factor risk model:* an S&P 100 cross-sectional model (market + sectors + 4 styles); total and active risk split into market, sector, style and specific, and each position's share.
  - *Stress:* today's book replayed through the COVID crash, Q4 2018, 2022, Aug 2024 and Apr 2025 (crypto: 2021, LUNA, FTX...), plus factor shocks. *Liquidity:* days to exit at 10% of volume. *Limits:* every risk limit with its utilization and a traffic light.
  - *Book exposure:* held vs last target (drift) vs benchmark (active), by name and by sector, plus pending orders.
  - *TCA:* each fill's decision price, arrival price and fill price; slippage split into delay and impact; participation in volume; fill rate.
  - *Signals:* rank IC at 1, 5, 21 and 63 days (decay), signal correlation, crowding (comomentum) and capacity.
  - *Next trade:* what the next rebalance and swap would buy and sell on today's prices, with cost, turnover and limit checks, and an optional approval step.
  - *Data health:* price freshness, gaps, stale prices, suspicious jumps (corporate actions, bad ticks), reconciliation of positions to fills, cash + positions = equity, stuck orders, live feed age.
  - *Alerts & audit:* current limit breaches and failing checks, alerts from trading runs, an audit trail of every trading run (who, how, which commit, what it did), and the controls and permissions in force.

**Data.** A GitHub Actions job (`.github/workflows/terminal.yml`) refreshes delayed Yahoo data every 30 minutes during market hours. After each close it trades the paper account, commits `state/` and redeploys the page.

**Live prices.** Type `LIVE` or click the status chip, then paste an Alpaca paper-account API key. The equities page streams real-time trades from Alpaca's free IEX feed for up to 30 symbols; the crypto page streams every coin. Every stock you open is live tracked; opening a 31st drops the one you opened longest ago. `LIVE LIST` shows the tracked set, which is remembered in your browser. Your key stays in your browser and is never sent to GitHub.

## Pipeline

```
prices ─▶ factors ─▶ z-score + winsorize ─▶ blended alpha ─▶ weights ─▶ caps ─▶ vol target ─▶ backtest
```

| Stage | What it does | File |
|---|---|---|
| **Factors** | 12-1 momentum, 5-day reversal, 63-day low volatility, trend quality (net move / path length) | `signals.py` |
| **Normalization** | Cross-sectional z-score per day, winsorized at ±3σ, weighted blend re-standardized | `signals.py` |
| **Construction** | Dollar-neutral L/S (demeaned alpha) or long-only (top 30%, rank-weighted) | `portfolio.py` |
| **Risk** | Position cap with excess redistributed, ex-ante vol targeting on a shrunk 63-day covariance, gross leverage cap, hard per-name NAV limit | `portfolio.py` |
| **Optimizer** | Closest portfolio to the target with sector ≤ 40%, beta ≤ 1.2 and a turnover penalty; a dependency-free QP solver (ADMM, as in OSQP) | `portfolio.optimize`, `solve_qp` |
| **Execution** | Signal at close *t*, trade at close *t+1*. Weights drift with prices between rebalances, and costs (commission + slippage bps) are charged on the actual trade from drifted holdings | `backtest.py` |
| **Live** | Month-end signal from the same code path, whole-share order sizing, sells before buys, sim or Alpaca broker, drawdown halt | `live.py`, `broker.py` |
| **Analytics** | CAGR, Sharpe, Sortino, Calmar, max drawdown, historical VaR/CVaR, beta/alpha, turnover, cost drag, monthly table | `metrics.py` |
| **Desk analytics** | Factor risk model (S&P 100: market, sectors, styles, specific), exact P&L attribution, tracking error / IR, stress replay and factor shocks, liquidity, limits, TCA, signal IC / decay / crowding / capacity, data health, next-trade preview ([MATH.md §17](docs/MATH.md#17-desk-analytics)) | `analytics.py`, `terminal.py` |

## Dashboard

- **KPI row**: CAGR, Sharpe, max drawdown, volatility, beta, turnover
- **Performance**: log equity curve vs SPY, underwater curve, 6-month rolling Sharpe
- **Returns**: monthly heatmap, daily return distribution with VaR, calendar-year bars
- **Positions**: current long/short book, gross and net exposure, turnover per rebalance
- **Signals**: the latest factor z-scores, blended alpha and resulting weights for each name
- **Statistics**: full metric table vs benchmark, CSV export

Every parameter (universe, mode, rebalance frequency, vol target, caps, costs, factor weights) is a sidebar control. If Yahoo is unreachable, the **Synthetic** source runs fully offline.

## Honest results

From [docs/RESEARCH.md](docs/RESEARCH.md) (2015 to 2026, net of costs, Sharpe excess of T-bills, ± one standard error):

| Series | CAGR | Sharpe | Max DD |
|---|---|---|---|
| Live equity strategy (momentum + optimizer) | 18.8% | 1.08 ± 0.37 | -21.7% |
| Old 4-factor blend (replaced) | 18.8% | 1.06 ± 0.37 | -22.8% |
| Same, walk-forward out of sample (2018 on) | 18.0% | 0.96 ± 0.41 | -23.8% |
| **Equal weight, same 30 names** | **22.5%** | **1.11 ± 0.37** | -29.4% |
| SPY | 14.2% | 0.73 ± 0.33 | -33.7% |
| Crypto trend sleeve (from 2019) | 32.7% | 1.04 ± 0.46 | -47.6% |
| Bitcoin buy and hold | 43.6% | 0.90 ± 0.44 | -76.6% |

What that means:

- **A pre-registered test said no.** The rules for calling momentum's edge "demonstrated" were committed before running it ([PREREGISTRATION.md](docs/PREREGISTRATION.md)). It failed four of five: information ratio against equal weight $-0.34$ ($t = -1.2$), 1% probability after deflating for 22 trials, negative in 3 of 4 periods and on the S&P 100 ([RESEARCH.md §7](docs/RESEARCH.md#7-pre-registered-edge-test)). **It is not suitable for outside money in this form.**
- **No demonstrated edge over equal weight.** Holding the same 30 names equally beat every one of 20 settings tested on raw return; corrected for the number of trials, the chance the best setting truly beats it is about 2%. Adjusted for its lower beta the strategy adds about 2% a year, which is not significant. Its real effect is lower volatility and drawdown.
- **Momentum is the only factor that predicts anything here** (rank IC t ≈ 2.2). Reversal predicts nothing and drives turnover; low volatility is significantly *negative* in this universe.
- **Everything is survivorship-biased.** The universes are today's members projected backward, so every number above is a ceiling.
- **Crypto trend-following buys drawdown control,** not a higher Sharpe ratio.

## What separates this from a live system

These limits are deliberate. The engine is built so each one can be swapped in:

- **Data**: Yahoo adjusted closes. Production needs a point-in-time vendor (CRSP, Norgate, Polygon) with corporate actions and delistings.
- **Universe**: a fixed list. Production needs a liquidity-screened universe that is rebuilt every period, typically 500–3000 names.
- **Risk model**: the terminal has a Barra-style factor risk model for monitoring and attribution, and construction runs a constrained optimizer (sector, beta, turnover), but the optimizer uses the shrunk sample covariance, not the factor model, and the styles are price-based only. Production uses fundamental styles (value, quality, size) and the factor model inside the optimizer.
- **Costs**: linear bps in the backtest. TCA on the terminal measures what fills actually cost (delay, impact, participation); production uses a square-root impact model scaled by ADV, plus borrow costs on shorts.
- **Process**: an approval step, an audit trail and limits with traffic lights exist, but there is no independent risk team, model validation or compliance sign-off, which is the human layer real desks rely on.
- **Execution**: `live.py` trades a simulator or Alpaca (paper or live) in two separated sleeves, with per-sleeve drawdown halts and kill switches, idempotent order ids, a stale-data guard, fat-finger limits and email alerts through failed GitHub runs. It doesn't manage intraday orders.
- **Validation**: `research.py` runs factor ICs, a walk-forward over a 20-setting grid and deflated Sharpe ratios. A point-in-time universe is still missing.

## Tests

`tests/test_core.py` checks the properties that silently break backtests:

- **No look-ahead**: scrambling every price after day *T* leaves every return, weight and trade up to *T* unchanged, with and without the swap overlay.
- Idle cash earns the risk-free rate, and Sharpe is computed on excess returns.
- Zero costs give gross = net, and higher costs give lower returns.
- Position and leverage limits hold on every trade day.
- Long-only never shorts. Long/short is dollar-neutral at unit gross.
- Metric functions match hand-computed values.

`tests/test_desk.py` checks the desk analytics and construction: the QP solver against a known answer, the optimizer's sector, beta and position limits and turnover penalty, that the optimized backtest has no look-ahead, the shadow backtest's start date, and that the crypto carve-out isn't counted as a loss. It also checks the desk analytics: risk shares (by factor group and by name) add up to 100% and total variance = factor + specific; attribution adds up exactly to the strategy's return; TCA splits slippage into delay and impact; traffic-light thresholds; and that the approval gate holds a rebalance across runs and releases it on approval.

`tests/test_live.py` checks the trading job: the crypto sleeve's NAV ledger, that the stock strategy never sizes from or sells coins, that a crypto halt leaves stocks untouched, fractional crypto orders, idempotent retries, that stale-order cleanup never touches hand-placed orders, migration of old state, and the swap overlay end to end.

CI runs on Python 3.11 and 3.12 on every push.

---

Research software, not investment advice. Past backtested performance does not predict future returns.
