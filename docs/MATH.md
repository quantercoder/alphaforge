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

This is the 63-day sample standard deviation of daily log returns, with $n-1$ in the denominator. Low-risk stocks have historically earned higher risk-adjusted returns than CAPM predicts (Frazzini & Pedersen, 2014, "Betting Against Beta").

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

- **Cross-sectional, not time-series.** Each day is standardized against itself, so only *relative* rank enters. A market-wide crash shifts every $f_{i,t}$ together and leaves $z$ unchanged. This is why a dollar-neutral book built from $z$ has little market exposure by construction.
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

With $N = 30$ and $L = 63$, $\mathbf{S}$ has $N(N+1)/2 = 465$ free parameters estimated from $63 	imes 30 = 1890$ numbers. Its smallest eigenvalues are biased toward zero and its largest away from it (Marchenko–Pastur). Portfolios built on $\mathbf S$ inherit that error, so the engine shrinks it toward its diagonal:

```math
\hat{\mathbf\Sigma} = (1-\delta)\,\mathbf S + \delta\,\operatorname{diag}(\mathbf S), \qquad \delta = 0.3 .
```

This is the Ledoit–Wolf (2004) form with a diagonal (zero-correlation) target and a fixed intensity in place of the optimal $\delta^\star$. It keeps every variance and multiplies every covariance by $1 - \delta$. Since $\hat{\mathbf\Sigma}$ is a convex combination of two positive semi-definite matrices, it is positive semi-definite, and positive definite whenever every asset has non-zero variance.

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

Finally, $w_i \leftarrow \operatorname{clip}(w_i, -m, m)$. This is a NAV-relative limit that holds after leverage. It can only reduce exposure, so forecast vol is at most $\sigma^\star$ afterwards, and dollar-neutrality may break by the clipped amount.

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

*Derivation.* Position $i$'s value goes from $w_{i,t-1}V$ to $w_{i,t-1}V(1+r_{i,t})$, and NAV goes from $V$ to $V(1+g_t)$. Divide. Short positions work the same way ($w<0$). Cash, the residual $1 - \mathbf 1^\top\mathbf w$, earns zero; there is no financing rate.

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
| Sharpe | $\dfrac{\bar r}{s_r}\sqrt A$ | excess over **zero**, not T-bills; see below |
| Sortino | $\dfrac{\bar r}{\mathrm{DD}}\sqrt A$, with $\mathrm{DD} = \sqrt{\tfrac1n\sum_t \min(r_t,0)^2}$ | downside deviation around a 0 target, over all days |
| Drawdown | $D_t = V_t / \max_{s\le t} V_s - 1$ | |
| Max drawdown | $\min_t D_t$ | |
| Calmar | $\text{CAGR}/\lvert\min_t D_t\rvert$ | |
| VaR$_{95}$ | $-Q_{0.05}(r)$ | historical, 1-day, positive number = loss |
| CVaR$_{95}$ | $-\mathbb E[\,r \mid r \le Q_{0.05}(r)\,]$ | expected shortfall; always $\ge$ VaR |
| Beta | $\hat\beta = \dfrac{\widehat{\operatorname{Cov}}(r, r^B)}{\widehat{\operatorname{Var}}(r^B)}$ | OLS slope on the benchmark |
| Alpha (ann.) | $A\left(\bar r - \hat\beta\,\bar r^B\right)$ | Jensen's alpha with $r_f = 0$ |
| Hit rate | share of non-zero days with $r_t > 0$ | |
| Ann. turnover | $\frac{A}{n}\sum_t \text{TO}_t$ | a value of $k$ means trading $k\times$ NAV a year |
| Cost drag | $\frac{A}{n}\sum_t c_t$ | return lost to costs per year |

**Sharpe and the risk-free rate.** The engine reports $\bar r/s_r$ without subtracting $r_f$. A dollar-neutral book earns roughly $r_f$ on its short-sale proceeds in practice, so $\bar r$ is already approximately an excess return. A long-only book's Sharpe ratio is overstated by about $r_f/\sigma_p$; with 4% rates and 15% vol, that's roughly 0.27.

**Annualizing by $\sqrt{A}$** assumes independent daily returns. With first-order autocorrelation $\rho$, the true annual volatility is about $\sqrt{A\,(1+\rho)/(1-\rho)}\;s_r$ (Lo, 2002).

**Ex-ante risk on the terminal** (`terminal.build`): book volatility $\sqrt{A\,\mathbf w^\top\mathbf S\,\mathbf w}$ on the 63-day *unshrunk* covariance, a parametric 1-day VaR of $1.645\cdot\hat\sigma_p/\sqrt{A}\cdot V$ under normal returns, book beta $\sum_i w_i\hat\beta_i$ from 252-day betas, and factor exposure $E_k = \sum_i w_i z^{(k)}_i$.

## 13. Live execution

`live.py` turns target weights into orders once a day after the close. Signal generation calls the same `targets_at` as the backtest.

### 13.1 Signal calendar

$\tau$ is a signal day if it is the last trading day of its month (approximated with the US federal holiday calendar) and no signal has been generated this month. If a month-end is missed, for example through a failed run or an NYSE-only holiday, the first run at least two calendar months after the last signal catches up.

