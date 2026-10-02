"""Price loading: Yahoo Finance for real data, a factor-model simulator for offline/tests."""
import numpy as np
import pandas as pd

DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "JPM", "V", "MA",
    "UNH", "XOM", "JNJ", "PG", "HD", "COST", "MRK", "ABBV", "CVX", "PEP",
    "KO", "WMT", "BAC", "ADBE", "CRM", "NFLX", "AMD", "TMO", "LIN", "ORCL",
]


# S&P 100 constituents (Yahoo symbols), approximate as of 2025. Watch-only: the strategy
# trades DEFAULT_UNIVERSE. Edit "watchlist" in live.json to change what the terminal shows.
SP100 = [
    "AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN", "AVGO", "AXP",
    "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK-B", "C", "CAT", "CHTR", "CL", "CMCSA",
    "COF", "COP", "COST", "CRM", "CSCO", "CVS", "CVX", "DE", "DHR", "DIS", "DUK", "EMR",
    "F", "FDX", "GD", "GE", "GILD", "GM", "GOOGL", "GS", "HD", "HON", "IBM", "INTC",
    "INTU", "ISRG", "JNJ", "JPM", "KO", "LIN", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ",
    "MDT", "MET", "META", "MMM", "MO", "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NOW",
    "NVDA", "ORCL", "PEP", "PFE", "PG", "PLTR", "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW",
    "SO", "SPG", "T", "TGT", "TMO", "TMUS", "TSLA", "TXN", "UBER", "UNH", "UNP", "UPS",
    "USB", "V", "VZ", "WFC", "WMT", "XOM",
]

# Cross-asset strip shown on the terminal: label -> Yahoo symbol.
MARKET_STRIP = {
    "SPX": "^GSPC", "NDX": "^NDX", "RTY": "^RUT", "VIX": "^VIX", "UST10Y": "^TNX",
    "DXY": "DX-Y.NYB", "GOLD": "GC=F", "WTI": "CL=F", "BTC": "BTC-USD", "EURUSD": "EURUSD=X",
}


def download(symbols, start, end=None):
    """Raw adjusted OHLCV panel from Yahoo (columns: field x symbol). Raises on empty."""
    import yfinance as yf

    raw = yf.download(list(symbols), start=start, end=end, auto_adjust=True,
                      progress=False, threads=False)
    if raw.empty:
        raise ValueError("No data returned from Yahoo Finance")
    return raw


def load_prices(tickers, start, end=None, benchmark="SPY", max_missing=0.05, raw=None):
    """Adjusted closes from Yahoo. Returns (prices, benchmark) aligned on trading days.

    Tickers missing more than `max_missing` of history are dropped rather than
    back-filled, so the backtest never sees prices that did not exist yet.
    Pass `raw` (from `download`) to reuse an existing download.
    """
    if raw is None:
        raw = download(list(tickers) + [benchmark], start, end)
    raw = raw["Close"][list(tickers) + [benchmark]].dropna(how="all")
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
