"""AlphaForge dashboard: streamlit run app.py"""
import datetime as dt

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alphaforge import metrics
from alphaforge.backtest import Config, run_backtest
from alphaforge.data import DEFAULT_UNIVERSE, load_prices, synthetic_prices
from alphaforge.signals import FACTORS, factor_scores

# Reference dark palette (validated categorical slots 1-2, blue<->red diverging, gray midpoint).
SURFACE, GRID, AXIS, MUTED, INK2 = "#1a1a19", "#2c2c2a", "#383835", "#898781", "#c3c2b7"
BLUE, ORANGE, RED, MID = "#3987e5", "#d95926", "#e66767", "#383835"
DIVERGING = [[0, "#104281"], [0.25, "#3987e5"], [0.5, MID], [0.75, "#e66767"], [1, "#a32b2b"]]

st.set_page_config(page_title="AlphaForge", layout="wide")


def style(fig, height=320, yfmt=None, log=False):
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=64, b=8), paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE, font=dict(color=INK2, family="system-ui, Segoe UI, sans-serif"),
        hovermode="x unified", legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0, bgcolor="rgba(0,0,0,0)"),
        title=dict(y=0.98, yanchor="top", x=0.01),
    )
    fig.update_xaxes(gridcolor=GRID, linecolor=AXIS, tickfont_color=MUTED, showspikes=True,
                     spikecolor=MUTED, spikethickness=1, spikedash="solid")
    fig.update_yaxes(gridcolor=GRID, linecolor=AXIS, tickfont_color=MUTED, zerolinecolor=AXIS,
                     tickformat=yfmt, type="log" if log else None)
    return fig


def line(x, y, name, color, fmt=".2%"):
    return go.Scatter(x=x, y=y, name=name, mode="lines", line=dict(color=color, width=2),
                      hovertemplate=f"%{{y:{fmt}}}<extra>{name}</extra>")


@st.cache_data(ttl=6 * 3600, show_spinner="Downloading prices…")
def get_data(source, tickers, start):
    if source == "Synthetic (offline)":
        return synthetic_prices()
    return load_prices(tickers, start)


# ---------- sidebar ----------
with st.sidebar:
    st.header("AlphaForge")
    source = st.radio("Data", ["Yahoo Finance", "Synthetic (offline)"])
    tickers = st.multiselect("Universe", DEFAULT_UNIVERSE, default=DEFAULT_UNIVERSE,
                             disabled=source != "Yahoo Finance")
    start = st.date_input("Start", dt.date(2014, 1, 1), disabled=source != "Yahoo Finance")
    st.subheader("Portfolio")
    mode = st.selectbox("Mode", ["long_short", "long_only"],
                        format_func=lambda m: "Market-neutral L/S" if m == "long_short" else "Long-only")
    rebalance = st.selectbox("Rebalance", ["ME", "W-FRI", "QE"],
                             format_func={"ME": "Monthly", "W-FRI": "Weekly", "QE": "Quarterly"}.get)
    target_vol = st.slider("Target vol (ann.)", 0.02, 0.30, 0.10, 0.01, format="%.2f")
    max_weight = st.slider("Max position", 0.02, 0.30, 0.10, 0.01, format="%.2f")
    max_lev = st.slider("Max gross leverage", 0.5, 4.0, 2.0, 0.1)
    st.subheader("Costs (bps per unit traded)")
    cost_bps = st.number_input("Commission", 0.0, 50.0, 2.0, 0.5)
    slip_bps = st.number_input("Slippage", 0.0, 50.0, 5.0, 0.5)
    st.subheader("Factor weights")
    defaults = Config().factor_weights
    fw = {f: st.slider(f.replace("_", " ").title(), 0.0, 1.0, defaults[f], 0.05) for f in FACTORS}

if source == "Yahoo Finance" and len(tickers) < 5:
    st.warning("Pick at least 5 tickers.")
    st.stop()
if not any(fw.values()):
    st.warning("Set at least one factor weight above zero.")
    st.stop()

try:
    prices, bench = get_data(source, tuple(tickers), str(start))
except Exception as e:  # network/data errors are user-facing, not crashes
    st.error(f"Data load failed: {e}. Try the synthetic source.")
    st.stop()

