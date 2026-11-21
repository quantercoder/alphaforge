# Data

`sp500_ticker_start_end.csv`: each ticker's S&P 500 entry and exit dates, from
[github.com/fja05680/sp500](https://github.com/fja05680/sp500) (MIT licence, © 2019-2020 Farrell J. Aultman).
Used by `alphaforge/pit.py` to build the point-in-time universe. Tickers use the dataset's format
(`BRK.B`); the code converts them to Yahoo's (`BRK-B`).

`cache/` (not committed) holds the downloaded prices so a rerun doesn't download again.
