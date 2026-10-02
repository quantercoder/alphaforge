# AlphaForge

**[Open the terminal](https://z125081-sam-lam.github.io/alphaforge/)** · [Math model](docs/MATH.md) · [Live trading](docs/LIVE_TRADING.md)

A multi-factor equity strategy engine with a Bloomberg-style web terminal, a paper/live trading job and a Streamlit research dashboard. It follows the workflow a systematic equity desk uses: cross-sectional factor signals, risk-aware portfolio construction, and a backtest with execution lag, weight drift and transaction costs. The backtest is tested for look-ahead bias.

```bash
pip install -r requirements.txt
streamlit run app.py            # dashboard
python -m alphaforge --synthetic  # CLI, offline
python -m alphaforge --mode long_only --start 2015-01-01
pytest -q
python -m alphaforge.live         # one trading day (paper simulator by default)
```

## Terminal

`site/index.html` is a static, keyboard-driven terminal hosted on GitHub Pages. It reads `site/data.json`, which `python -m alphaforge.live` writes.

- Command line: type `NVDA` and press Enter to chart it. `PORT`, `SIG`, `RISK`, `BT`, `BLTR`, `MTH` and `HELP` jump to panels, and F1–F8 do the same.
- Market strip (SPX, NDX, RTY, VIX, 10Y, DXY, gold, WTI, BTC, EURUSD), a sortable monitor with sparklines, and candlestick charts.
- The paper book, order blotter, per-name signals, ex-ante risk with factor exposures and a correlation matrix, the backtest and a monthly returns grid.

**Data.** A GitHub Actions job (`.github/workflows/terminal.yml`) refreshes delayed Yahoo data every 30 minutes during market hours. After each close it trades the paper account, commits `state/` and redeploys the page.

**Live prices.** Type `LIVE` or click the status chip, then paste an Alpaca paper-account API key. The page then streams real-time trades from Alpaca's free IEX feed for up to 30 symbols, plus BTC. Your key stays in your browser and is never sent to GitHub.

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
| **Execution** | Signal at close *t*, trade at close *t+1*. Weights drift with prices between rebalances, and costs (commission + slippage bps) are charged on the actual trade from drifted holdings | `backtest.py` |
| **Live** | Month-end signal from the same code path, whole-share order sizing, sells before buys, sim or Alpaca broker, drawdown halt | `live.py`, `broker.py` |
| **Analytics** | CAGR, Sharpe, Sortino, Calmar, max drawdown, historical VaR/CVaR, beta/alpha, turnover, cost drag, monthly table | `metrics.py` |

## Dashboard

- **KPI row**: CAGR, Sharpe, max drawdown, volatility, beta, turnover
- **Performance**: log equity curve vs SPY, underwater curve, 6-month rolling Sharpe
- **Returns**: monthly heatmap, daily return distribution with VaR, calendar-year bars
- **Positions**: current long/short book, gross and net exposure, turnover per rebalance
- **Signals**: the latest factor z-scores, blended alpha and resulting weights for each name
- **Statistics**: full metric table vs benchmark, CSV export

Every parameter (universe, mode, rebalance frequency, vol target, caps, costs, factor weights) is a sidebar control. If Yahoo is unreachable, the **Synthetic** source runs fully offline.

## Honest results

Defaults: 30 US mega caps, 2014 to present, monthly rebalance, 7 bps per unit traded.

| Mode | CAGR | Sharpe | Max DD | Beta |
|---|---|---|---|---|
| Market-neutral L/S | ~1.5% | ~0.2 | -25% | 0.07 |
| Long-only | ~15% | ~1.1 | -21% | 0.60 |

Read these numbers with care:

- **The market-neutral book barely beats cash.** Classic price factors inside 30 heavily arbitraged mega caps carry very little alpha after costs. That is a realistic finding, not a bug.
- **Long-only performance is mostly beta plus survivorship.** The universe is *today's* mega caps projected backward, so it already knows which companies won. A real study needs point-in-time index membership, delisted names included.
- Weekly rebalancing roughly triples turnover and costs more than the faster signal earns back.

## What separates this from a live system

These limits are deliberate. The engine is built so each one can be swapped in:

- **Data**: Yahoo adjusted closes. Production needs a point-in-time vendor (CRSP, Norgate, Polygon) with corporate actions and delistings.
- **Universe**: a fixed list. Production needs a liquidity-screened universe that is rebuilt every period, typically 500–3000 names.
- **Risk model**: a shrunk sample covariance. Production uses a factor risk model (Barra-style) and a constrained optimizer (cvxpy) with sector neutrality and turnover penalties.
- **Costs**: linear bps. Production uses a square-root impact model scaled by ADV, plus borrow costs on shorts.
- **Execution**: `live.py` trades a simulator or Alpaca (paper or live), with drawdown halt, kill switch, stale-data guard and fat-finger limits. It doesn't reconcile fills or manage intraday orders.
- **Validation**: a single in-sample run. Use walk-forward splits and deflated Sharpe before trusting any parameter choice.

## Tests

`tests/test_core.py` checks the properties that silently break backtests:

- **No look-ahead**: scrambling every price after day *T* leaves every return up to *T* unchanged.
- Zero costs give gross = net, and higher costs give lower returns.
- Position and leverage limits hold on every trade day.
- Long-only never shorts. Long/short is dollar-neutral at unit gross.
- Metric functions match hand-computed values.

CI runs on Python 3.11 and 3.12 on every push.

---

Research software, not investment advice. Past backtested performance does not predict future returns.
