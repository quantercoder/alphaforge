# Live trading

AlphaForge runs a daily job, `python -m alphaforge.live`, that turns two strategies' signals into orders:

| Sleeve | Strategy | Rebalance | Terminal page |
|---|---|---|---|
| **Equities** | multi-factor stock strategy ([MATH.md](MATH.md)) | month-end, plus a 2-week swap of the worst 2 | `index.html` |
| **Crypto** | trend-following on 8 coins ([MATH.md §16](MATH.md#16-the-crypto-sleeve)) | every 7 days | `crypto.html` |

The sleeves share one broker account but are kept apart: each has its own NAV, high-water mark, drawdown halt and kill switch, and neither ever trades the other's positions. The crypto sleeve starts with a fixed budget (`crypto.budget`, \$10,000) and then moves only with its own P&L; the equity sleeve is the rest of the account ([MATH.md §13.0](MATH.md#130-sleeves)).

It runs against one of two brokers:

| Broker | What it is | Money at risk |
|---|---|---|
| `sim` (default) | Paper account stored in `state/account.json` | none |
| `alpaca` | [Alpaca](https://alpaca.markets) paper account | none |
| `alpaca` + `live_money` | Alpaca live account | **real** |

## What one run does

For each sleeve:

1. Downloads prices (equities from 2014, crypto from 2019; for crypto only complete UTC days).
2. Refuses to trade if the latest close is older than `max_data_age_days`.
3. Works out the sleeve's NAV and updates its high-water mark.
4. **Halt check.** If the sleeve's NAV is more than `max_drawdown_halt` below its peak, the job flattens that sleeve and writes `state/KILL` (equities) or `state/KILL_CRYPTO`. It does the same whenever that file exists or `ALPHAFORGE_KILL` is `1` (all sleeves), `equity` or `crypto`.
5. Simulator only: fills the orders queued yesterday at today's close.
6. Every 10 trading days between month-ends (`swap_every`), sells the 2 holdings with the worst P&L since purchase (`swap_count`) and buys the 2 highest-scoring stocks it doesn't own, provided each scores higher than the one it replaces. See [MATH.md §13.4](MATH.md#134-two-week-swap-of-the-worst-performers).
7. On its signal day (month-end for equities, every 7 days for crypto), computes target weights with the same function the backtest uses. Alpaca equity orders fill at the next open; crypto orders fill immediately. Simulator orders wait for the next run.
8. Writes `state/equity.csv` (account and both sleeve NAVs) and `state/orders.jsonl`, checks the broker for rejected or canceled orders, then rebuilds `site/data.json` and `site/crypto.json`.

**Alerts.** A drawdown halt, a rejected order, or a broker cancellation of one of the job's orders is written to `alerts.txt`, and the GitHub job then fails on purpose. GitHub emails the repository owner about failed scheduled runs, so a problem reaches you without watching the site. The page still deploys and the state is still committed first.

**Retries are safe.** Every order has a deterministic id (`af-equ-2026-10-30-rb-AAPL-0`), so a re-run on the same day sends nothing twice: the broker rejects the duplicates and the job records them as `duplicate`, not as errors.

The order-sizing math, filters and controls are specified in [MATH.md §13](MATH.md#13-live-execution).

## Run it locally

```bash
pip install -r requirements.txt
python -m alphaforge.live                 # one trading day on the simulator
python -m alphaforge.live --quotes-only   # refresh the terminal without trading
python -m http.server 8600 --directory site   # open http://localhost:8600
```

Run it once per weekday after 16:00 New York time. Running twice on the same day is safe: the equity row for that date is overwritten, and no new signal fires until the next month-end.

## Automation (GitHub Actions)

`.github/workflows/terminal.yml` runs on GitHub's servers:

| When (UTC, Mon–Fri) | What |
|---|---|
| 21:15 | Trading run: `python -m alphaforge.live`, then commits `state/` (account, equity curve, orders) to `main` |
| every 30 min, 13:00–20:30 | Quote refresh: `--quotes-only`, no trading |
| on push to `site/`, `alphaforge/` or `live.json` | Quote refresh and redeploy |

Every run redeploys the terminal to GitHub Pages. `state/` in git is the audit trail: each commit is one trading day. To pause automation, disable the workflow under **Actions → terminal → ⋯ → Disable workflow**. To stop trading but keep quotes, set the repository variable `ALPHAFORGE_KILL` to `1` (Settings → Secrets and variables → Actions → Variables).

GitHub may delay scheduled runs by several minutes at busy times, and pauses schedules in repos with no activity for 60 days.

## Configuration: `live.json`

```json
{
  "broker": "alpaca",
  "live_money": false,
  "capital": 100000,
  "strategy": {"mode": "long_only", "target_vol": 0.12, "max_weight": 0.1, "max_leverage": 1.0,
               "swap_every": 10, "swap_count": 2},
  "min_trade_notional": 200,
  "max_order_notional": 25000,
  "max_drawdown_halt": 0.2,
  "crypto": {"enabled": true, "budget": 10000}
}
```

`crypto` accepts any key from `CRYPTO_DEFAULTS` in `live.py`: `universe`, `strategy` (target vol 25%, max 35% per coin), `rebalance_days` (7), `cash_buffer` (2%), `max_drawdown_halt` (50%), `max_order_notional` (\$5,000). Set `"enabled": false` to stop the crypto strategy; coins then stay where they are and are excluded from the equity sleeve's NAV.

`watchlist` (optional, defaults to the S&P 100) lists extra tickers the terminal shows. It doesn't change what the strategy trades; that's `universe`. Use Yahoo symbols, for example `BRK-B`.

`strategy` accepts any `backtest.Config` field, so whatever you test in the dashboard can be run live unchanged. Keep `long_only` unless your broker account allows short selling.

## Connect Alpaca (paper)

1. Create a paper account at alpaca.markets and generate an API key.
2. Set the keys as environment variables on the machine that runs the job: `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY`. In GitHub Actions, store them as repository **secrets**, never in the repo.
3. Set `"broker": "alpaca"` in `live.json`.

With Alpaca connected, the terminal reads everything from your account: the **Paper book** shows Alpaca's positions and prices, the **Order blotter** shows Alpaca's orders with filled quantity, average fill price and status, and the **Paper account** tab shows equity, cash, buying power, day P&L and Alpaca's own daily equity history. These refresh on every run (every 30 minutes in market hours). Before placing a new rebalance the job cancels any orders still open, so a rerun never doubles up.

Each sleeve manages every position in its asset class. A stock bought by hand is part of the equity sleeve and will be sold at the next rebalance if the model doesn't want it; a coin bought by hand becomes part of the crypto sleeve. Orders you place by hand are never canceled by the job, and the blotter marks them "manual". For manual trading, use a separate paper account.

## Real money

Two separate switches have to agree before an order reaches the live endpoint:

1. `"live_money": true` in `live.json` (a committed, reviewable change), and
2. `ALPHAFORGE_CONFIRM_LIVE=yes` in the job's environment.

If only one is set, the job stops with an error and sends nothing.

Before you flip them, be clear about what the evidence supports. The market-neutral version has no statistically meaningful edge, and the long-only backtest is inflated by survivorship bias ([MATH.md §14](MATH.md#14-statistical-caveats)). Run on paper for months first, and compare paper fills with the backtest over the same period.

## Before real money: a pass/fail rule

Decide this before looking at results, write it down, and stick to it. A sensible template:

1. **Time:** at least 6 months of paper trading through the Alpaca account (12 is better), including at least one month-end rebalance per month and one market drop of 5% or more.
2. **Tracking:** the paper equity sleeve's daily returns correlate with the backtest's over the same days at 0.9 or better, and the average slippage on the blotter stays within the 7 bps the backtest assumes.
3. **Benchmark:** the paper sleeve does not trail an equal-weight portfolio of the same 30 names by more than its lower volatility explains. [RESEARCH.md](RESEARCH.md) shows the backtest itself doesn't clear this bar, so expect to fail it.
4. **Controls:** the kill switch has been tested on paper (set `ALPHAFORGE_KILL=equity` for one run and confirm the sleeve flattens), and an alert email has actually arrived.

If any point fails, stay on paper. That decision is yours; this repository will not flip the switches.

## Stopping it

- **Now:** set the repository variable `ALPHAFORGE_KILL` to `1` (both sleeves), `equity` or `crypto`, or create `state/KILL` / `state/KILL_CRYPTO`. The next trading run flattens that sleeve and trades nothing more in it.
- **Resume:** delete the file (and unset the variable). A drawdown halt always needs a person to do this.
- **Alpaca directly:** "Close all positions" in the Alpaca dashboard works at any time, independent of this code.

## Known gaps

- The trading calendar uses US federal holidays as a stand-in for NYSE holidays; the catch-up rule covers mismatches.
- Simulator fills use the close plus fixed slippage, with no partial fills or market impact.
- Reconciliation is by alert, not repair: rejected, canceled or expired orders raise an alert, and the next rebalance re-targets the book. There is no intraday retry.
- The Alpaca account pays no interest on cash, while the backtest credits idle cash with the T-bill rate.
- Whole shares only, which leaves up to one share of tracking error per name.
