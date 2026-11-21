# Research report 7: SEC EDGAR fundamentals

Generated 2026-11-21 by `python -m alphaforge.fundamentals`. Rules committed before the run: [PREREGISTRATION_7.md](PREREGISTRATION_7.md).

619 companies matched to SEC filings; 132,031 point-in-time events (each usable from the day after its filing). Events: `data/fundamental_events.csv.gz`.

| Signal | Coverage | IC | IR vs equal weight | t | Rules passed |
|---|---|---|---|---|---|
| F1 Book-to-market (value) | 86% | -0.007 | +0.06 | +0.2 | 3 of 6 |
| F2 Earnings yield (value) | 96% | +0.011 | +0.01 | +0.0 | 1 of 6 |
| F3 Profitability, ROA (quality) | 94% | +0.006 | +0.07 | +0.3 | 1 of 6 |
| F4 Earnings surprise, SUE (drift) | 92% | +0.004 | -0.08 | -0.3 | 1 of 6 |

## F1. Book-to-market (value)

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC -0.007, t -0.5 |
| 2. Edge vs equal weight | **fail** | IR +0.06, t +0.2 over 13.8 years |
| 3. Deflated | **fail** | 5% after 43 trials |
| 4. Stability | pass | 2013–16 +0.19, 2017–19 -0.99, 2020–22 +0.27, 2023–now +0.46 |
| 5. Breadth | pass | liquid +0.03, less liquid +0.08 |
| 6. Coverage | pass | 86% of priced member-months have the signal |

## F2. Earnings yield (value)

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC +0.011, t +1.0 |
| 2. Edge vs equal weight | **fail** | IR +0.01, t +0.0 over 13.8 years |
| 3. Deflated | **fail** | 3% after 43 trials |
| 4. Stability | **fail** | 2013–16 -0.04, 2017–19 -0.52, 2020–22 +0.28, 2023–now +0.16 |
| 5. Breadth | **fail** | liquid -0.14, less liquid +0.18 |
| 6. Coverage | pass | 96% of priced member-months have the signal |

## F3. Profitability, ROA (quality)

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC +0.006, t +0.6 |
| 2. Edge vs equal weight | **fail** | IR +0.07, t +0.3 over 13.8 years |
| 3. Deflated | **fail** | 5% after 43 trials |
| 4. Stability | **fail** | 2013–16 -0.90, 2017–19 +1.11, 2020–22 +0.28, 2023–now -0.22 |
| 5. Breadth | **fail** | liquid +0.29, less liquid -0.08 |
| 6. Coverage | pass | 94% of priced member-months have the signal |

## F4. Earnings surprise, SUE (drift)

| Rule | Result | Evidence |
|---|---|---|
| 1. Signal | **fail** | IC +0.004, t +0.7 |
| 2. Edge vs equal weight | **fail** | IR -0.08, t -0.3 over 13.8 years |
| 3. Deflated | **fail** | 1% after 43 trials |
| 4. Stability | **fail** | 2013–16 -0.39, 2017–19 +0.00, 2020–22 -0.56, 2023–now +0.48 |
| 5. Breadth | **fail** | liquid +0.17, less liquid -0.25 |
| 6. Coverage | pass | 92% of priced member-months have the signal |

## Verdict

No fundamental signal passes all six rules: no demonstrated edge from fundamentals either.

