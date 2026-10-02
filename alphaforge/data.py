"""Price loading: Yahoo Finance for real data, a factor-model simulator for offline/tests."""
import numpy as np
import pandas as pd

DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "MA",
    "UNH", "XOM", "JNJ", "PG", "HD", "COST", "MRK", "ABBV", "CVX", "PEP",
    "KO", "WMT", "BAC", "ADBE", "CRM", "NFLX", "AMD", "TMO", "LIN", "ORCL",
]


def load_prices(tickers, start, end=None, benchmark="SPY", max_missing=0.05):
    """Adjusted closes from Yahoo. Returns (prices, benchmark) aligned on trading days.

    Tickers missing more than `max_missing` of history are dropped rather than
    back-filled, so the backtest never sees prices that did not exist yet.
    """
    import yfinance as yf

    raw = yf.download(list(tickers) + [benchmark], start=start, end=end,
                      auto_adjust=True, progress=False)["Close"]
    if raw.empty:
        raise ValueError("No data returned from Yahoo Finance")
    raw = raw.dropna(how="all")
    bench = raw.pop(benchmark).ffill()
    keep = raw.columns[raw.isna().mean() <= max_missing]
    if len(keep) < 5:
        raise ValueError(f"Only {len(keep)} tickers with usable history; need at least 5")
    return raw[keep].ffill(), bench


def synthetic_prices(n_assets=30, n_days=2520, seed=7):
    """One-factor market + sector + idiosyncratic GBM with mild cross-sectional momentum.

    Deterministic for a seed; used by tests and the dashboard's offline mode.
    """
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2015-01-02", periods=n_days)
    mkt = rng.normal(0.0004, 0.011, n_days)
    beta = rng.uniform(0.6, 1.5, n_assets)
    sector = rng.integers(0, 5, n_assets)
    sec_f = rng.normal(0, 0.006, (n_days, 5))[:, sector]
    drift = rng.normal(0.0002, 0.0003, n_assets)
    idio = rng.normal(0, 1, (n_days, n_assets)) * rng.uniform(0.008, 0.02, n_assets)
    rets = drift + np.outer(mkt, beta) + sec_f + idio
    # Slow-moving latent drift so momentum has something to find.
    latent = np.cumsum(rng.normal(0, 0.00002, (n_days, n_assets)), axis=0)
    rets = rets + latent
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), index=idx,
                          columns=[f"SYN{i:02d}" for i in range(n_assets)])
    bench = pd.Series(100 * np.exp(np.cumsum(mkt)), index=idx, name="BENCH")
    return prices, bench
