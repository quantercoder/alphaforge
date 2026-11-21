# Pre-registered test 9: multi-asset strategies (trend following across asset classes)

Written and committed **before** any strategy below was run (see this file's git history). Code:
`alphaforge/multiasset.py`; output: [RESEARCH_9.md](RESEARCH_9.md) and the Multi-Asset page.

## Why

Every earlier test looked for an edge inside US stocks. Professional multi-asset funds earn differently: they hold
many asset classes and follow their trends, getting paid mostly when stock markets fall (Moskowitz, Ooi &
Pedersen 2012; Hurst, Ooi & Pedersen 2017: positive in about a century of data). The question here: does such a
portfolio, alone or next to stocks, beat holding the S&P 500 on a risk-adjusted basis?

## Universe: 16 ETFs (no survivorship bias: none was chosen for its later performance)

| Class | ETFs |
|---|---|
| US stocks | SPY (large), IWM (small) |
| International stocks | EFA (developed), EEM (emerging) |
| Government bonds | SHY (1–3 years), IEF (7–10 years), TLT (20+ years), TIP (inflation-linked) |
| Credit | LQD (investment grade), HYG (high yield) |
| Real assets | VNQ (real estate), GLD (gold), SLV (silver), DBC (commodities) |
| Currencies | UUP (US dollar), FXY (Japanese yen) |

Each ETF joins once it has 13 months of history. Total returns (dividends included), monthly rebalancing at month-end
with the trade at the next close, 3 bp per unit of turnover, cash earning T-bills.

## Strategies

| | Strategy | Rule (fixed now) |
|---|---|---|
| M1 | **Trend following (TSMOM)**, the candidate | Each ETF's signal = average sign of its 1, 3, 6 and 12-month returns in excess of T-bills, held only if positive (long or cash, no shorting). Weight = signal × (10% ÷ its GARCH volatility) ÷ number of ETFs available, scaled so the whole portfolio targets 10% volatility (GARCH vols, 252-day correlation); at most 25% per ETF and 100% in total, no borrowing. |
| — | Risk parity | Equal risk contribution across SPY, EFA, EEM, IEF, TLT, TIP, GLD, DBC |
| — | Dual momentum (Antonacci) | If SPY's 12-month return beats T-bills, hold whichever of SPY and EFA did better; otherwise hold IEF |
| — | 60/40 | 60% SPY, 40% IEF |
| — | Permanent portfolio | 25% each SPY, TLT, GLD, SHY |
| — | Equal weight | all available ETFs equally |
| — | S&P 500 | SPY, buy and hold |

## Rules for M1 (all must pass), from January 2005 to the latest

1. **Risk-adjusted:** Sharpe ratio (excess of T-bills) at least SPY's and at least 60/40's.
2. **Crisis protection:** a positive return in at least 3 of 5 stock-market crises: October 2007–March 2009,
   July–September 2011, October–December 2018, February–March 2020, and 2022.
3. **Diversifying:** correlation of monthly returns with SPY at most 0.5.
4. **Better together:** 50% SPY + 50% M1, rebalanced monthly, has a higher Sharpe ratio than SPY **and** a maximum
   drawdown at least 10 points smaller.
5. **Stable:** Sharpe ratio above 0 in at least 2 of 3 periods: 2005–2012, 2013–2019, 2020–latest.

## Decision

If M1 passes, the **50/50 combination** (SPY + trend following) is proposed as a new multi-asset sleeve on the paper
account, and it goes live only with your approval. The other strategies are shown for comparison and are not
traded. Trials: 1 more (46 in the project). A pass means better risk-adjusted returns from diversification. It does
not mean a forecasting edge, and it does not mean beating the S&P's raw return every year.
