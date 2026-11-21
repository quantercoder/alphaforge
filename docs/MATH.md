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
17. [Desk analytics](#17-desk-analytics): factor risk model, attribution, stress, liquidity, limits, TCA, signal diagnostics, approval and audit, next-trade preview, data health, paper against backtest, forecasts
18. [The Lab](#18-the-lab): multi-model forecasts, strategy lab, VaR methods, portfolio construction, leverage and sizing

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

**Live weights: momentum only.** Since October 2026 `live.json` sets $\lambda = (1, 0, 0, 0)$: momentum only. The four-factor blend had no predictive power on these 30 names (rank IC ≈ 0.01, $t \approx 0.6$) because low volatility predicts *backwards* here ($t \approx -4.7$) and reversal predicts nothing. Low volatility is dropped rather than flipped: "buy high volatility" would fit the survivorship bias of a universe built from today's winners. Trend quality could join only if its own IC reached $t \ge 2$; it didn't ($t \approx 0.9$). Choosing momentum after looking at the IC table is data snooping, so it was tested under rules written down first ([PREREGISTRATION.md](PREREGISTRATION.md)). The verdict was **no demonstrated edge over equal weight** ([RESEARCH.md §7](RESEARCH.md#7-pre-registered-edge-test)). Momentum is kept because it is the only factor with support in this sample and decades of out-of-sample evidence elsewhere, not because this test proved it.

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

### 9.5 Constrained construction (optimizer)

When `max_sector`, `max_beta` or `turnover_penalty` is set (all three are in `live.json`), the weights $\mathbf w^\star$ of §9.4 become a *target*, and `portfolio.optimize` finds the closest portfolio that respects the limits:

```math
\min_{\mathbf w}\; (\mathbf w - \mathbf w^\star)^\top \mathbf S\, (\mathbf w - \mathbf w^\star) + \tau \lVert \mathbf w - \mathbf w_0 \rVert_1
\quad\text{s.t.}\quad
0 \le w_i \le m,\;\; \mathbf 1^\top\mathbf w \le L_{\max},\;\; \sum_{i \in s} w_i \le c_{\text{sec}}\;\forall s,\;\; \boldsymbol\beta^\top \mathbf w \le c_\beta
```

- $\mathbf S = 252\,\hat{\mathbf\Sigma}$ is the annualized shrunk covariance of §8, so the objective is the squared tracking error to the target.
- $\mathbf w_0$ is today's book (drifted weights in the backtest, actual positions in the live job).
- $\tau$ (`turnover_penalty`, 0.001) is the price of one unit of turnover in units of annual tracking variance. A 1% move in a 30%-volatility stock reduces tracking variance by about $0.01^2 \times 0.3^2 \approx 10^{-5}$ and costs $\tau \times 0.01 = 10^{-5}$, so moves of about 1% or less are not worth making: a no-trade band.
- $\beta_i$ is name $i$'s beta to the equal-weighted universe over the last 252 days; $c_\beta$ = `max_beta` (1.2), $c_{\text{sec}}$ = `max_sector` (0.40). Names in sector "Other" (unknown) have no sector limit. Names with no alpha get $w_i = 0$.

Optimizing toward $\mathbf w^\star$ instead of $\max \boldsymbol\alpha^\top\mathbf w - \gamma\,\mathbf w^\top\mathbf\Sigma\mathbf w$ avoids putting $\alpha$ (a z-score) and risk on one scale, which would need an IC × volatility conversion this strategy hasn't earned (§14). The result: a book as close as possible to what the simple rules want, moved only as far as the limits require. Because $\mathbf w^\star$ is already volatility-targeted and every constraint is an upper bound, there is no rescaling afterwards.

**Quadratic program.** With $\mathbf t \ge |\mathbf w - \mathbf w_0|$ as extra variables, $\mathbf x = (\mathbf w, \mathbf t)$:

```math
\min_{\mathbf x}\; \tfrac12 \mathbf x^\top \mathbf P \mathbf x + \mathbf q^\top \mathbf x
\quad\text{s.t.}\quad \mathbf l \le \mathbf A \mathbf x \le \mathbf u,
\qquad
\mathbf P = \begin{pmatrix} 2\mathbf S & 0 \\ 0 & \epsilon \mathbf I\end{pmatrix},\;
\mathbf q = \begin{pmatrix} -2\mathbf S \mathbf w^\star \\ \tau \mathbf 1\end{pmatrix}
```

The rows of $\mathbf A$ are the box, the budget, one row per sector, the beta row, and $\mathbf w + \mathbf t \ge \mathbf w_0$, $\mathbf w - \mathbf t \le \mathbf w_0$. `portfolio.solve_qp` solves it with the ADMM iteration used by OSQP (Stellato et al., 2020), with $\rho = 0.5$, $\sigma = 10^{-6}$ and over-relaxation $\alpha = 1.6$:

```math
\begin{aligned}
\tilde{\mathbf x} &= (\mathbf P + \sigma \mathbf I + \rho \mathbf A^\top\mathbf A)^{-1}\big(\sigma \mathbf x^k - \mathbf q + \mathbf A^\top(\rho \mathbf z^k - \mathbf y^k)\big), \qquad \tilde{\mathbf z} = \mathbf A\tilde{\mathbf x} \\
\mathbf x^{k+1} &= \alpha\tilde{\mathbf x} + (1-\alpha)\mathbf x^k, \qquad
\mathbf z^{k+1} = \Pi_{[\mathbf l,\mathbf u]}\big(\alpha\tilde{\mathbf z} + (1-\alpha)\mathbf z^k + \mathbf y^k/\rho\big) \\
\mathbf y^{k+1} &= \mathbf y^k + \rho\big(\alpha\tilde{\mathbf z} + (1-\alpha)\mathbf z^k - \mathbf z^{k+1}\big)
\end{aligned}
```

It stops when the primal residual $\lVert\mathbf A\mathbf x - \mathbf z\rVert_\infty$ and the dual change $\rho\lVert \mathbf z^{k+1} - \mathbf z^k\rVert_\infty$ are both below $10^{-8}$. The matrix is inverted once per problem (at most 60 variables here). Last-digit violations are then repaired: clip to the box, and if a limit row still exceeds its bound, scale the book down by bound ÷ value. Scaling down can't break any other limit, because they are all upper bounds on non-negative weights. A test checks the solver against a known closed-form answer (projection onto a capped simplex).

**Timing.** In the backtest the target is now computed inside the daily loop at the signal close, so $\mathbf w_0$ is the drifted book at that moment. It still uses only data up to that close; the no-look-ahead test runs with the optimizer on.

**Swaps.** The two-week swap (§13.4) isn't optimized, but it is sector-aware: a candidate is skipped if its sector, after taking the dropped name's weight, would exceed `max_sector`. A swap never *trims* a sector that drifted over the cap since the last rebalance; the next rebalance does.

**Effect** ([RESEARCH.md §8](RESEARCH.md#8-constrained-construction-optimizer)). Same Sharpe ratio; the worst sector weight on a trade day falls from 53% to 43% (every rebalance ends at or under 40%; the excess is drift on swap days); turnover falls from 5.7× to 3.6× a year. It controls where the risk sits. It doesn't create an edge.

### 9.6 GARCH(1,1) volatility (live since November 2026)

With `vol_model: "garch"` the volatility target of §9.2 uses forecast volatilities instead of the 63-day sample. Returns are close to unpredictable, but volatility clusters: a volatile day tends to be followed by another (Engle 1982). GARCH(1,1) (Bollerslev 1986) models the conditional variance $h_t$ of a stock's daily return $r_t$ (demeaned over the fitting window) as

```math
h_t = \omega + a\, r_{t-1}^2 + b\, h_{t-1}, \qquad \omega = s^2 (1 - a - b), \qquad a, b \ge 0,\; a + b < 1,
```

with **variance targeting** (Engle & Mezrich 1996): $s^2$ is the sample variance of the window, so the long-run variance equals it and only $a$ (reaction to news) and $b$ (persistence) are estimated. They maximize the Gaussian log-likelihood

```math
\ell(a, b) = -\tfrac12 \sum_t \left(\ln h_t + \frac{r_t^2}{h_t}\right), \qquad h_1 = s^2,
```

over a grid ($a \in \{0.01, \dots, 0.25\}$, $b \in \{0.60, \dots, 0.99\}$, step 0.01, $a + b < 0.999$), evaluated for all stocks at once (`vol.garch_fit`). A grid is exact to its step and can't fail to converge. A test checks that it recovers known parameters from simulated GARCH data to within 0.02–0.04.

The forecast of the average daily variance over the next $H = 21$ days follows from the recursion's mean reversion:

```math
h_{T+k} = s^2 + (a+b)^{k-1}\,\big(h_{T+1} - s^2\big), \qquad \bar h_H = \frac1H \sum_{k=1}^{H} h_{T+k}.
```

Each stock is refitted at every rebalance on the prior 756 days (at least 500; otherwise the sample volatility is used). The covariance is the **constant-correlation** form (Bollerslev 1990): $\Sigma = D\,\tilde C\,D$ with $D = \operatorname{diag}(\sqrt{\bar h_H})$ and $\tilde C$ the 252-day sample correlation shrunk 30% toward the identity. It feeds §9.2's scaling; the optimizer (§9.5) still measures tracking error with the sample covariance.

**Why it was adopted** ([RESEARCH_3.md](RESEARCH_3.md), rules pre-registered in [PREREGISTRATION_3.md](PREREGISTRATION_3.md)). Out of sample, 11,654 forecasts of 21-day variance on 101 stocks at every month-end from 2016, each GARCH fitted on the prior three years only:

| | QLIKE | Mincer-Zarnowitz $R^2$ | 68% range coverage |
|---|---|---|---|
| 63-day sample | 0.473 | 0.13 | 67% |
| GARCH(1,1) | 0.371 | 0.16 | 69% |

GARCH had the lower QLIKE loss (Patton 2011) for 96% of the stocks. In the backtest, the book's realized volatility stayed closer to the 12% target (average gap 3.4% → 2.8%), the maximum drawdown fell from −21.7% to −17.3%, and the Sharpe ratio moved from 1.04 to 1.08 (within noise). This is better risk forecasting, not an edge in returns.

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

### 13.6 Data freshness

The signal at date $\tau$ must use the close of $\tau$. Two delays break that in practice: GitHub starts the scheduled 21:15 UTC job anywhere from minutes to about five hours late, and Yahoo can publish a session's close hours after the bell. Before this check existed, several runs saw only the previous session (the latest date in the data was $\tau - 1$), traded on day-old prices, and skipped a row of the NAV history.

With Alpaca as the broker, `live.fill_latest_closes` runs before any signal:

1. **Expected session.** $\tau^\star$ = the latest date in Alpaca's market calendar (`/v2/calendar`, the exchange's real sessions, holidays and early closes) whose close time has passed in New York (`AlpacaBroker.last_close_date`). A run at 01:13 UTC is 21:13 in New York, so $\tau^\star$ is that day.
2. **Observed session.** $\tau^{y}$ = the latest date with at least one close among the strategy's names, SPY and the watchlist in the Yahoo download.
3. **Fill.** If $\tau^{y} < \tau^\star$, request daily bars for every session in $(\tau^{y}, \tau^\star]$ from Alpaca's market data (`/v2/stocks/bars`, consolidated SIP feed, falling back to IEX when the plan doesn't allow SIP), and write open, high, low, close and volume into those rows. Yahoo names map to Alpaca names by `-` → `.` (BRK-B → BRK.B). Bars are unadjusted; that's correct for the newest sessions, because split and dividend adjustments only rescale prices *before* an event, which Yahoo's history already carries.
4. **Report.** If the data still ends before $\tau^\star$ (both sources behind, or Alpaca failed), the run trades on the latest prices it has and raises the alert "traded on stale prices", which fails the GitHub job and emails the owner. If the calendar call itself fails, the run continues on Yahoo's data and logs that freshness couldn't be checked.

Stale data is reported rather than refused, because refusing could skip a month-end signal (§13.1 catches up only after two months). The hard guard remains: no trading at all when the latest close is older than `max_data_age_days`. The simulator has no market data source, so it skips the check.

Optionally, every rebalance and swap can wait for a person's approval, and every trading run is written to an audit log ([§17.6](#176-approval-audit-permissions)).

## 14. Statistical caveats

**Standard error of the Sharpe ratio.** For iid returns over $Y$ years, $\operatorname{SE}(\widehat{SR}) \approx \sqrt{(1 + \widehat{SR}^2/2)/Y}$ (Lo, 2002). Over 11.7 years with $\widehat{SR} = 0.2$, the SE is about 0.30, so the market-neutral book's Sharpe ratio isn't distinguishable from zero. At $\widehat{SR} = 1.1$, SE ≈ 0.37, which is significant but wide.

**Multiple testing.** Every slider setting tried on the dashboard is an implicit trial. The expected maximum Sharpe ratio across $M$ independent trials of a zero-skill strategy grows like $\sqrt{2\ln M}\cdot\operatorname{SE}$. The deflated Sharpe ratio (Bailey & López de Prado, 2014) corrects for this. Treat any configuration found by searching as in-sample until a walk-forward test confirms it.

**Survivorship bias.** `DEFAULT_UNIVERSE` is a list of today's mega caps. Run back to 2014, it selects on the outcome: these firms are large *because* they went up. Long-only results are inflated by an amount that can't be measured without point-in-time constituents. Cross-sectional (long/short) results are less exposed, since everyone in the universe shares the bias, but they still are exposed.

**Regime dependence.** Momentum suffers sharp crashes in rebounds after bear markets (Daniel & Moskowitz, 2016: 2009 is the textbook case). Twelve years of data contain only a handful of such episodes.

**What the research found** ([RESEARCH.md](RESEARCH.md)). Momentum is the only factor with a positive rank IC here ($t \approx 2.2$ at 63 days). Reversal has none and causes most of the turnover; low volatility is significantly negative. Walk-forward, out of sample, the Sharpe ratio is about 0.96. No setting in the 20-setting grid beats an equal-weight portfolio of the same 30 names on raw returns; adjusted for its lower beta, the live strategy adds about 2% a year, which is not statistically distinguishable from zero.

**Pre-registration.** Picking a configuration after seeing results is the most common way to fool yourself. Before momentum only replaced the blend, the rules for calling its edge "demonstrated" were committed to git ([PREREGISTRATION.md](PREREGISTRATION.md)): positive IC, information ratio against equal weight with $t \ge 2$, a deflated probability of at least 95% counting all 22 configurations tried, positive in 3 of 4 sub-periods, positive on the S&P 100, and confirmation on survivorship-free data. It failed four of the five rules that can be run (IR $-0.34$, $t = -1.2$; deflated probability 1%). On this evidence the strategy isn't suitable for outside money.

**Test 6: point-in-time macro** ([PREREGISTRATION_6.md](PREREGISTRATION_6.md), [RESEARCH_6.md](RESEARCH_6.md), `alphaforge/macro.py`). Test 4's market forecast was rerun with real macro data as it was known on each date: ALFRED vintages of payrolls, unemployment, CPI, industrial production, jobless claims, financial conditions and building permits, so later revisions never reach the model (January 2020 payrolls were first published as 152,186 thousand and now read 152,031 thousand), plus FRED market rates and spreads. The rule was stricter (ensemble R² above 0 with a Diebold-Mariano p below 0.05/3). Every horizon failed, by a wide margin (ensemble R² −12%, −48%, −108%): the linear and neural models extrapolate badly from extreme readings such as the 2020 jobless-claims spike, and the best single model (ARIMA, R² +0.2% to +1.0%) was not significant. The Lab uses these point-in-time features anyway, because they are the honest data.

**Test 7: company fundamentals** ([PREREGISTRATION_7.md](PREREGISTRATION_7.md), [RESEARCH_7.md](RESEARCH_7.md), `alphaforge/fundamentals.py`). SEC EDGAR XBRL filings for 619 of the 848 point-in-time S&P 500 members (132,031 events in `data/fundamental_events.csv.gz`), each value usable from the day after its filing and taken as first filed, so restatements never leak backwards. Valuation ratios use the actual price of each day (Yahoo's split-adjusted close multiplied back by later splits), so they match per-share figures in the filings. Four signals, each the top 20% against equal weight of members that have it: book-to-market (IC −0.007), earnings yield (+0.011), return on assets (+0.006) and standardized unexpected earnings (+0.004); information ratios from −0.08 to +0.07, none with |t| above 0.3. No signal passed. Ken French's survivorship-free factor returns had predicted this: value, investment and size have earned about nothing since 2010, and profitability only a little.

**Test 5: risk controls** ([PREREGISTRATION_5.md](PREREGISTRATION_5.md), [RESEARCH_5.md](RESEARCH_5.md)). Three candidates from the Lab, judged on losses avoided (maximum drawdown at least 2 points smaller, Sharpe within 0.05 overall and from 2020, turnover up at most 25%). None was adopted. **Maximum diversification** (§18.5 as the whole construction, `mode: "max_div"`) beat momentum on the point-in-time S&P 500's 100 most-traded names (drawdown −18% vs −44%), but on the live 30 names it was worse than the current strategy on every rule (drawdown −24% vs −18%, Sharpe 1.00 vs 1.11). The Lab's earlier comparison was against equal weight, not against the strategy with its optimizer and GARCH. A **daily 3% VaR limit** (GARCH on the book's own returns, 10-point band) raised the Sharpe ratio slightly (1.17) but cut the drawdown by only 0.5 points. **Stress de-risking** (half the book while VIX is above VIX3M or SPY's GARCH volatility is in its top 10%) cut the drawdown from −17.8% to −14.0% at a similar Sharpe, but cost about 3 points of annual return and raised turnover from 3.0× to 5.3× a year, over the limit. Overlays scale the whole book from the next day (`test5.apply_overlay`; a test checks that a scale of 1 reproduces the backtest exactly).

**Test 3: trading less into dips** ([PREREGISTRATION_3.md](PREREGISTRATION_3.md), [RESEARCH_3.md](RESEARCH_3.md)). Four changes, each judged against fixed rules (turnover down at least 15%, Sharpe within 0.05, maximum drawdown within 2 points; for GARCH, the forecasting rules of §9.6):

- **No two-week swap:** sale days fell from 21 to 12 a year and the Sharpe ratio rose from 1.04 to 1.06, but turnover fell only 10%, so it missed the 15% bar. Not adopted; the swap stays.
- **Rank buffer** (buy into the top 30%, keep while in the top 50%; `hold_buffer`): no effect on 30 names, because the optimizer already damps turnover. On the point-in-time S&P 500 it halved turnover (6.3× → 3.0× a year) at the same Sharpe. It had to pass on both, so not adopted.
- **GARCH volatility:** passed every rule; adopted (§9.6).
- **Crypto exit buffer** (sell a coin only when all three trend lookbacks are negative; `trend_exit`): failed every rule. Sharpe 0.92 → 0.69, maximum drawdown −48% → −56%. Holding through dips is exactly what trend-following is meant to avoid: its quick exits are its crash protection.

**Test 2: a point-in-time universe** ([PREREGISTRATION_PIT.md](PREREGISTRATION_PIT.md), [RESEARCH_PIT.md](RESEARCH_PIT.md), `alphaforge/pit.py`). To remove the hindsight in "today's 30 winners", the second test uses the S&P 500 as it was at each month-end from 2012 (membership from the free `fja05680/sp500` list; 848 tickers, 645 priced by Yahoo, 84% of member-months covered). Three signals with outside evidence were registered in advance: 12-1 momentum, residual momentum (Blitz, Huij & Martens 2011) and the 52-week high (George & Hwang 2004). Each buys the top 20% each month against equal weight of all members. **None passed a single rule.** Momentum's monthly rank IC fell from $+0.057$ ($t = 2.2$) on the hindsight universe to $+0.003$ ($t = 0.2$) on the fair one: almost all of the earlier signal was survivorship bias. Residual momentum: IC $0.000$; 52-week high: $-0.002$. Information ratios against equal weight: $+0.05$, $+0.08$, $-0.26$, none with $|t| > 1$.

**Upgrade path,** in order of value: complete prices for delisted stocks (Yahoo covers 84% of member-months; the rest needs a paid source such as Norgate, Sharadar or CRSP) → signals with independent evidence that this universe can't fake (fundamental value and quality, earnings revisions) → feeding the §17.1 factor model into the §9.5 optimizer in place of the sample covariance → square-root impact costs.

## 15. Parameter reference

| Parameter | Default | Where |
|---|---|---|
| Momentum lookback / skip | 252 / 21 days | `signals.momentum` |
| Reversal lookback | 5 days | `signals.reversal` |
| Low-vol lookback | 63 days | `signals.low_vol` |
| Trend-quality lookback | 126 days | `signals.quality_trend` |
| Winsorization | ±3 σ | `signals.cs_zscore` |
| Factor weights $\lambda$ | 0.4 / 0.2 / 0.2 / 0.2 (live: 1 / 0 / 0 / 0, momentum only) | `Config.factor_weights` |
| Sector cap $c_{\text{sec}}$ / beta cap $c_\beta$ | none (live: 40% / 1.2) | `Config.max_sector`, `max_beta` |
| Turnover penalty $\tau$ | 0 (live: 0.001) | `Config.turnover_penalty` |
| Volatility model | sample (live: GARCH(1,1), 756-day fit, 21-day horizon) | `Config.vol_model`, `vol.garch_vol` |
| Rank buffer / crypto exit buffer | off (tested in RESEARCH_3, not adopted) | `Config.hold_buffer`, `Config.trend_exit` |
| QP solver | ADMM, $\rho$ 0.5, $\sigma$ $10^{-6}$, relaxation 1.6, tolerance $10^{-8}$ | `portfolio.solve_qp` |
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
| Price history fresh | business days between the latest close and the expected one: 0 ok, 1 warn, more fail. Expected = today once NYSE has opened on a trading day, else the previous trading day; for crypto, yesterday (UTC), because today's bar is still forming. The trading job fills missing sessions itself first (§13.6), so a warning here means both data sources were behind |
| Quotes complete | every shown symbol's last quote date equals the latest close, else warn with the laggards |
| No missing prices | every strategy name has a finite price on the latest row, else fail |
| No stale prices | no strategy name has an unchanged close for 6 rows, else warn |
| Corporate actions / bad ticks | no daily move above 25% (crypto 50%) in 10 sessions, else warn with the date and size. Prices are split- and dividend-adjusted by Yahoo, so a flagged jump is either real news or a data error |
| Positions reconcile to fills | each broker position matches the quantity rebuilt from the full fill history (§13.3) within 3% (crypto fees are paid in coin), else warn |
| Cash + positions = equity | Alpaca only: $|E - C - \sum MV| \le 0.5\% \cdot E$ |
| No stuck orders | no order still open (new, accepted, partially filled, held) after one day |
| Trading job ran | last trading run within 4 days (covers weekends and one holiday) |

The browser adds two live checks: the terminal data's age (ok under 45 minutes, or under 3 days while NYSE is closed, because the refresh only runs in market hours) and the live feed's last tick (ok under 60 seconds, or anytime while NYSE is closed). A failing check is also listed under Alerts.

### 17.9 Paper against backtest

The test of whether live trading reproduces the research (`terminal.tracking_block`). A **shadow backtest** runs the strategy's current settings from the paper sleeve's first day (`run_backtest(..., start=day)`: first signal that day, then the normal calendar), with the backtest's costs. It is compared with the paper sleeve's daily returns from `state/equity.csv`:

```math
r^{\text{paper}}_t = \frac{(A_t - A_{t-1}) - (V^c_t - V^c_{t-1})}{A_{t-1} - V^c_{t-1}}
```

with $A$ the account equity and $V^c$ the crypto sleeve's NAV (§13.0). Measuring the change this way means that setting aside the crypto budget isn't counted as a loss. For rows from before the crypto column existed, $V^c$ takes its first recorded value. The crypto sleeve uses its own NAV, from its start date.

Reported: the cumulative return of each, the gap, tracking error $\operatorname{sd}(r^{\text{paper}} - r^{\text{shadow}})\sqrt{A}$ (from 5 days) and correlation (from 20 days), next to the pass/fail rule in [LIVE_TRADING.md](LIVE_TRADING.md#before-real-money-a-passfail-rule): 126 trading days, correlation ≥ 0.9, average slippage within the assumed cost, and the edge test of §14. Until the next full rebalance the paper book still holds the old blend's stocks, so a gap is expected at first.

### 17.10 Forecasts

The Forecasts panel (`terminal.forecast_block`, command `FCST`) turns a signal into an expected return with an honest range, using Grinold's forecasting rule (Grinold & Kahn 2000):

```math
\mathbb E[r_i - \bar r \mid z_i] = \mathrm{IC}\cdot\sigma_i\cdot z_i,
\qquad
\text{68\% range} = \mathbb E[\cdot] \pm \sigma_i\sqrt{1-\mathrm{IC}^2},
\qquad
P(r_i > \bar r) = \Phi\!\left(\frac{\mathrm{IC}\, z_i}{\sqrt{1-\mathrm{IC}^2}}\right)
```

where $z_i$ is the name's standardized score, $\sigma_i$ its volatility over the horizon (daily standard deviation over the last 63 days for stocks or 60 for crypto, times $\sqrt{h}$), and IC the signal's measured information coefficient at that horizon. The rule follows from a regression of the next-period return on the score when both are roughly normal: the slope is $\mathrm{IC}\cdot\sigma_i$ per unit of $z$. The forecast is therefore only as good as the IC. With an IC near zero, every forecast is near zero and the range is the stock's normal move. That is the panel's point: it makes visible how little a signal knows.

- **Stocks:** 12-1 momentum z-scored across the 100 or so names on the terminal, one-month horizon ($h = 21$), $\sigma_i$ from GARCH(1,1) (§9.6) with the 63-day sample as fallback, IC from the point-in-time test (`alphaforge/calibration.json`, written by `python -m alphaforge.pit`): $+0.003$, $t = 0.2$. The track-record row shows the average next-month return against the average stock for each fifth of the forecasts since 2012. A working forecast would climb from the lowest to the highest fifth; this one is flat.
- **Crypto:** the trend score standardized against its own history across all coins (a time-series signal), one-week horizon, IC pooled over coins and month-ends (§17.5). It measures about $+0.11$ ($t \approx 2.9$), but on today's 8 surviving coins with no pre-registered test, so the panel marks it unproven.

The forecasts are not used to trade. They describe what the signal implies, with its track record next to it.

## 18. The Lab

Code: `alphaforge/models.py`, `strategies.py`, `lab.py`; page `site/research.html`. Rules for its forecasting test: [PREREGISTRATION_4.md](PREREGISTRATION_4.md); results: [RESEARCH_4.md](RESEARCH_4.md). Every panel is tagged **DATA** (measured: prices, yields, breadth, positions) or **MODEL** (estimated: forecasts, VaR, regime, allocations). Nothing on the page is traded.

### 18.1 Market forecasts (track A)

Target: SPY's log return over $h \in \{5, 21, 63\}$ trading days, sampled weekly. Thirteen features known at the forecast date (past returns, distance from the 200-day average, realized and GARCH volatility, VIX and its change, term spread, credit, dollar, oil).

**Models.** Historical mean (the benchmark); ARIMA$(p,1,0)$, an AR($p$) on daily log returns, $p \le 5$ by AIC, forecast by iterating $\hat r_{t+k} = c + \sum_{j=1}^{p}\phi_j \hat r_{t+k-j}$ and summing $k = 1..h$; ridge regression ($\lambda = 10$, standardized features); random forest (300 trees, depth 4); gradient-boosted trees (scikit-learn HistGradientBoosting, depth 3, learning rate 0.05, 200 rounds); a neural network (32-16 MLP, standardized inputs and target, early stopping); a momentum rule. **Ensemble:** the equal-weight average of the six non-benchmark models. Equal weights are deliberate: estimated combination weights usually do worse out of sample (the "forecast combination puzzle", Smith & Wallis 2009).

**Purged walk-forward.** For each year $Y \ge 2014$, every model is fitted on the weeks $t$ whose target window ended before 1 January $Y$ ($t + h < $ cut-off), then forecasts every week of $Y$. A test checks that shocking all prices after a date leaves every earlier forecast unchanged.

**Scoring.** With realized $y_t$, model forecast $f_t$ and historical-mean forecast $\bar y_t$:

```math
R^2_{\text{OOS}} = 1 - \frac{\sum_t (y_t - f_t)^2}{\sum_t (y_t - \bar y_t)^2},
\qquad
\text{DM} = \frac{\bar d}{\widehat{\text{se}}_{\text{NW}}(\bar d)},\; d_t = (y_t - \bar y_t)^2 - (y_t - f_t)^2
```

(Campbell & Thompson 2008; Diebold & Mariano 1995), with a Newey-West standard error at lag $\lceil h/5 \rceil$ because overlapping weekly targets are autocorrelated. The hit rate is the share of correct signs; its binomial test uses the number of non-overlapping forecasts. Because SPY mostly rises, the historical mean alone is right 58–74% of the time, so a hit rate above 50% is not evidence of skill.

**Scenarios and intervals.** With the ensemble forecast $\mu$, the GARCH volatility over the horizon $\sigma_h$ (§9.6) and the standardized out-of-sample errors $z_t = (y_t - f_t)/\operatorname{sd}(y - f)$: bear, base and bull are $\mu + \sigma_h\, q_z(0.10)$, $\mu + \sigma_h\, q_z(0.50)$ and $\mu + \sigma_h\, q_z(0.90)$. The 95% interval uses $q_z(0.025)$ and $q_z(0.975)$. Using empirical error quantiles instead of a normal distribution keeps the fat tails; the page reports how often past outcomes fell inside the 80% interval.

### 18.2 Stock forecasts (track B)

Each point-in-time S&P 500 member at each month-end (pit.py), nine features rank-transformed to $[-1, 1]$ across members that month (Gu, Kelly & Xiu 2020): 12-1 and 6-1 momentum, 1-month reversal, 52-week-high ratio, volatility, 252-day beta, residual momentum, largest daily return, dollar volume. Target: next month's return minus the members' average, winsorized at the 1st and 99th percentiles for training. The same learners are refitted each January from 2016 on all earlier months, with the last month purged (its target ends after the cut-off; a test checks it). The ensemble averages the models' cross-sectional ranks. Today's one-month forecast per stock is Grinold's rule (§17.10) with the ensemble's out-of-sample IC and GARCH volatility. "Model agreement" is $1 - \operatorname{sd}(\text{model ranks}) / 0.29$, where 0.29 is the standard deviation of independent uniform ranks.

### 18.3 Strategy lab

Thirteen strategies, each net of costs (SPY 2 bp, stocks 7 bp per unit of turnover; 0.5% a year to borrow shares; T-bills + 1% to borrow cash), trading at the next close or the next month: buy-and-hold SPY; trend following (hold SPY above its 200-day average, else T-bills); volatility targeting ($w = \min(1.5, 0.15/\sigma^{\text{GARCH}})$; Moreira & Muir 2017); mean reversion (Connors RSI(2) below 10 above the 200-day average, sell above the 5-day average); on the point-in-time S&P 500, momentum long-only and market-neutral (top minus bottom 20%), short-term reversal long/short, low volatility, and a three-factor composite; pairs trading by the distance method (Gatev, Goetzmann & Rouwenhorst 2006: the 10 same-sector pairs with the smallest squared distance of normalized prices over 252 days, opened at 2 formation standard deviations, closed when the spread crosses zero or after 126 days); and the crypto sleeve against bitcoin.

Reported: CAGR, volatility, Sharpe (excess of T-bills), Sortino, maximum drawdown, Calmar (CAGR ÷ |max drawdown|), win rate, skew, annual cost drag (gross minus net), Sharpe before and from 2020, and the probabilistic Sharpe ratio $\text{PSR} = \Phi\!\left(\widehat{SR}\sqrt{n-1}\,/\sqrt{1 - \gamma_3 \widehat{SR} + \tfrac{\gamma_4 - 1}{4}\widehat{SR}^2}\right)$ (Bailey & López de Prado 2012), the probability that the true per-period Sharpe exceeds zero given skew $\gamma_3$ and kurtosis $\gamma_4$.

### 18.4 Risk of the paper book

Today's equity weights $w$ applied to three years of returns give the book's return history $r^p$. One-day and ten-day VaR and Expected Shortfall at 95% and 99% by five methods:

- **Historical:** empirical quantiles of the last two years (ten-day: overlapping ten-day sums).
- **Parametric normal:** $\text{VaR}_\alpha = z_\alpha \sigma - \mu$, $\text{ES}_\alpha = \sigma\,\varphi(z_\alpha)/(1-\alpha) - \mu$.
- **Cornish-Fisher:** $z_\alpha$ replaced by $z_\alpha + \tfrac{(z_\alpha^2 - 1)S}{6} + \tfrac{(z_\alpha^3 - 3z_\alpha)K}{24} - \tfrac{(2z_\alpha^3 - 5z_\alpha)S^2}{36}$ with skew $S$ and excess kurtosis $K$.
- **Filtered historical simulation** (Barone-Adesi et al. 1999): fit GARCH(1,1) to $r^p$, standardize $\epsilon_t = r^p_t/\sqrt{h_t}$, and simulate by resampling $\epsilon$ through the GARCH recursion from today's $h_{T+1}$ (20,000 one-day draws; 5,000 ten-day paths). This keeps both the fat tails and today's volatility.
- **Monte Carlo:** multivariate Student-t shocks (5 degrees of freedom, scaled to unit variance) with the 252-day correlation shrunk 30% toward the identity and each stock's one-day GARCH volatility; ten-day by $\sqrt{10}$.

Also shown: skew, excess kurtosis, worst and best day, tail ratio $|q_{0.95}/q_{0.05}|$, beta and correlation to SPY, the three-year drawdown at today's weights, gross and net exposure, the ten-day filtered-historical P&L histogram and the correlation matrix. The terminal's Risk panel shows the filtered-historical 99% VaR and ES next to its simpler measures.

### 18.5 Portfolio construction, leverage and sizing

For the strategy's 30 stocks, with $\Sigma = D C D$ (GARCH volatilities, 252-day correlation shrunk 30%) and long-only weights capped at 10%: **equal weight**; **inverse volatility**; **minimum variance** $\min w^\top \Sigma w$; **maximum diversification** $\max \frac{w^\top \sigma}{\sqrt{w^\top \Sigma w}}$ (Choueifaty & Coignard 2008), solved as $\min x^\top \Sigma x$ s.t. $\sigma^\top x = 1$, $x \ge 0$, then $w = x / \mathbf 1^\top x$; **equal risk contribution** (Maillard, Roncalli & Teiletche 2010), by the fixed-point iteration $w_i \leftarrow w_i \sqrt{\overline{RC}/RC_i}$ with $RC_i = w_i (\Sigma w)_i$; and **mean-variance** $\max \alpha^\top w - \tfrac{\lambda}{2} w^\top \Sigma w$ ($\lambda = 5$) with the track-B forecasts as $\alpha$. The quadratic programs use the ADMM solver of §9.5, projected onto the capped simplex. Reported per method: forecast volatility, diversification ratio, effective names $1/\sum w_i^2$, the largest risk share, and a monthly walk-forward from 2016.

**Leverage.** The live strategy's backtest returns at $L \in \{1, 1.5, 2, 3\}$: $r^L_t = L r_t - (L - 1)(r^f_t + 1\%/252)$. One-year loss probabilities come from 2,000 paths built from 21-day blocks of history (a block bootstrap keeps volatility clustering).

**Kelly.** $f^* = \mu/\sigma^2 = SR/\sigma$ from the backtest, with half Kelly and the Kelly fraction at the lower 95% bound of the Sharpe ratio, $\max(0, SR - 1.96\,\text{SE})/\sigma$ with $\text{SE} = \sqrt{(1 + SR^2/2)/Y}$. Kelly is only as good as the mean it is given, and the fair-universe tests put the strategy's edge near zero, where Kelly is 0.

### 18.6 Market intelligence and integrity

**Regime** (a rule, not a fitted model): *Stress* if VIX is above VIX3M (an inverted volatility curve) or SPY's GARCH volatility is in its top 10% of ten years; *Risk-on* if SPY is above its 200-day average with volatility below its ten-year median; else *Neutral*. Macro indicators show their one-month change, z-score against one year ($(x - \bar x)/s$) and ten-year percentile. Breadth uses today's S&P 500 members. Unusual activity flags members whose move today exceeds three standard deviations of their prior 63 days, or whose volume does.

**Not available, and not estimated:** institutional flows, point-in-time fundamentals, an economic-events calendar, options data, prices for about a quarter of former members, and deep learning (PyTorch adds about 800 MB per install; Gu, Kelly & Xiu 2020 find shallow networks do as well for return prediction). The page lists them instead of filling the gap.

## References

- Ang, A., Hodrick, R., Xing, Y. & Zhang, X. (2006). The cross-section of volatility and expected returns. *Journal of Finance* 61(1).
- Asness, C., Moskowitz, T. & Pedersen, L. (2013). Value and momentum everywhere. *Journal of Finance* 68(3).
- Bailey, D. & López de Prado, M. (2012). The Sharpe ratio efficient frontier. *Journal of Risk* 15(2).
- Bailey, D. & López de Prado, M. (2014). The deflated Sharpe ratio. *Journal of Portfolio Management* 40(5).
- Baker, M., Bradley, B. & Wurgler, J. (2011). Benchmarks as limits to arbitrage: understanding the low-volatility anomaly. *Financial Analysts Journal* 67(1).
- Barone-Adesi, G., Giannopoulos, K. & Vosper, L. (1999). VaR without correlations for portfolios of derivative securities. *Journal of Futures Markets* 19(5).
- Blitz, D., Huij, J. & Martens, M. (2011). Residual momentum. *Journal of Empirical Finance* 18(3).
- Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *Journal of Econometrics* 31(3).
- Bollerslev, T. (1990). Modelling the coherence in short-run nominal exchange rates: a multivariate generalized ARCH model. *Review of Economics and Statistics* 72(3).
- Campbell, J. & Thompson, S. (2008). Predicting excess stock returns out of sample. *Review of Financial Studies* 21(4).
- Choueifaty, Y. & Coignard, Y. (2008). Toward maximum diversification. *Journal of Portfolio Management* 35(1).
- Da, Z., Gurun, U. & Warachka, M. (2014). Frog in the pan: continuous information and momentum. *Review of Financial Studies* 27(7).
- Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2).
- DeMiguel, V., Garlappi, L. & Uppal, R. (2009). Optimal versus naive diversification. *Review of Financial Studies* 22(5).
- Diebold, F. & Mariano, R. (1995). Comparing predictive accuracy. *Journal of Business & Economic Statistics* 13(3).
- Engle, R. (1982). Autoregressive conditional heteroscedasticity with estimates of the variance of United Kingdom inflation. *Econometrica* 50(4).
- Engle, R. & Mezrich, J. (1996). GARCH for groups. *Risk* 9(8).
- Frazzini, A. & Pedersen, L. (2014). Betting against beta. *Journal of Financial Economics* 111(1).
- Gatev, E., Goetzmann, W. & Rouwenhorst, K. G. (2006). Pairs trading: performance of a relative-value arbitrage rule. *Review of Financial Studies* 19(3).
- George, T. & Hwang, C.-Y. (2004). The 52-week high and momentum investing. *Journal of Finance* 59(5).
- Grinold, R. & Kahn, R. (2000). *Active Portfolio Management*, 2nd ed. McGraw-Hill.
- Gu, S., Kelly, B. & Xiu, D. (2020). Empirical asset pricing via machine learning. *Review of Financial Studies* 33(5).
- Hurst, B., Ooi, Y. H. & Pedersen, L. (2017). A century of evidence on trend-following investing. *Journal of Portfolio Management* 44(1).
- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance* 48(1).
- Ledoit, O. & Wolf, M. (2004). Honey, I shrunk the sample covariance matrix. *Journal of Portfolio Management* 30(4).
- Lehmann, B. (1990). Fads, martingales, and market efficiency. *Quarterly Journal of Economics* 105(1).
- Liu, Y. & Tsyvinski, A. (2021). Risks and returns of cryptocurrency. *Review of Financial Studies* 34(6).
- Lo, A. (2002). The statistics of Sharpe ratios. *Financial Analysts Journal* 58(4).
- Lou, D. & Polk, C. (2022). Comomentum: inferring arbitrage activity from return correlations. *Review of Financial Studies* 35(7).
- López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley.
- Maillard, S., Roncalli, T. & Teiletche, J. (2010). The properties of equally weighted risk contribution portfolios. *Journal of Portfolio Management* 36(4).
- Menchero, J., Orr, D. & Wang, J. (2011). The Barra US equity model (USE4): methodology notes. MSCI.
- Moreira, A. & Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance* 72(4).
- Novy-Marx, R. & Velikov, M. (2016). A taxonomy of anomalies and their trading costs. *Review of Financial Studies* 29(1).
- Patton, A. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160(1).
- Perold, A. (1988). The implementation shortfall: paper versus reality. *Journal of Portfolio Management* 14(3).
- Smith, J. & Wallis, K. (2009). A simple explanation of the forecast combination puzzle. *Oxford Bulletin of Economics and Statistics* 71(3).
- Stellato, B., Banjac, G., Goulart, P., Bemporad, A. & Boyd, S. (2020). OSQP: an operator splitting solver for quadratic programs. *Mathematical Programming Computation* 12(4).
