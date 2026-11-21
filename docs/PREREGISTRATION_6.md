# Pre-registered test 6: market forecasts with point-in-time macro data (FRED / ALFRED)

Written and committed **before** any of these data were used in a model (see this file's git history). Code:
`alphaforge/macro.py`; output: [RESEARCH_6.md](RESEARCH_6.md).

## Why

Test 4 forecast SPY with macro features from Yahoo: market prices standing in for macro data. Real macro data
(payrolls, unemployment, inflation, industrial production) gets revised after release, sometimes a lot: January
2020 payrolls were first published as 152,186 thousand and now read 152,031 thousand. A model trained on today's
revised numbers uses information nobody had at the time. ALFRED keeps every published vintage, so each feature
here is the value **as it was known on the forecast date**.

## Features (each known at the forecast date)

**SPY technicals (unchanged from test 4):** past returns over 5, 21, 63 and 252 days; distance from the 200-day
average; 21-day realized volatility; GARCH(1,1) volatility.

**Market series from FRED** (never revised; used the day after their date, to allow for publication):

| Feature | Series |
|---|---|
| Term spread | DGS10 − DGS3MO |
| Credit spread | BAA10Y (Moody's Baa − 10-year Treasury) |
| VIX | VIXCLS |
| Dollar, 63-day change | DTWEXBGS (broad trade-weighted) |
| Oil, 63-day change | DCOILWTICO |

**Macro series from ALFRED, as first known on each date** (vintages, so revisions never leak):

| Feature | Series | Transform |
|---|---|---|
| Payroll growth | PAYEMS | 3-month change, annualized |
| Unemployment momentum | UNRATE | latest minus the lowest of the prior 12 months (the Sahm-rule idea) |
| Inflation | CPIAUCSL | 12-month change |
| Industrial production | INDPRO | 6-month change |
| Jobless claims | ICSA | 4-week average ÷ 52-week average − 1 |
| Financial conditions | NFCI | latest level |
| Housing permits | PERMIT | 12-month change |

## Test

Exactly test 4's track A: SPY's log return over 5, 21 and 63 trading days, weekly forecasts, out of sample from
January 2014, every model refitted each January on data whose target ended before that date; the same seven
models and the equal-weight ensemble, with the same specifications.

## Rule (stricter than test 4)

At each horizon, the **ensemble** must have an out-of-sample R² above 0 against the historical mean **and** a
Diebold-Mariano p-value below **0.05 / 3 = 0.0167** (one-sided, Newey-West, Bonferroni across the three horizons).

Test 4's hit-rate rule is dropped: SPY rises most weeks, so the historical mean already beats 50%, and that rule
couldn't tell skill from drift.

## Decision

A pass at any horizon makes that horizon's forecast **provisionally demonstrated**. It would be reported, not
traded, and any use in trading would need its own test. Either way, the Lab switches to these point-in-time
features, because they are the honest data. Trials: 3 more (39 in the project so far).