cfg = Config(mode=mode, rebalance=rebalance, target_vol=target_vol, max_weight=max_weight,
             max_leverage=max_lev, cost_bps=cost_bps, slippage_bps=slip_bps, factor_weights=fw)
res = run_backtest(prices, cfg, bench)
s = metrics.summary(res)
live = res.weights.abs().sum(axis=1) > 0
t0 = live.idxmax()
r, b = res.returns.loc[t0:], res.benchmark.loc[t0:]

# ---------- KPI row ----------
st.caption(f"{len(prices.columns)} names · {t0:%Y-%m-%d} → {r.index[-1]:%Y-%m-%d} · "
           f"signal at close, trade {cfg.execution_lag}d later · {cost_bps + slip_bps:.1f} bps/unit cost")
k = st.columns(6)
k[0].metric("CAGR", f"{s['CAGR']:.1%}")
k[1].metric("Sharpe", f"{s['Sharpe']:.2f}")
k[2].metric("Max drawdown", f"{s['Max Drawdown']:.1%}")
k[3].metric("Ann. vol", f"{s['Ann. Vol']:.1%}")
k[4].metric("Beta", f"{s['Beta']:.2f}")
k[5].metric("Turnover / yr", f"{s['Ann. Turnover']:.1f}×")

tab_perf, tab_ret, tab_pos, tab_sig, tab_stats = st.tabs(
    ["Performance", "Returns", "Positions", "Signals", "Statistics"])

with tab_perf:
    eq, beq = (1 + r).cumprod(), (1 + b).cumprod()
    fig = go.Figure([line(eq.index, eq, "Strategy", BLUE, ".3f"),
                     line(beq.index, beq, "Benchmark", ORANGE, ".3f")])
    st.plotly_chart(style(fig, 380, log=True).update_layout(title="Growth of $1 (log)"),
                    use_container_width=True)
    c1, c2 = st.columns(2)
    dd = metrics.drawdown(r)
    fig = go.Figure(go.Scatter(x=dd.index, y=dd, name="Drawdown", fill="tozeroy", mode="lines",
                               line=dict(color=RED, width=2), fillcolor="rgba(230,103,103,0.18)",
                               hovertemplate="%{y:.2%}<extra>Drawdown</extra>"))
    c1.plotly_chart(style(fig, yfmt=".0%").update_layout(title="Drawdown", showlegend=False),
                    use_container_width=True)
    rs = metrics.rolling_sharpe(r)
    fig = go.Figure(line(rs.index, rs, "6m rolling Sharpe", BLUE, ".2f"))
    fig.add_hline(y=0, line_color=AXIS, line_width=1)
    c2.plotly_chart(style(fig).update_layout(title="Rolling Sharpe (126d)", showlegend=False),
                    use_container_width=True)

with tab_ret:
    mt = metrics.monthly_table(r)
    z = mt.drop(columns="Year")
    lim = np.nanmax(np.abs(z.values))
    fig = go.Figure(go.Heatmap(
        z=z.values, x=z.columns, y=z.index.astype(str), colorscale=DIVERGING, zmid=0,
        zmin=-lim, zmax=lim, xgap=2, ygap=2, text=np.vectorize(lambda v: "" if np.isnan(v) else f"{v:.1%}")(z.values),
        texttemplate="%{text}", textfont=dict(size=10, color="#ffffff"),
        hovertemplate="%{y} %{x}: %{z:.2%}<extra></extra>", colorbar=dict(tickformat=".0%")))
    fig.update_yaxes(autorange="reversed")
    st.plotly_chart(style(fig, 40 + 28 * len(z)).update_layout(title="Monthly returns", hovermode="closest"),
                    use_container_width=True)
    # Blue<->red diverging uses red for losses; values carry sign in text so color is not the only cue.
    c1, c2 = st.columns(2)
    var, cvar = metrics.var_cvar(r)
    fig = go.Figure(go.Histogram(x=r, nbinsx=80, marker=dict(color=BLUE, line=dict(color=SURFACE, width=1)),
                                 hovertemplate="%{x:.2%}: %{y} days<extra></extra>", name="Daily returns"))
    fig.add_vline(x=-var, line_color=INK2, line_dash="dash", annotation_text=f"VaR95 {var:.2%}",
                  annotation_font_color=INK2)
    c1.plotly_chart(style(fig).update_xaxes(tickformat=".1%").update_layout(
        title="Daily return distribution", hovermode="closest", showlegend=False), use_container_width=True)
    yr = mt["Year"]
    fig = go.Figure(go.Bar(x=yr.index.astype(str), y=yr, marker_color=[BLUE if v >= 0 else RED for v in yr],
                           marker_cornerradius=4, text=[f"{v:+.1%}" for v in yr], textposition="outside",
                           hovertemplate="%{x}: %{y:.2%}<extra></extra>"))
    c2.plotly_chart(style(fig, yfmt=".0%").update_layout(title="Calendar-year returns", showlegend=False),
                    use_container_width=True)
    with st.expander("Monthly returns table"):
        st.dataframe(mt.style.format("{:.2%}", na_rep=""), use_container_width=True)

