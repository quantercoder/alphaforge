# The AlphaForge model

This document specifies every quantity the engine computes, in the order the code computes it. Each section names the function that implements it, so you can check one against the other. When the code and this document disagree, the code is the bug report.

**Contents**

1. [Notation](#1-notation)
2. [Returns](#2-returns)
3. [Factors](#3-factors)
4. [Cross-sectional standardization](#4-cross-sectional-standardization)
5. [Alpha blending](#5-alpha-blending)
6. [From alpha to weights](#6-from-alpha-to-weights)
7. [Position caps](#7-position-caps-water-filling)
8. [Covariance estimation](#8-covariance-estimation)
9. [Volatility targeting and leverage](#9-volatility-targeting-and-leverage)
10. [Timing and the no-look-ahead guarantee](#10-timing-and-the-no-look-ahead-guarantee)
11. [Portfolio accounting: drift, turnover, costs](#11-portfolio-accounting-drift-turnover-costs)
12. [Performance and risk statistics](#12-performance-and-risk-statistics)
13. [Live execution](#13-live-execution)
14. [Statistical caveats](#14-statistical-caveats)
15. [Parameter reference](#15-parameter-reference)
16. [The crypto sleeve](#16-the-crypto-sleeve)
17. [Desk analytics](#17-desk-analytics): factor risk model, attribution, stress, liquidity, limits, TCA, signal diagnostics, approval and audit, next-trade preview, data health

---

## 1. Notation

| Symbol | Meaning |
|---|---|
| $t = 0,\dots,T$ | trading days, indexing daily closes |
| $i = 1,\dots,N$ | assets in the universe |
| $P_{i,t}$ | split- and dividend-adjusted close of asset $i$ on day $t$ |
| $p_{i,t} = \ln P_{i,t}$ | log price |
| $r_{i,t}$ | simple return from $t-1$ to $t$ |
| $\mathcal{U}_t$ | assets with a defined score on day $t$ (the tradeable set) |
| $N_t = \lvert \mathcal{U}_t \rvert$ | size of the tradeable set |
| $w_{i,t}$ | weight of asset $i$, as a fraction of net asset value (NAV) |
| $\mathbf{w}_t \in \mathbb{R}^N$ | the weight vector |
| $\lVert \mathbf{w} \rVert_1 = \sum_i \lvert w_i \rvert$ | gross exposure |
| $\mathbf{1}^\top \mathbf{w} = \sum_i w_i$ | net exposure |
| $\mathcal{F}_t$ | information available at the close of day $t$ |

All annualization uses $A = 252$ trading days (`metrics.TD`).

## 2. Returns

Simple and log returns:

```math
r_{i,t} = \frac{P_{i,t}}{P_{i,t-1}} - 1, \qquad \ell_{i,t} = p_{i,t} - p_{i,t-1} = \ln(1 + r_{i,t}).
```

Simple returns aggregate across assets: the portfolio return is $\sum_i w_i r_i$. Log returns aggregate across time: the $k$-day log return is $\sum_{s=0}^{k-1} \ell_{i,t-s}$. The engine uses each where its aggregation property is the one that's needed. Factors are built from log prices, and portfolio accounting uses simple returns.

Missing prices are forward-filled only after the series starts. A ticker missing more than 5% of its history is dropped instead (`data.load_prices`), so a price that didn't exist yet can never enter a signal.

## 3. Factors

Each factor maps the price history up to $t$ to a raw score $f_{i,t}$. Higher scores mean higher expected return. All four are implemented in `signals.py`.

### 3.1 Momentum, 12–1 (`momentum`)

```math
f^{\text{MOM}}_{i,t} = p_{i,t-21} - p_{i,t-252} = \ln \frac{P_{i,t-21}}{P_{i,t-252}}.
```

This is the return over the past year, excluding the most recent month. The skipped month matters because one-month returns tend to *reverse* (see 3.2), and including them would partly cancel the momentum effect (Jegadeesh & Titman, 1993).

### 3.2 Short-term reversal (`reversal`)

```math
f^{\text{REV}}_{i,t} = -\left(p_{i,t} - p_{i,t-5}\right).
```

Last week's losers score highly. The effect is usually attributed to liquidity provision: prices pushed away from value by order-flow imbalance tend to revert (Lehmann, 1990). It's the fastest-decaying factor here and the main source of turnover.

### 3.3 Low volatility (`low_vol`)

```math
f^{\text{LV}}_{i,t} = -\hat\sigma_{i,t}, \qquad
\hat\sigma_{i,t} = \sqrt{\frac{1}{62}\sum_{s=0}^{62}\left(\ell_{i,t-s} - \bar\ell_{i,t}\right)^2}.
```

This is the 63-day sample standard deviation of daily log returns, with $n-1$ in the denominator. The evidence for a total-volatility anomaly is Ang, Hodrick, Xing & Zhang (2006), who find that stocks with high recent volatility earn low subsequent returns, and Baker, Bradley & Wurgler (2011), who tie it to benchmark-constrained investors. (Frazzini & Pedersen's "Betting Against Beta" is about beta, a related but different measure.)

**In this universe the factor works backwards.** Over 2015 to 2026 its rank IC against the next 63 days' returns is $-0.14$ ($t \approx -4.7$; see [RESEARCH.md](RESEARCH.md)): the most volatile mega caps (mostly technology) did best. The anomaly is documented across broad universes; 30 survivors of a tech-led decade are not one.

### 3.4 Trend quality (`quality_trend`)

```math
f^{\text{TQ}}_{i,t} = \frac{p_{i,t} - p_{i,t-126}}{\sum_{s=0}^{125} \lvert \ell_{i,t-s} \rvert}.
```

This is the net six-month move divided by the total distance the price travelled. By the triangle inequality $\lvert p_t - p_{t-126} \rvert \le \sum \lvert \ell \rvert$, so $f^{\text{TQ}} \in [-1, 1]$. A value of $+1$ means every day was an up day. It rewards smooth trends over jumpy ones with the same endpoint, a price-only stand-in for the "frog in the pan" information-discreteness effect (Da, Gurun & Warachka, 2014).

**Warm-up.** Momentum needs 252 observations, so no trade happens before `Config.warmup = 252`.

## 4. Cross-sectional standardization

Raw factors live on different scales: momentum is a log return and low-vol is a daily volatility. Before blending, each factor is converted into a cross-sectional z-score for each day (`signals.cs_zscore`):

```math
z_{i,t} = \operatorname{clip}\!\left(\frac{f_{i,t} - \mu_t}{s_t},\; -3,\; 3\right),
\quad
\mu_t = \frac{1}{N_t}\sum_{j \in \mathcal{U}_t} f_{j,t},
\quad
s_t = \sqrt{\frac{1}{N_t - 1}\sum_{j \in \mathcal{U}_t} (f_{j,t} - \mu_t)^2}.
```

Three properties matter:

- **Cross-sectional, not time-series.** Each day is standardized against itself, so only *relative* rank enters. A shock that moves every $f_{i,t}$ by the same amount (or scales them all by the same positive factor) leaves $z$ unchanged. A real crash rarely does that: high-beta names fall further, so ranks still move. This is why a dollar-neutral book built from $z$ has little market exposure by construction.
- **Winsorization at ±3.** One extreme name (a biotech after an FDA decision) would otherwise dominate the weights through the linear mapping in §6. Clipping bounds any single name's influence. After clipping, $z$ is no longer exactly mean 0 and variance 1; §5 re-standardizes.
- **Degenerate days.** If $s_t = 0$ (all scores equal), $z$ is undefined (NaN) and nobody trades on that factor that day.

## 5. Alpha blending

Given factor weights $\lambda_k$ (`Config.factor_weights`, default momentum 0.4, the rest 0.2), the composite is (`signals.combine`):

```math
\alpha_{i,t} = \operatorname{cs\_zscore}\!\left(\sum_k \lambda_k \, \tilde z^{(k)}_{i,t}\right),
\qquad
\tilde z^{(k)}_{i,t} =
\begin{cases} z^{(k)}_{i,t} & \text{if defined} \\ 0 & \text{otherwise.}\end{cases}
```

A missing factor contributes the cross-sectional mean (zero) rather than removing the name. A name is tradeable only if at least one factor with $\lambda_k \neq 0$ is defined for it. Because the blend is re-standardized, only the *ratios* of the $\lambda_k$ matter: multiplying all weights by the same constant changes nothing.

**Why a linear blend.** If the factor z-scores were jointly Gaussian with forecast-return covariances $\mathbf{b}$ and factor covariance $\mathbf{\Omega}$, the minimum-variance linear forecast would weight them by $\mathbf{\Omega}^{-1}\mathbf{b}$. Fixed $\lambda$ treats $\mathbf{\Omega}$ as diagonal and $\mathbf{b}$ as known. That is a deliberate bias-for-variance trade, because estimated $\mathbf{\Omega}^{-1}\mathbf{b}$ weights are notoriously unstable (DeMiguel, Garlappi & Uppal, 2009). The factors are in fact correlated: momentum and trend quality overlap, and low-vol tends to anti-correlate with momentum in strong bull markets.

## 6. From alpha to weights

`portfolio.alpha_to_weights` produces a unit-gross vector $\mathbf{u}$ with $\lVert \mathbf{u} \rVert_1 = 1$.

### 6.1 Market-neutral long/short

```math
u_i = \frac{\alpha_i - \bar\alpha}{\sum_{j}\lvert \alpha_j - \bar\alpha \rvert},
\qquad \bar\alpha = \frac{1}{N_t}\sum_{j\in\mathcal{U}_t}\alpha_j.
```

**Claim:** $\mathbf{1}^\top\mathbf{u} = 0$ and $\lVert\mathbf{u}\rVert_1 = 1$.
*Proof.* The numerators sum to $\sum_i \alpha_i - N_t\bar\alpha = 0$, and the denominator is by definition the $\ell_1$ norm of the numerator vector. $\square$

Weights proportional to demeaned alpha are the solution to

```math
\max_{\mathbf{u}} \; \boldsymbol\alpha^\top \mathbf{u} - \frac{\gamma}{2}\,\mathbf{u}^\top \mathbf{u}
\quad \text{s.t. } \mathbf{1}^\top\mathbf{u} = 0,
```

which is a mean-variance optimizer with an identity covariance. Risk is then handled separately at the portfolio level by §9's scalar, not name by name. This "alpha-proportional, risk-scaled" construction is robust and transparent, and it gives up some efficiency compared with a full $\mathbf{\Sigma}^{-1}\boldsymbol\alpha$ solution.

### 6.2 Long-only

Let $n = \max(1, \operatorname{round}(0.3\,N_t))$ and let $\mathcal{T}$ be the $n$ names with the highest alpha. Rank them inside $\mathcal{T}$ from $1$ (lowest) to $n$ (highest):

```math
u_i = \frac{\operatorname{rank}_{\mathcal{T}}(\alpha_i)}{\sum_{j\in\mathcal T}\operatorname{rank}_{\mathcal T}(\alpha_j)} = \frac{2\operatorname{rank}_{\mathcal{T}}(\alpha_i)}{n(n+1)}, \quad i\in\mathcal T; \qquad u_i = 0 \text{ otherwise.}
```

Rank weighting is invariant to monotone transformations of alpha, so it's insensitive to outliers even beyond the winsorization. The top name gets $2/(n+1)$ of the book, about 20% for $n = 9$, before the caps in §7.

## 7. Position caps (water-filling)

`portfolio.cap_weights` enforces $\lvert u_i \rvert \le m$ while keeping gross exposure $G = \lVert\mathbf{u}\rVert_1$ fixed. Write $C$ for the set of capped names, starting empty. Repeat:

1. $O = \{i : \lvert u_i\rvert > m\}$. If $O = \varnothing$, stop.
2. $C \leftarrow C \cup O$, and set $u_i \leftarrow m\,\operatorname{sgn}(u_i)$ for $i \in C$.
3. Free set $F = \{i \notin C : u_i \neq 0\}$. Room left: $R = G - \lVert\mathbf u\rVert_1$.
4. Scale the free names proportionally: $u_i \leftarrow u_i\left(1 + R / \sum_{j\in F}\lvert u_j\rvert\right)$ for $i \in F$.

Each pass either terminates or moves at least one name into $C$, so it ends in at most $N$ passes. The code caps the loop at 20. Signs are preserved, and so are relative weights within $F$. If $\lvert\{i: u_i\neq 0\}\rvert \cdot m < G$, the constraint can't be met at full gross; every name ends at $\pm m$ and the gross exposure shrinks. With a capped name kept in $C$ permanently, a later rescale can't push it back over $m$.

Because §9 later rescales the whole vector, the cap is applied again as a hard clip after leverage (§9.3).

## 8. Covariance estimation

On each rebalance date $t$, with lookback $L = 63$ (`Config.cov_lookback`), let $\mathbf{R} \in \mathbb{R}^{L\times N}$ hold the simple returns $r_{\cdot, t-L+1}, \dots, r_{\cdot,t}$, with missing values set to $0$. The sample covariance is

```math
\mathbf{S} = \frac{1}{L-1}\sum_{s=t-L+1}^{t} (\mathbf r_s - \bar{\mathbf r})(\mathbf r_s - \bar{\mathbf r})^\top .
```

With $N = 30$ and $L = 63$, $\mathbf{S}$ has $N(N+1)/2 = 465$ free parameters estimated from $63 \times 30 = 1890$ numbers. Its smallest eigenvalues are biased toward zero and its largest away from it (Marchenko–Pastur). Portfolios built on $\mathbf S$ inherit that error, so the engine shrinks it toward its diagonal:

```math
\hat{\mathbf\Sigma} = (1-\delta)\,\mathbf S + \delta\,\operatorname{diag}(\mathbf S), \qquad \delta = 0.3 .
```

This has the form of Ledoit–Wolf (2004) shrinkage toward a diagonal (zero-correlation) target, but it is **not** the Ledoit–Wolf estimator: Ledoit and Wolf estimate the intensity $\delta^\star$ from the data to minimize expected error, while this uses a fixed $\delta = 0.3$. It keeps every variance and multiplies every covariance by $1 - \delta$. Since $\hat{\mathbf\Sigma}$ is a convex combination of two positive semi-definite matrices, it is positive semi-definite, and positive definite whenever every asset has non-zero variance.

**Ceiling.** Pairwise correlations are pulled toward zero, so the diversification in a long-only book is somewhat overstated, and ex-ante volatility *underestimates* realized volatility. In the default backtest, a 12% target delivers about 15% realized. A factor risk model (§14) is the upgrade.

## 9. Volatility targeting and leverage

### 9.1 Ex-ante volatility

For a weight vector $\mathbf u$, the forecast annualized volatility is

```math
\hat\sigma_p(\mathbf u) = \sqrt{A\;\mathbf u^\top \hat{\mathbf\Sigma}\,\mathbf u}.
```

### 9.2 Scaling

`portfolio.vol_target` multiplies by a single scalar

```math
k = \min\!\left(\frac{\sigma^\star}{\hat\sigma_p(\mathbf u)},\; \frac{L_{\max}}{\lVert\mathbf u\rVert_1}\right),
\qquad \mathbf w = k\,\mathbf u,
```

with target $\sigma^\star$ (`target_vol`) and gross cap $L_{\max}$ (`max_leverage`). Scaling by a positive constant leaves the direction of the book unchanged, and $\hat\sigma_p$ is homogeneous of degree one ($\hat\sigma_p(k\mathbf u) = k\,\hat\sigma_p(\mathbf u)$), so unless the leverage cap binds, the forecast vol after scaling is exactly $\sigma^\star$. If $\hat\sigma_p = 0$, the book is set to zero.

Why target vol at all: realized volatility clusters (GARCH effects), so scaling exposure inversely to recent risk keeps the risk budget stable through regimes. Empirically it also tends to improve Sharpe ratios, because high-vol periods have historically had worse risk-adjusted returns (Moreira & Muir, 2017).

### 9.3 Hard per-name limit

Finally, $w_i \leftarrow \operatorname{clip}(w_i, -m, m)$. This is a NAV-relative limit that holds after leverage. It can only shrink positions. That lowers forecast volatility when every covariance in the book is non-negative, which holds for the long-only book in practice. In a long/short book, clipping one side can *raise* volatility by removing a hedge, and it breaks dollar-neutrality by the clipped amount.

### 9.3a What the vol target actually does in the live book

With the live settings (long-only, $m = 10\%$, top 30% of 30 names, so 9 names), the rank weights of §6.2 run from 2.2% to 20%. The cap binds on most names, and $9 \times 10\% = 90\% < 100\%$, so water-filling can't reach full gross: every name ends at 10%. **The live book is equal-weight across the top 9 with about 10% cash, by construction**, and the rank weighting has no effect. After that, the vol target can only scale *down*: scaling up would be undone by the hard clip at $m$. So in this configuration it works as a risk brake in volatile periods, not as a target. Raising $m$ (for example to 15%) or holding more names would let both mechanisms work; that is a strategy change and is tested in [RESEARCH.md §3](RESEARCH.md#3-walk-forward).

### 9.4 The full map

```math
\mathbf w_t = \operatorname{clip}_m\!\Big(k\cdot \operatorname{cap}_m\big(\mathbf u(\boldsymbol\alpha_t)\big)\Big),
```

which is `portfolio.target_weights` and is called through `backtest.targets_at` by both the backtest and the live job.

## 10. Timing and the no-look-ahead guarantee

Let $\tau$ be a rebalance signal date: the last trading day of each `Config.rebalance` period, after warm-up. With execution lag $\ell = 1$ (`execution_lag`):

| Time | Event |
|---|---|
| close of $\tau$ | $\boldsymbol\alpha_\tau$ and $\hat{\mathbf\Sigma}_\tau$ computed from $\mathcal F_\tau$; target $\mathbf w^\star$ fixed |
| close of $\tau + 1$ | trade from the drifted weights to $\mathbf w^\star$; pay costs |
| $\tau + 2$ onward | earn $\mathbf w^\top \mathbf r$ |

**Claim:** every quantity used to choose $\mathbf w^\star$ is $\mathcal F_\tau$-measurable.
Every factor in §3 uses $P_{i,s}$ for $s \le \tau$ only. §4 and §5 are per-day transformations, and §8 uses returns up to $\tau$. The code computes `alpha.iloc[i]` and `rets.iloc[i-L+1 : i+1]` with $i$ the signal row. $\square$

`tests/test_core.py::test_no_lookahead` checks this empirically. It multiplies every price after day $T$ by random noise and asserts that the return series up to $T$ is bit-identical. Any leak of future data, through a centred rolling window, a full-sample normalization or a shifted index, would fail it.

Executing one day after the signal is conservative compared with assuming a fill at the signal close. That would need the close price before the close happens.

## 11. Portfolio accounting: drift, turnover, costs

### 11.1 Weight drift

Between rebalances the book holds shares, not weights. If NAV-relative weights $\mathbf w_{t-1}$ are held over day $t$, the gross portfolio return is $g_t = \mathbf w_{t-1}^\top \mathbf r_t$, and the end-of-day weights are

```math
w_{i,t}^{-} = \frac{w_{i,t-1}\,(1 + r_{i,t})}{1 + g_t}.
```

*Derivation.* Position $i$'s value goes from $w_{i,t-1}V$ to $w_{i,t-1}V(1+r_{i,t})$, and NAV goes from $V$ to $V(1+g_t)$. Divide. Short positions work the same way ($w<0$).

**Cash earns the T-bill rate.** The residual $1 - \mathbf 1^\top\mathbf w_{t-1}$ earns the daily risk-free return $r^f_t = y_{t-1}/(100 \cdot 252)$, where $y$ is the 13-week T-bill yield in percent (Yahoo `^IRX`), lagged one day so it is known before it is earned:

```math
g_t = \mathbf w_{t-1}^\top \mathbf r_t + \left(1 - \mathbf 1^\top \mathbf w_{t-1}\right) r^f_t .
```

In a dollar-neutral book the short proceeds plus capital earn roughly $r^f$ on the full NAV, which this formula gives since $\mathbf 1^\top\mathbf w = 0$. There is no borrow fee. Note the live Alpaca account pays no interest on cash, so live results lag this assumption by about $r^f$ times the cash share.

### 11.2 Turnover and costs

On a trade day, the book jumps from the drifted $\mathbf w^-_t$ to the target $\mathbf w^\star$:

```math
\text{TO}_t = \lVert \mathbf w^\star - \mathbf w_t^- \rVert_1, \qquad
c_t = \text{TO}_t \cdot \frac{\kappa_{\text{comm}} + \kappa_{\text{slip}}}{10^4},
```

with commission $\kappa_{\text{comm}} = 2$ bps and slippage $\kappa_{\text{slip}} = 5$ bps per unit of notional traded. The net return is

```math
r^{\text{net}}_t = g_t - c_t .
```

Charging costs on the trade from *drifted* weights matters. Charging from the previous target would undercount turnover for names that moved a lot.

**Ceiling.** Linear costs are realistic only for trades that are small relative to volume. The standard improvement is the square-root impact law, $\text{cost}_i \approx \eta\,\sigma_i\sqrt{\lvert q_i\rvert / \text{ADV}_i}$, plus borrow fees on shorts.

### 11.3 Equity curve

```math
V_t = V_0 \prod_{s=1}^{t}\left(1 + r^{\text{net}}_s\right).
```

## 12. Performance and risk statistics

Implemented in `metrics.py`, computed from the first trade day onward. $\bar r$ and $s_r$ are the sample mean and standard deviation ($n-1$) of daily net returns, and $n$ is the number of days.

| Statistic | Definition | Notes |
|---|---|---|
| CAGR | $(V_n/V_0)^{A/n} - 1$ | geometric |
| Ann. vol | $s_r\sqrt{A}$ | assumes no autocorrelation |
| Sharpe | $\dfrac{\bar x}{s_x}\sqrt A$ with $x_t = r_t - r^f_t$ | excess of T-bills |
| Sharpe SE | $\sqrt{(1 + \widehat{SR}^2/2)/Y}$ | Lo (2002), $Y$ years |
| Sortino | $\dfrac{\bar x}{\mathrm{DD}}\sqrt A$, with $\mathrm{DD} = \sqrt{\tfrac1n\sum_t \min(x_t,0)^2}$ | downside deviation of excess returns, over all days |
| Drawdown | $D_t = V_t / \max_{s\le t} V_s - 1$ | |
| Max drawdown | $\min_t D_t$ | |
| Calmar | $\text{CAGR}/\lvert\min_t D_t\rvert$ | |
| VaR$_{95}$ | $-Q_{0.05}(r)$ | historical, 1-day, positive number = loss |
| CVaR$_{95}$ | $-\mathbb E[\,r \mid r \le Q_{0.05}(r)\,]$ | expected shortfall; always $\ge$ VaR |
| Beta | $\hat\beta = \dfrac{\widehat{\operatorname{Cov}}(r, r^B)}{\widehat{\operatorname{Var}}(r^B)}$ | OLS slope on the benchmark |
| Alpha (ann.) | $A\left(\bar x - \hat\beta\,\bar x^B\right)$ | Jensen's alpha on excess returns; $\hat\beta$ also on excess returns |
| Hit rate | share of non-zero days with $r_t > 0$ | |
| Ann. turnover | $\frac{A}{n}\sum_t \text{TO}_t$ | a value of $k$ means trading $k\times$ NAV a year |
| Cost drag | $\frac{A}{n}\sum_t c_t$ | return lost to costs per year |

**Annualization.** $A = 252$ for equities and $A = 365$ for crypto, which trades every day. The crypto sleeve's statistics use no risk-free rate.

**Annualizing by $\sqrt{A}$** assumes independent daily returns. With first-order autocorrelation $\rho$, the true annual volatility is about $\sqrt{A\,(1+\rho)/(1-\rho)}\;s_r$ (Lo, 2002).

**Risk on the terminal** (`terminal.risk_block`), for a sleeve with NAV $V$ and NAV-relative weights $\mathbf w$:

| Quantity | Definition |
|---|---|
| Forecast vol | $\sqrt{A\,\mathbf w^\top\hat{\mathbf\Sigma}\,\mathbf w}$ with the model's own shrunk covariance (§8) |
| Realized vol | standard deviation of $\mathbf r_s^\top \mathbf w$ over the same lookback, times $\sqrt A$: what today's book *would have* done |
| VaR 95% (normal) | $1.645\,\sqrt{\mathbf w^\top\hat{\mathbf\Sigma}\,\mathbf w}\;V$ |
| VaR 95% (history) | $-Q_{0.05}\big(\{\mathbf r_s^\top\mathbf w\}_{s \in \text{last year}}\big)\,V$, historical simulation of today's book |
| Beta | $\sum_i w_i \hat\beta_i$, one-year betas to SPY (equities) or Bitcoin (crypto) |
| Stress | $\beta \cdot \text{shock} \cdot V$ for SPX $-10\%$ or BTC $-20\%$ |
| Share of risk | $\dfrac{w_i (\hat{\mathbf\Sigma}\mathbf w)_i}{\mathbf w^\top\hat{\mathbf\Sigma}\mathbf w}$, which sums to 1 (Euler decomposition) |
| Sector exposure | $\sum_{i \in s} w_i$ per sector |
| Factor exposure | $E_k = \sum_i w_i z^{(k)}_i$ |

Forecast below realized means the covariance window was calmer than the year; the gap is worth watching.

## 13. Live execution

`live.py` turns target weights into orders once a day after the close. Signal generation calls the same `targets_at` as the backtest.

### 13.0 Sleeves

The account is split into an **equity sleeve** (this strategy) and a **crypto sleeve** (§16). **The equity strategy manages only the equity sleeve**: it sees only `us_equity` positions, never sells a coin, and sizes from the equity sleeve's NAV, not the whole account. With account equity $E$, the crypto sleeve's NAV $V^c$ and the equity sleeve's NAV $V^e$ are

```math
V^c = M^c + C^c, \qquad C^c = B - M^c_0 - \sum_{f \in \mathcal F^c} q_f P_f, \qquad V^e = E - V^c,
```

where $M^c$ is the crypto market value, $B$ the crypto budget, $M^c_0$ the crypto market value when the sleeve started, and the sum runs over every crypto fill since then (signed quantity times fill price, read back from the broker). So the crypto sleeve starts with $B$ and then moves only with its own P&L; fees paid in coin show up as a smaller $M^c$. With the crypto sleeve off, $V^e = E - M^c$, so coins held by hand still never inflate stock sizing. Each sleeve has its own high-water mark, drawdown halt and kill file (`state/KILL`, `state/KILL_CRYPTO`); a halt flattens only that sleeve.

### 13.1 Signal calendar

$\tau$ is a signal day if it is the last trading day of its month (approximated with the US federal holiday calendar) and no signal has been generated this month. If a month-end is missed, for example through a failed run or an NYSE-only holiday, the first run at least two calendar months after the last signal catches up.

### 13.2 Order sizing

With sleeve NAV $V$, cash buffer $b$ (0 for equities, 2% for crypto), price $P_i$, current units $q_i$ and target weight $w^\star_i$:

```math
q^\star_i = \operatorname{trunc}\!\left(\frac{w_i^\star (1-b) V}{P_i}\right), \qquad \Delta_i = q_i^\star - q_i ,
```

where trunc is to whole shares for equities and to $10^{-6}$ for crypto. The buffer exists because a crypto purchase needs settled cash: sizing to exactly $V$ would leave fees with nowhere to come from, and the broker would reject the last buy.

Truncation toward zero means the book never exceeds its target in absolute terms. The rounding error per name is under one share, so the weight error is $\lvert w_i - w^\star_i\rvert < P_i/V$; for a \$600 stock in a \$100k account that is 0.6%.

Filters, applied in this order:

1. **Dust:** skip if $\lvert\Delta_i P_i\rvert$ is below `min_trade_notional`, unless the target is zero (full closes always go through).
2. **Fat-finger cap:** $\lvert\Delta_i\rvert \le \lfloor N^{\max}/P_i\rfloor$ with $N^{\max}$ = `max_order_notional`. A capped name converges to target over several rebalances.
3. **Sign-flip split:** if $q_i$ and $q_i + \Delta_i$ have opposite signs, send two orders, $-q_i$ and then $q_i+\Delta_i$, because brokers reject a single order that flips a position.
4. **Ordering:** sells before buys, sorted by signed notional, so sale proceeds fund the purchases.

### 13.3 Fills

- **Simulator** (`SimBroker`): the order queued on signal day $\tau$ fills at the close of the next run day $\tau + 1$, at $P(1 \pm \kappa_{\text{slip}})$ plus commission $\kappa_{\text{comm}}\lvert qP\rvert$. That reproduces the backtest's timing (§10) exactly.
- **Alpaca equities:** market, time-in-force *day*, submitted after the close, so they fill at the next open. This is about half a day earlier than the backtest assumes. Each fill is compared with the price at signal time and the average slippage is shown on the blotter, next to the cost the backtest assumes.
- **Alpaca crypto:** market, time-in-force *gtc*, fractional quantities, filled immediately (24/7).
- **Idempotency.** Every order carries a deterministic client id, `af-{sleeve}-{date}-{rb|sw|kl}-{symbol}-{n}`. A retried run produces the same ids, the broker rejects the duplicates, and nothing is sent twice. Before a rebalance the job cancels only *its own* open orders from earlier days in that sleeve's asset class; orders placed by hand are never touched.

### 13.4 Two-week swap of the worst performers

Between month-end rebalances the book is reviewed every $S$ trading days (`swap_every`, 10 in `live.json`), counted from the last rebalance or swap. With long holdings $\mathcal H$, entry (average) price $\bar P_i$ and current price $P_i$, the P&L since entry is $\pi_i = P_i/\bar P_i - 1$. Let $h_{(1)}, \dots, h_{(k)}$ be the $k$ holdings with the lowest $\pi$ (`swap_count`, 2), worst first, and let $c_{(1)}, c_{(2)}, \dots$ be the names *not* held, ranked by today's alpha. The rule pairs $h_{(j)}$ with $c_{(j)}$ and keeps a pair only if

```math
\alpha_{c_{(j)}} > \alpha_{h_{(j)}},
```

so the book never swaps into a name the model rates below the one it sells. Kept pairs are executed by selling $h_{(j)}$ entirely and splitting the proceeds evenly across the incoming names, so gross exposure is unchanged up to share rounding. Every other position is left as it is; the next month-end rebalance resizes the whole book. `portfolio.pick_swaps` implements the selection for both the backtest and the live job, with the same one-day lag as full rebalances.

Selling on P&L since entry is path-dependent (it depends on when each name was bought), so it is not a cross-sectional signal like §3. It works as a disciplined loss-cutting overlay, with alpha deciding the replacements. In the default backtest (long-only, 2015 to 2026) it changed results from Sharpe 1.14 / CAGR 17.8% / turnover 6.8× to Sharpe 1.17 / CAGR 18.3% / turnover 9.3×. That improvement is well inside one standard error (§14).

### 13.5 Risk controls

The high-water mark is $H_t = \max_{s\le t} V_s$. The job flattens the book and writes a `state/KILL` file when

```math
\frac{V_t}{H_t} - 1 < -d_{\max},
```

with $d_{\max}$ = `max_drawdown_halt` (20% equities, 50% crypto, set beyond each backtest's worst drawdown so normal swings don't trip it). Trading resumes only after a person deletes that file. The terminal shows how much of the distance to the halt has been used. Halts, rejected orders and broker cancellations are written to `alerts.txt`, and the GitHub job fails on them, which emails the repository owner. The job also halts on `ALPHAFORGE_KILL=1` (all sleeves) or `ALPHAFORGE_KILL=equity` / `crypto` (one sleeve), and it refuses to trade on prices older than `max_data_age_days`. Real-money trading needs both `"live_money": true` in `live.json` **and** `ALPHAFORGE_CONFIRM_LIVE=yes` in the environment.

Optionally, every rebalance and swap can wait for a person's approval, and every trading run is written to an audit log ([§17.6](#176-approval-audit-permissions)).

## 14. Statistical caveats

**Standard error of the Sharpe ratio.** For iid returns over $Y$ years, $\operatorname{SE}(\widehat{SR}) \approx \sqrt{(1 + \widehat{SR}^2/2)/Y}$ (Lo, 2002). Over 11.7 years with $\widehat{SR} = 0.2$, the SE is about 0.30, so the market-neutral book's Sharpe ratio isn't distinguishable from zero. At $\widehat{SR} = 1.1$, SE ≈ 0.37, which is significant but wide.

**Multiple testing.** Every slider setting tried on the dashboard is an implicit trial. The expected maximum Sharpe ratio across $M$ independent trials of a zero-skill strategy grows like $\sqrt{2\ln M}\cdot\operatorname{SE}$. The deflated Sharpe ratio (Bailey & López de Prado, 2014) corrects for this. Treat any configuration found by searching as in-sample until a walk-forward test confirms it.

**Survivorship bias.** `DEFAULT_UNIVERSE` is a list of today's mega caps. Run back to 2014, it selects on the outcome: these firms are large *because* they went up. Long-only results are inflated by an amount that can't be measured without point-in-time constituents. Cross-sectional (long/short) results are less exposed, since everyone in the universe shares the bias, but they still are exposed.

**Regime dependence.** Momentum suffers sharp crashes in rebounds after bear markets (Daniel & Moskowitz, 2016: 2009 is the textbook case). Twelve years of data contain only a handful of such episodes.

**What the research found** ([RESEARCH.md](RESEARCH.md)). Momentum is the only factor with a positive rank IC here ($t \approx 2.2$ at 63 days). Reversal has none and causes most of the turnover; low volatility is significantly negative. Walk-forward, out of sample, the Sharpe ratio is about 0.96. No setting in the 20-setting grid beats an equal-weight portfolio of the same 30 names on raw returns; adjusted for its lower beta, the live strategy adds about 2% a year, which is not statistically distinguishable from zero.

**Upgrade path,** in order of value: point-in-time universe → walk-forward validation → factor risk model with optimizer ($\max_{\mathbf w}\,\boldsymbol\alpha^\top\mathbf w - \tfrac{\gamma}{2}\mathbf w^\top\mathbf\Sigma\mathbf w - \tau\lVert\mathbf w - \mathbf w_0\rVert_1$ subject to sector and beta neutrality) → square-root impact costs.

## 15. Parameter reference

| Parameter | Default | Where |
|---|---|---|
| Momentum lookback / skip | 252 / 21 days | `signals.momentum` |
| Reversal lookback | 5 days | `signals.reversal` |
| Low-vol lookback | 63 days | `signals.low_vol` |
| Trend-quality lookback | 126 days | `signals.quality_trend` |
| Winsorization | ±3 σ | `signals.cs_zscore` |
| Factor weights $\lambda$ | 0.4 / 0.2 / 0.2 / 0.2 | `Config.factor_weights` |
| Long-only top fraction | 30% | `portfolio.alpha_to_weights` |
| Covariance lookback $L$ | 63 days | `Config.cov_lookback` |
| Shrinkage $\delta$ | 0.3 | `portfolio.target_weights` |
| Target vol $\sigma^\star$ | 10% (12% in `live.json`) | `Config.target_vol` |
| Max weight $m$ | 10% | `Config.max_weight` |
| Max gross $L_{\max}$ | 2.0 (1.0 in `live.json`) | `Config.max_leverage` |
| Execution lag $\ell$ | 1 day | `Config.execution_lag` |
| Costs | 2 + 5 bps | `Config.cost_bps`, `slippage_bps` |
| Rebalance | month-end | `Config.rebalance` |
| Drawdown halt $d_{\max}$ | 20% equities, 50% crypto | `live.json` |
| Risk-free rate | 13-week T-bill (`^IRX`), lagged a day | `data.risk_free` |
| Crypto budget $B$ | \$10,000 | `live.json` → `crypto.budget` |
| Swap interval $S$ / count $k$ | 10 trading days / 2 names | `Config.swap_every`, `swap_count` |
| Approval before trading | off | `live.json` → `require_approval` |
| **Desk analytics (§17)** | | |
| Risk-model universe | strategy names + watchlist (S&P 100) | `terminal.equity_page` |
| Risk-model window / EWMA half-life | 252 days (crypto 365) / 90 days | `analytics.risk_model` |
| Sector constraint weight | $10^3$ (sum of sector returns = 0) | `analytics.risk_model` |
| Active-risk benchmark | equal weight of the 30 names; crypto: 100% BTC | `terminal.equity_page`, `crypto_page` |
| ADV window / participation | 20 days / 10% | `terminal._adv_usd`, `analytics.liquidity`, `capacity` |
| Traffic lights | green $u<0.9$, amber $0.9\le u<1$, red $u\ge1$ | `analytics.light` |
| Soft limits (equities) | sector 40%, beta 1.2, VaR 2.5% of NAV, TE 12%, vol 1.5×target, 1 day to exit | `terminal.LIMITS` |
| Soft limits (crypto) | beta to BTC 1.5, VaR 8% of NAV, vol 1.5×target, 1 day to exit | `terminal.LIMITS` |
| Position-limit drift tolerance | 1.2 × `max_weight` | `terminal.LIMITS` |
| IC horizons | 1, 5, 21, 63 days (crypto 1, 7, 30, 90) | `analytics.signal_ic` |
| Crowding window / history | 63 days / 36 month-ends | `analytics.crowding` |
| Factor shock | 3σ over 21 days | `terminal.desk_block` |
| Corporate-action flag | daily move > 25% (crypto 50%) in 10 sessions | `analytics.data_health` |

## 16. The crypto sleeve

A separate strategy with its own budget, NAV and kill switch (§13.0), shown on its own terminal page.

**Signal: time-series trend.** For each coin, with log price $p$,

```math
\tau_{i,t} = \frac{1}{3}\sum_{n \in \{20,\,60,\,120\}} \operatorname{sgn}\!\left(p_{i,t} - p_{i,t-n}\right) \in \{-1, -\tfrac13, \tfrac13, 1\}.
```

Unlike §4 this is *not* cross-sectional: each coin is judged against its own past, so every coin can be in a downtrend at once, and then the sleeve holds cash. Trend persistence at these horizons is documented across asset classes (Hurst, Ooi & Pedersen, 2017) and in crypto specifically (Liu & Tsyvinski, 2021).

**Weights.** Long only (spot crypto can't be shorted on Alpaca), in proportion to positive trend and inverse volatility:

```math
u_i = \frac{\max(\tau_i, 0)/\hat\sigma_i}{\sum_j \max(\tau_j, 0)/\hat\sigma_j}, \qquad \hat\sigma_i = \text{60-day std of daily returns},
```

then the same pipeline as equities: cap at 35% per coin (§7), scale to a 25% annual vol target on the shrunk 60-day covariance (§8–9), gross capped at 100%, hard clip at 35%.

**Schedule and costs.** Rebalanced every 7 days on complete daily (UTC) bars; today's still-forming bar is dropped. Costs are 25 bps (Alpaca's taker fee) plus 10 bps slippage. Annualization uses 365 days.

**Evidence** ([RESEARCH.md §6](RESEARCH.md#6-crypto-trend-sleeve)). From 2019, the trend sleeve had a Sharpe ratio of about 1.0 against 0.9 for holding Bitcoin, within one standard error ($\approx 0.45$), and a maximum drawdown near $-48\%$ against $-77\%$. Its case is drawdown control, not a higher Sharpe ratio. The 8 coins are today's survivors, so the backtest is biased upward like the equity one.

## 17. Desk analytics

Code: [`alphaforge/analytics.py`](../alphaforge/analytics.py). These numbers describe the book; none of them feed back into the trading decisions.

### 17.1 Factor risk model

A cross-sectional model in the style of Barra, fitted on the S&P 100 (the strategy's 30 names plus the watchlist), one regression per day over the last 252 days:

$$r_{i,t} = f^{\text{mkt}}_t + \sum_{s} D_{i,s}\, f^{s}_t + \sum_{k} z_{i,k,t-1}\, f^{k}_t + \varepsilon_{i,t}, \qquad \text{subject to } \sum_s f^s_t = 0$$

$D_{i,s}\in\{0,1\}$ is the sector dummy and $z_{i,k,t-1}$ the style z-score (momentum, reversal, low volatility, trend quality, §3–4) known at the prior close. The intercept and the sector dummies are collinear; the sum-to-zero constraint (added as a heavily weighted extra row of the least-squares system) makes $f^{\text{mkt}}_t$ the return of the average stock and $f^s_t$ each sector's return relative to it.

The factor covariance $F$ and the specific variances $\delta_i^2$ are exponentially weighted with a 90-day half-life, $w_t \propto 2^{-(T-t)/90}$:

$$F = \sum_t w_t (f_t-\bar f)(f_t-\bar f)^\top, \qquad \delta_i^2 = \sum_t w_t\, \varepsilon_{i,t}^2$$

For weights $w$, the exposures are $x = X^\top w$ (with $X$ today's exposure matrix) and the forecast variance is

$$\sigma^2 = x^\top F x + \sum_i w_i^2 \delta_i^2 .$$

**Decomposition (Euler).** Factor $k$'s share of variance is $x_k (Fx)_k / \sigma^2$; the shares of all factors plus the specific share $\sum_i w_i^2\delta_i^2/\sigma^2$ add up to one. Grouping factors gives Market / Sector / Style / Specific. Name $i$'s share is $w_i(\Sigma w)_i/\sigma^2$ with $\Sigma = XFX^\top + \operatorname{diag}(\delta^2)$; these also add up to one.

**Active risk.** The same decomposition applied to $w - b$, where $b$ is the benchmark (equal weight of the 30 names for stocks, 100% bitcoin for crypto), gives the forecast tracking error $\sqrt{(w-b)^\top\Sigma(w-b)\cdot 252}$ and its sources.

The crypto sleeve uses the one-factor version (intercept only): the crypto market and coin-specific risk.

### 17.2 P&L attribution

With the backtest's end-of-day weights $w_{t-1}$, the day's book return on stocks is exactly

$$\sum_i w_{i,t-1} r_{i,t} = \underbrace{\sum_k (X_t^\top w_{t-1})_k f^k_t}_{\text{market + sector + style}} + \underbrace{\sum_i w_{i,t-1}\varepsilon_{i,t}}_{\text{specific}}$$

because the residuals are defined by the same regression. Adding cash $(1-\sum_i w_{i,t-1})\,r^f_t$ and subtracting costs gives the strategy's net return, so the parts add up to the total with no residual (a test checks this). Contributions are summed arithmetically over the window (not compounded), and per name as $\sum_t w_{i,t-1} r_{i,t}$.

**Against a benchmark.** With active return $a_t = r_t - r^b_t$: tracking error $\mathrm{TE} = \operatorname{sd}(a)\sqrt{A}$, annual active return $\bar a A$, information ratio $\mathrm{IR} = \bar a A / \mathrm{TE}$ ($A$ = 252 or 365).

### 17.3 Stress, liquidity, limits

**Historical replay.** For a window $[t_0, t_1]$ (COVID crash, Q4 2018, 2022 rates, Aug 2024, Apr 2025; for crypto, the 2021 crash, Terra/LUNA, FTX and others), the book's move is $\sum_i w_i (P_{i,t_1}/P_{i,t_0} - 1)$ on today's weights. A name with no price at $t_0$ is proxied by $\beta_i \times$ the benchmark's move.

**Factor shocks.** Style factor $k$ moved 3 standard deviations over a month against the book: P&L $= -\operatorname{sign}(x_k)\, 3\sqrt{21 F_{kk}}\; x_k \cdot \text{NAV}$.

**Days to exit.** Position $i$ needs $|MV_i| / (0.10 \cdot \mathrm{ADV}_i)$ days when trading at most 10% of its 20-day average dollar volume.

**Limits.** Utilization $u = |\text{value}|/\text{limit}$: green below 0.9, amber from 0.9 to 1, red at 1 or more. Hard limits are enforced by the trading job (order size, position cap at trade time, gross exposure, drawdown halt); soft limits (forecast volatility, beta, largest sector, VaR, tracking error, days to exit) are monitored and raise an alert on the terminal.

### 17.4 Transaction cost analysis

Implementation shortfall (Perold 1988) against the decision price $P_d$ (the signal close), split at the arrival price $P_a$ (the open of the fill day) for stocks, with side $s=\pm1$:

$$\underbrace{s\left(\tfrac{P_f}{P_d}-1\right)}_{\text{total}} \approx \underbrace{s\left(\tfrac{P_a}{P_d}-1\right)}_{\text{delay}} + \underbrace{s\left(\tfrac{P_f}{P_a}-1\right)}_{\text{impact}}$$

in basis points, positive = cost. Participation is shares filled divided by the day's volume. Fill rate is filled over ordered quantity across finished orders. Averages are notional-weighted.

### 17.5 Signal diagnostics

**IC and decay.** At each month-end $m$, the rank IC is the Spearman correlation between the score $z_{\cdot,m}$ and the forward return $P_{\cdot,m+h}/P_{\cdot,m}-1$ across names, for $h \in \{1, 5, 21, 63\}$ days. The table reports the mean IC, $t = \overline{IC}/\operatorname{sd}(IC)\cdot\sqrt{n}$ and the hit rate. Reading across horizons shows the decay. The crypto trend signal has only 8 coins, so its IC is pooled across coins and month-ends, with the sample size shrunk to $n\cdot\min(1, \Delta/h)$ when the horizon $h$ is longer than the sampling step $\Delta$ (overlapping windows are not independent).

**Signal correlation.** The average rank correlation between signals at month-ends over 3 years.

**Crowding.** Co-movement of the top third of names by each signal (Lou & Polk's comomentum): the average pairwise correlation of their market-adjusted daily returns over 63 days, shown now and as a percentile of its last 3 years. A high percentile means the names trade as one block, as they do when many funds hold them.

**Capacity.** With $\overline{|\Delta w_i|}$ the average trade in name $i$ per rebalance, the AUM at which no name needs more than 10% of its ADV in a day is $\min_i 0.10\,\mathrm{ADV}_i / \overline{|\Delta w_i|}$.

### 17.6 Approval, audit, permissions

With `"require_approval": true` in `live.json` (or under `"crypto"`), a due rebalance or swap is not traded: the sleeve records `awaiting`, raises one alert and checks again every run, so a month-end rebalance is not lost. A run with `ALPHAFORGE_APPROVE=equity|crypto|all` (the workflow's *approve* input) executes it. Every trading run appends to `state/audit.jsonl` (time, GitHub actor, trigger, run id, commit, events, order count, alerts) and alerts to `state/alerts.jsonl`, both committed with the state.

The approval gate, per sleeve and per run (`live.step_sleeve`):

```
due_rebalance = signal_due(today) or awaiting.kind == "rebalance"
due_swap      = not due_rebalance and swap_due(today)
if (due_rebalance or due_swap) and require_approval and ALPHAFORGE_APPROVE not in {sleeve, "all"}:
    if awaiting.kind changed: raise one alert
    awaiting = {kind, since}            # last_signal / last_swap are NOT advanced
else if due_rebalance or due_swap:
    awaiting = none; trade as usual (logged as "approved by <GitHub user>" when approval was required)
```

Because `last_signal` is not advanced while waiting, a month-end rebalance approved days later still runs with that day's data, and a swap stays due until it is approved. Permissions are GitHub's: only the Actions job holds the broker keys, and only collaborators with write access can start a run with *approve*.

### 17.7 Next-trade preview

`terminal.preview_block` runs the trading job's own functions on today's data, without sending anything:

1. Targets $w^\star$ = `targets_at(alpha, returns, today)`, exactly as a signal day would compute them.
2. Orders = `plan_orders(w*, positions, NAV, prices, sleeve config)`: the same truncation, dust filter, fat-finger cap, sign-flip split, ordering and crypto cash buffer as §13.2.
3. Swap (equities) = `pick_swaps(P&L since entry, alpha, k)` then `swap_orders(...)`, as in §13.4.
4. For each order list: buys $\sum_{\Delta>0}\Delta P$, sells, turnover $\sum|\Delta P|/V$, estimated cost $\sum|\Delta P|\,(\kappa_{\text{comm}}+\kappa_{\text{slip}})$, and the post-trade book: gross $\sum|w|$, largest weight, largest sector, number of names. An order cut to `max_order_notional` is flagged *capped*.

**Dates.** The next rebalance for equities is the first business day $d$ (federal calendar, as in §13.1) with $d+1$ in a new month and $\text{month}(d) \ne \text{month}(\text{last signal})$. The next swap check is the later of the last rebalance or swap plus $S$ weekdays: the job counts trading days in the price data, which plain weekdays match better than the federal calendar (NYSE is open on Columbus and Veterans Day). For crypto it is the last signal plus 7 days, rolled forward to a weekday because the job only runs Monday to Friday. Before a sleeve's first signal both read "next trading run". The real run trades at that day's close, so quantities will differ from the preview by that day's price moves.

### 17.8 Data health checks

`analytics.data_health` runs on every build. Each check is ok, warn or fail:

| Check | Rule |
|---|---|
| Price history fresh | business days between the latest close and the expected one: 0 ok, 1 warn, more fail. Expected = today once NYSE has opened on a trading day, else the previous trading day; for crypto, yesterday (UTC), because today's bar is still forming |
| Quotes complete | every shown symbol's last quote date equals the latest close, else warn with the laggards |
| No missing prices | every strategy name has a finite price on the latest row, else fail |
| No stale prices | no strategy name has an unchanged close for 6 rows, else warn |
| Corporate actions / bad ticks | no daily move above 25% (crypto 50%) in 10 sessions, else warn with the date and size. Prices are split- and dividend-adjusted by Yahoo, so a flagged jump is either real news or a data error |
| Positions reconcile to fills | each broker position matches the quantity rebuilt from the full fill history (§13.3) within 3% (crypto fees are paid in coin), else warn |
| Cash + positions = equity | Alpaca only: $|E - C - \sum MV| \le 0.5\% \cdot E$ |
| No stuck orders | no order still open (new, accepted, partially filled, held) after one day |
| Trading job ran | last trading run within 4 days (covers weekends and one holiday) |

The browser adds two live checks: the terminal data's age (ok under 45 minutes, or under 3 days while NYSE is closed, because the refresh only runs in market hours) and the live feed's last tick (ok under 60 seconds, or anytime while NYSE is closed). A failing check is also listed under Alerts.

## References

- Ang, A., Hodrick, R., Xing, Y. & Zhang, X. (2006). The cross-section of volatility and expected returns. *Journal of Finance* 61(1).
- Baker, M., Bradley, B. & Wurgler, J. (2011). Benchmarks as limits to arbitrage: understanding the low-volatility anomaly. *Financial Analysts Journal* 67(1).
- Bailey, D. & López de Prado, M. (2014). The deflated Sharpe ratio. *Journal of Portfolio Management* 40(5).
- Da, Z., Gurun, U. & Warachka, M. (2014). Frog in the pan: continuous information and momentum. *Review of Financial Studies* 27(7).
- Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2).
- DeMiguel, V., Garlappi, L. & Uppal, R. (2009). Optimal versus naive diversification. *Review of Financial Studies* 22(5).
- Frazzini, A. & Pedersen, L. (2014). Betting against beta. *Journal of Financial Economics* 111(1).
- Hurst, B., Ooi, Y. H. & Pedersen, L. (2017). A century of evidence on trend-following investing. *Journal of Portfolio Management* 44(1).
- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance* 48(1).
- Ledoit, O. & Wolf, M. (2004). Honey, I shrunk the sample covariance matrix. *Journal of Portfolio Management* 30(4).
- Lehmann, B. (1990). Fads, martingales, and market efficiency. *Quarterly Journal of Economics* 105(1).
- Grinold, R. & Kahn, R. (2000). *Active Portfolio Management*, 2nd ed. McGraw-Hill.
- Lo, A. (2002). The statistics of Sharpe ratios. *Financial Analysts Journal* 58(4).
- Lou, D. & Polk, C. (2022). Comomentum: inferring arbitrage activity from return correlations. *Review of Financial Studies* 35(7).
- Menchero, J., Orr, D. & Wang, J. (2011). The Barra US equity model (USE4): methodology notes. MSCI.
- Perold, A. (1988). The implementation shortfall: paper versus reality. *Journal of Portfolio Management* 14(3).
- Liu, Y. & Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *Review of Financial Studies* 34(6).
- Moreira, A. & Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance* 72(4).
