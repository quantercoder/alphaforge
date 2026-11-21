# Pre-registered test 7: company fundamentals from SEC EDGAR (value, quality, earnings surprises)

Written and committed **before** any fundamental data was downloaded or tested (see this file's git history).
Code: `alphaforge/fundamentals.py`; output: [RESEARCH_7.md](RESEARCH_7.md).

## Why

Every earlier test used prices only. Fundamentals are different information: what companies earn and own, as
reported to the SEC. The free SEC XBRL data carries each number's **filing date**, so a number can be used only
from the day the market could read it.

What 60 years of survivorship-free factor returns (Ken French) already say, before this test: value (book/price),
investment and size have earned about nothing since 2010; profitability earned a little (Sharpe 0.22, t 0.9);
momentum 0.26. Earnings surprises are not in that data. So the prior is weak for value, modest for quality, open
for earnings surprises.

## Data and point-in-time rules

- **Universe:** the point-in-time S&P 500 of test 2, at each month-end from January 2013 to the latest.
- **Fundamentals:** SEC XBRL company facts (`data.sec.gov/api/xbrl/companyfacts`), matched to tickers through the
  SEC's ticker file. Companies that no longer file can't be matched by ticker, so coverage (the share of
  member-months with the needed data) is measured and reported.
- **No look-ahead:** a value counts from the day after its `filed` date. For each fiscal period the **first filed**
  value is used, so later restatements never leak backwards.
- Each signal is ranked across the members that have it that month; members without it are left out of both the
  strategy and the benchmark that month.

## Candidates (each tested on its own)

| | Signal | Definition | Evidence |
|---|---|---|---|
| F1 | **Book-to-market (value)** | latest annual (10-K) `StockholdersEquity` ÷ (price × latest `EntityCommonStockSharesOutstanding`) | Fama & French (1992) |
| F2 | **Earnings yield (value)** | latest annual diluted EPS (`EarningsPerShareDiluted`, 10-K) ÷ price | Basu (1977) |
| F3 | **Profitability (quality)** | latest annual `NetIncomeLoss` ÷ the average of that year's start and end `Assets` (ROA) | Novy-Marx (2013); Fama & French (2015) |
| F4 | **Earnings surprise (drift)** | standardized unexpected earnings: latest quarter's diluted EPS minus the same quarter a year earlier, ÷ the standard deviation of that change over the prior 8 quarters (at least 4); a fourth quarter is the annual figure minus the first three quarters. Used only if reported in the last 4 months | Bernard & Thomas (1989) |

## Portfolio, benchmark, rules

Exactly test 2's: top 20% by the signal, equal weight, rebalanced monthly, 7 bp per unit of turnover, against equal
weight of all members that have the signal. All six of test 2's rules, with two changes:

- **Stability:** the periods are 2013–16, 2017–19, 2020–22 and 2023–latest (positive in at least 3 of 4).
- **Coverage:** at least 70% of member-months have the signal (rather than 90% priced), because filings can only be
  matched for companies that still file.

Deflation counts every configuration tried in the project: 39 before this test, plus these 4 = **43**.

## Decision

A candidate passing all six rules is **provisionally demonstrated**. It would be proposed for the live strategy only
with your approval, and only after its own paper period. If none passes: no demonstrated edge from fundamentals
either. Insider trades (SEC Form 4) are a separate, later test.