with tab_pos:
    w = res.weights.iloc[-1].sort_values()
    w = w[w.abs() > 1e-6]
    c1, c2 = st.columns([1, 1])
    fig = go.Figure(go.Bar(x=w.values, y=w.index, orientation="h", marker_cornerradius=4,
                           marker_color=[BLUE if v > 0 else RED for v in w.values],
                           hovertemplate="%{y}: %{x:.2%}<extra></extra>"))
    c1.plotly_chart(style(fig, max(320, 22 * len(w))).update_xaxes(tickformat=".0%").update_layout(
        title=f"Current book ({res.weights.index[-1]:%Y-%m-%d}) · blue long, red short",
        hovermode="closest", showlegend=False), use_container_width=True)
    wl = res.weights.loc[t0:]
    gross, net = wl.abs().sum(axis=1), wl.sum(axis=1)
    fig = go.Figure([line(gross.index, gross, "Gross", BLUE), line(net.index, net, "Net", ORANGE)])
    c2.plotly_chart(style(fig, yfmt=".0%").update_layout(title="Exposure"), use_container_width=True)
    to = res.turnover.loc[t0:]
    to = to[to > 0]
    fig = go.Figure(go.Bar(x=to.index, y=to, marker_color=BLUE, hovertemplate="%{x|%Y-%m-%d}: %{y:.1%}<extra></extra>"))
    c2.plotly_chart(style(fig, 240, yfmt=".0%").update_layout(title="Turnover per rebalance",
                                                               hovermode="closest", showlegend=False),
                    use_container_width=True)

with tab_sig:
    last = res.alpha.iloc[-1].dropna().sort_values(ascending=False)
    fs = pd.DataFrame({f: sc.iloc[-1] for f, sc in factor_scores(prices).items()})
    tbl = fs.loc[last.index].assign(alpha=last, weight=res.weights.iloc[-1].reindex(last.index))
    st.markdown("Latest cross-sectional z-scores (winsorized ±3). Alpha is the weighted blend, re-standardized.")
    st.dataframe(tbl.style.format("{:+.2f}", subset=list(FACTORS) + ["alpha"])
                 .format("{:+.2%}", subset=["weight"]),
                 use_container_width=True, height=min(800, 38 * (len(tbl) + 1)))

with tab_stats:
    fmt_pct = {"CAGR", "Ann. Vol", "Max Drawdown", "VaR 95% (1d)", "CVaR 95% (1d)", "Hit Rate",
               "Cost Drag (ann.)", "Alpha (ann.)"}
    rows = [(k_, f"{v:.2%}" if k_ in fmt_pct else f"{v:.2f}") for k_, v in s.items()]
    bs = {"CAGR": (1 + b).prod() ** (252 / len(b)) - 1, "Ann. Vol": b.std() * np.sqrt(252),
          "Sharpe": metrics.sharpe(b), "Max Drawdown": metrics.drawdown(b).min()}
    st.dataframe(pd.DataFrame(rows, columns=["Metric", "Strategy"]).assign(
        Benchmark=[f"{bs[k_]:.2%}" if k_ in fmt_pct and k_ in bs else (f"{bs[k_]:.2f}" if k_ in bs else "")
                   for k_, _ in rows]), hide_index=True, use_container_width=True)
    st.download_button("Download daily returns (CSV)",
                       pd.DataFrame({"strategy": res.returns, "gross": res.gross_returns,
                                     "costs": res.costs, "benchmark": res.benchmark}).to_csv(),
                       "alphaforge_returns.csv", "text/csv")
