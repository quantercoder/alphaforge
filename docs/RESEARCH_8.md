# Research report 8: beating the S&P 500 by taking more risk, with control

Generated 2026-11-21 by `python -m alphaforge.test8`. Rules committed before the run: [PREREGISTRATION_8.md](PREREGISTRATION_8.md). This is a choice to carry more market risk, managed by GARCH volatility and a trend filter. It is not a forecasting edge.

SPY from 1998, daily, net of 2 bp per unit of turnover; borrowing at T-bills + 1%; cash earns T-bills.

| | CAGR | Vol | Sharpe | Max DD | Worst year | Best year | Avg weight | Days levered | Turnover / yr |
|---|---|---|---|---|---|---|---|---|---|
| SPY buy and hold | 8.9% | 19.3% | 0.43 | -55.2% | -36.8% | 32.3% | 1.00 | 0% | 0.0× |
| R1 risk-targeted | 9.4% | 18.5% | 0.46 | -51.5% | -28.5% | 46.8% | 1.22 | 77% | 6.5× |
| R2 risk-targeted + trend filter | 8.9% | 15.8% | 0.49 | -37.0% | -18.4% | 46.8% | 1.11 | 67% | 8.5× |

## R1 risk-targeted: pass

| Rule | Result | Evidence |
|---|---|---|
| 1. Higher return | pass | CAGR 9.4% vs SPY 8.9% |
| 2. Consistently (rolling 10 years) | pass | beat SPY in 90% of 228 windows |
| 3. In each era | pass | 1998–07 4.6% vs 5.8%, 2008–15 8.4% vs 6.5%, 2016–now 14.7% vs 13.7% |
| 4. Not a worse crash | pass | max drawdown -51.5% vs SPY -55.2% |
| 5. Not just leverage | pass | Sharpe 0.46 vs SPY 0.43 |

## R2 risk-targeted + trend filter: pass

| Rule | Result | Evidence |
|---|---|---|
| 1. Higher return | pass | CAGR 8.9% vs SPY 8.9% |
| 2. Consistently (rolling 10 years) | pass | beat SPY in 82% of 228 windows |
| 3. In each era | pass | 1998–07 4.1% vs 5.8%, 2008–15 8.5% vs 6.5%, 2016–now 14.0% vs 13.7% |
| 4. Not a worse crash | pass | max drawdown -37.0% vs SPY -55.2% |
| 5. Not just leverage | pass | Sharpe 0.49 vs SPY 0.43 |

## Decision

**R2 risk-targeted + trend filter** passes: it goes live on the paper account as the equity sleeve's strategy.

## Sensitivity to the borrowing rate (not part of the rules; the verdict stands)

The rules assumed borrowing at T-bills + 1%. A broker's margin rate is often T-bills + 2–3%. Exact excess annual
return over SPY:

| Borrowing at | R1 risk-targeted | R2 + trend filter |
|---|---|---|
| T-bills + 1% (the test) | +0.48% | +0.06% |
| T-bills + 2% | +0.18% | −0.22% |
| T-bills + 3% | −0.11% | −0.49% |

On raw return, neither reliably beats SPY once borrowing costs are realistic: the extra return from leverage is
mostly paid away in interest. R2's lasting difference is risk: a maximum drawdown of −37% against −55%, a worst
year of −18% against −37%, and a higher Sharpe ratio.