### 13.2 Order sizing

With equity $V$, price $P_i$, current shares $q_i$ and target weight $w^\star_i$:

```math
q^\star_i = \operatorname{trunc}\!\left(\frac{w_i^\star V}{P_i}\right), \qquad \Delta_i = q_i^\star - q_i .
```

Truncation toward zero means the book never exceeds its target in absolute terms. The rounding error per name is under one share, so the weight error is $\lvert w_i - w^\star_i\rvert < P_i/V$; for a \$600 stock in a \$100k account that is 0.6%.

Filters, applied in this order:

1. **Dust:** skip if $\lvert\Delta_i P_i\rvert$ is below `min_trade_notional`, unless the target is zero (full closes always go through).
2. **Fat-finger cap:** $\lvert\Delta_i\rvert \le \lfloor N^{\max}/P_i\rfloor$ with $N^{\max}$ = `max_order_notional`. A capped name converges to target over several rebalances.
3. **Sign-flip split:** if $q_i$ and $q_i + \Delta_i$ have opposite signs, send two orders, $-q_i$ and then $q_i+\Delta_i$, because brokers reject a single order that flips a position.
4. **Ordering:** sells before buys, sorted by signed notional, so sale proceeds fund the purchases.

### 13.3 Fills

- **Simulator** (`SimBroker`): the order queued on signal day $\tau$ fills at the close of the next run day $\tau + 1$, at $P(1 \pm \kappa_{\text{slip}})$ plus commission $\kappa_{\text{comm}}\lvert qP\rvert$. That reproduces the backtest's timing (§10) exactly.
- **Alpaca:** market, time-in-force *day*, submitted after the close, so they fill at the next open. This is about half a day earlier than the backtest assumes.

### 13.4 Risk controls

The high-water mark is $H_t = \max_{s\le t} V_s$. The job flattens the book and writes a `state/KILL` file when

```math
\frac{V_t}{H_t} - 1 < -d_{\max},
```

with $d_{\max}$ = `max_drawdown_halt`. Trading resumes only after a person deletes that file. The job also halts on the `ALPHAFORGE_KILL=1` environment variable, and it refuses to trade on prices older than `max_data_age_days`. Real-money trading needs both `"live_money": true` in `live.json` **and** `ALPHAFORGE_CONFIRM_LIVE=yes` in the environment.

## 14. Statistical caveats

**Standard error of the Sharpe ratio.** For iid returns over $Y$ years, $\operatorname{SE}(\widehat{SR}) \approx \sqrt{(1 + \widehat{SR}^2/2)/Y}$ (Lo, 2002). Over 11.7 years with $\widehat{SR} = 0.2$, the SE is about 0.30, so the market-neutral book's Sharpe ratio isn't distinguishable from zero. At $\widehat{SR} = 1.1$, SE ≈ 0.37, which is significant but wide.

**Multiple testing.** Every slider setting tried on the dashboard is an implicit trial. The expected maximum Sharpe ratio across $M$ independent trials of a zero-skill strategy grows like $\sqrt{2\ln M}\cdot\operatorname{SE}$. The deflated Sharpe ratio (Bailey & López de Prado, 2014) corrects for this. Treat any configuration found by searching as in-sample until a walk-forward test confirms it.

**Survivorship bias.** `DEFAULT_UNIVERSE` is a list of today's mega caps. Run back to 2014, it selects on the outcome: these firms are large *because* they went up. Long-only results are inflated by an amount that can't be measured without point-in-time constituents. Cross-sectional (long/short) results are less exposed, since everyone in the universe shares the bias, but they still are exposed.

**Regime dependence.** Momentum suffers sharp crashes in rebounds after bear markets (Daniel & Moskowitz, 2016: 2009 is the textbook case). Twelve years of data contain only a handful of such episodes.

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
| Drawdown halt $d_{\max}$ | 20% | `live.json` |

## References

- Bailey, D. & López de Prado, M. (2014). The deflated Sharpe ratio. *Journal of Portfolio Management* 40(5).
- Da, Z., Gurun, U. & Warachka, M. (2014). Frog in the pan: continuous information and momentum. *Review of Financial Studies* 27(7).
- Daniel, K. & Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2).
- DeMiguel, V., Garlappi, L. & Uppal, R. (2009). Optimal versus naive diversification. *Review of Financial Studies* 22(5).
- Frazzini, A. & Pedersen, L. (2014). Betting against beta. *Journal of Financial Economics* 111(1).
- Jegadeesh, N. & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance* 48(1).
- Ledoit, O. & Wolf, M. (2004). Honey, I shrunk the sample covariance matrix. *Journal of Portfolio Management* 30(4).
- Lehmann, B. (1990). Fads, martingales, and market efficiency. *Quarterly Journal of Economics* 105(1).
- Lo, A. (2002). The statistics of Sharpe ratios. *Financial Analysts Journal* 58(4).
- Moreira, A. & Muir, T. (2017). Volatility-managed portfolios. *Journal of Finance* 72(4).
