"""CLI: python -m alphaforge [--synthetic] [--mode long_only] [--start 2015-01-01]"""
import argparse

from . import metrics
from .backtest import Config, run_backtest
from .data import DEFAULT_UNIVERSE, load_prices, synthetic_prices

p = argparse.ArgumentParser(description="Run the AlphaForge multi-factor backtest")
p.add_argument("--synthetic", action="store_true", help="use simulated prices (offline)")
p.add_argument("--start", default="2015-01-01")
p.add_argument("--mode", default="long_short", choices=["long_short", "long_only"])
p.add_argument("--rebalance", default="ME")
p.add_argument("--target-vol", type=float, default=0.10)
a = p.parse_args()

prices, bench = synthetic_prices() if a.synthetic else load_prices(DEFAULT_UNIVERSE, a.start)
res = run_backtest(prices, Config(mode=a.mode, rebalance=a.rebalance, target_vol=a.target_vol), bench)
for k, v in metrics.summary(res).items():
    print(f"{k:<18}{v:>10.3f}" if abs(v) >= 1 or k in {"Sharpe", "Sortino", "Calmar", "Beta", "Avg Gross Lev."}
          else f"{k:<18}{v:>10.2%}")
