# Live trading

AlphaForge runs a daily job, `python -m alphaforge.live`, that turns the model's month-end signal into orders. It runs against one of two brokers:

| Broker | What it is | Money at risk |
|---|---|---|
| `sim` (default) | Paper account stored in `state/account.json` | none |
| `alpaca` | [Alpaca](https://alpaca.markets) paper account | none |
| `alpaca` + `live_money` | Alpaca live account | **real** |

## What one run does

1. Downloads prices for the universe, SPY and the market strip.
2. Refuses to trade if the latest close is older than `max_data_age_days`.
3. Marks the book to market and updates the high-water mark.
4. **Halt check.** If equity is more than `max_drawdown_halt` below its peak, the job flattens the book and writes `state/KILL`. It does the same whenever `state/KILL` exists or `ALPHAFORGE_KILL=1` is set.
5. Simulator only: fills the orders queued yesterday at today's close.
6. On the last trading day of the month, computes target weights with the same function the backtest uses. Alpaca orders go out right away and fill at the next open. Simulator orders wait for the next run.
7. Writes `state/equity.csv` and `state/orders.jsonl`, then rebuilds `site/data.json` for the terminal.

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
  "broker": "sim",
  "live_money": false,
  "capital": 100000,
  "strategy": {"mode": "long_only", "target_vol": 0.12, "max_weight": 0.10, "max_leverage": 1.0},
  "min_trade_notional": 200,
  "max_order_notional": 25000,
  "max_drawdown_halt": 0.20
}
```

`strategy` accepts any `backtest.Config` field, so whatever you test in the dashboard can be run live unchanged. Keep `long_only` unless your broker account allows short selling.

## Connect Alpaca (paper)

1. Create a paper account at alpaca.markets and generate an API key.
2. Set the keys as environment variables on the machine that runs the job: `ALPACA_KEY_ID` and `ALPACA_SECRET_KEY`. In GitHub Actions, store them as repository **secrets**, never in the repo.
3. Set `"broker": "alpaca"` in `live.json`.

## Real money

Two separate switches have to agree before an order reaches the live endpoint:

1. `"live_money": true` in `live.json` (a committed, reviewable change), and
2. `ALPHAFORGE_CONFIRM_LIVE=yes` in the job's environment.

If only one is set, the job stops with an error and sends nothing.

Before you flip them, be clear about what the evidence supports. The market-neutral version has no statistically meaningful edge, and the long-only backtest is inflated by survivorship bias ([MATH.md §14](MATH.md#14-statistical-caveats)). Run on paper for months first, and compare paper fills with the backtest over the same period.

## Stopping it

- **Now:** set `ALPHAFORGE_KILL=1`, or create `state/KILL`. The next run flattens the book and trades nothing more.
- **Resume:** delete `state/KILL` (and unset the variable). A drawdown halt always needs a person to do this.
- **Alpaca directly:** "Close all positions" in the Alpaca dashboard works at any time, independent of this code.

## Known gaps

- The trading calendar uses US federal holidays as a stand-in for NYSE holidays; the catch-up rule covers mismatches.
- Simulator fills use the close plus fixed slippage, with no partial fills or market impact.
- Alpaca orders are fire-and-forget. Fills are not reconciled back into `orders.jsonl`; check the Alpaca dashboard.
- Whole shares only, which leaves up to one share of tracking error per name.
