"""Generate site/index.html and site/crypto.html from one template so the two pages can't drift.

    python scripts/make_pages.py

Run it after editing site/terminal.js or site/terminal.css: the pages load them with a content
hash (?v=...), so browsers fetch the new version at once instead of a cached copy.
"""
import hashlib
import os

SITE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "site")


def ver(name):
    with open(os.path.join(SITE, name), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:10]

TEMPLATE = '''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="terminal.css?v={css_v}">
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js" integrity="sha384-OK7vELvjHdhUFi31JYioPIcRHTROLdcDa6ZsNWgvgLaKj+9JqhU0Ad8g4wz3CXjA" crossorigin="anonymous"></script>
</head>
<body>
<header class="top">
  <nav class="pages" aria-label="Pages">
    <a href="index.html"{eq_cur}>Equities</a>
    <a href="crypto.html"{cr_cur}>Crypto</a>
  </nav>
  <form class="cmd" id="cmdform" autocomplete="off" role="search">
    <label for="cmd">CMD</label>
    <div class="cmdwrap">
      <input id="cmd" placeholder="{placeholder}" spellcheck="false" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="sugg">
      <ul id="sugg" class="sugg" role="listbox" aria-label="Suggestions" hidden></ul>
    </div>
    <button class="go" type="submit">GO</button>
  </form>
  <div class="clock">
    <span id="mkt"></span>
    <span>NY <b id="ny">--:--:--</b></span>
    <span>UTC <b id="utc">--:--:--</b></span>
    <span>Data <b id="asof">loading</b></span>
    <span id="mode"></span>{feed_sel}
    <button id="livebtn" class="badge live-off" type="button">Delayed · connect live</button>
  </div>
</header>
<div class="strip" id="strip" aria-label="{strip_label}"></div>

<main>
  <section class="p" id="mon"><h2><span>Monitor <small class="k">MON</small> <small id="livecount"></small></span><span class="tabs" id="mtabs"></span></h2><div class="body" id="monb"></div></section>
  <section class="p" id="gp"><h2><span>Price chart <small class="k">GP</small></span><span class="tabs" id="range"></span></h2>
    <div class="ghead" id="ghead"></div><div class="chart" id="gpc"></div></section>
  <section class="p" id="perf"><h2><span>Performance <small class="k">BT</small></span><span class="tabs" id="ptabs"></span></h2>
    <div class="kpis" id="kpis"></div><div class="legend" id="plegend"></div><div class="chart" id="pc" style="height:260px"></div>
    <div class="body" id="pcompare"></div><p class="note" id="note"></p></section>
  <section class="p" id="book"><h2><span>{book_title} <small class="k">PORT</small></span><small>live P&amp;L</small></h2>
    <div class="acct" id="acct"></div><div class="kpis" id="bkpis" style="grid-template-columns:repeat(4,minmax(0,1fr))"></div><div class="body" id="bookb"></div></section>
  <section class="p" id="bltr"><h2><span>Order blotter <small class="k">BLTR</small></span><small id="slip"></small></h2><div class="body" id="bltrb"></div></section>
  <section class="p" id="sig"><h2><span>Signals <small class="k">SIG</small></span><small>{sig_note}</small></h2><div class="body" id="sigb"></div></section>
  <section class="p" id="risk"><h2><span>Risk <small class="k">RISK</small></span><small id="risklabel"></small></h2><div class="body" id="riskb"></div></section>
  <section class="p" id="mth"><h2><span>Monthly returns <small class="k">MTH</small></span><small>backtest</small></h2><div class="body" id="mthb"></div></section>
</main>

<nav class="fkeys" id="fkeys" aria-label="Functions"></nav>
<p class="foot">{foot} Nothing here is investment advice.
  <a href="https://github.com/z125081-Sam-Lam/alphaforge">Source</a> · <a href="https://github.com/z125081-Sam-Lam/alphaforge/blob/main/docs/MATH.md">Model</a> ·
  <a href="https://github.com/z125081-Sam-Lam/alphaforge/blob/main/docs/RESEARCH.md">Research</a> ·
  Charts by <a href="https://www.tradingview.com/lightweight-charts/">TradingView Lightweight Charts</a></p>

<dialog id="livedlg">
  <h3>Live prices</h3>
  <p>{live_text} Use the API key from an Alpaca <b>paper</b> account: it can read market data and can't touch real money.</p>
  <form method="dialog">
    <label>API key ID <input id="lk" autocomplete="off" spellcheck="false"></label>
    <label>Secret key <input id="ls" type="password" autocomplete="off"></label>
    <label><input type="checkbox" id="lremember"> Remember on this device</label>
    <p class="mut">Keys go only to stream.data.alpaca.markets. They're saved in this browser only if you tick the box.</p>
    <p class="mut" id="lerr"></p>
    <div class="row"><button class="go" value="connect">Connect</button><button value="cancel">Cancel</button><button value="disconnect">Disconnect</button></div>
  </form>
</dialog>

<dialog id="help">
  <h3>Commands</h3>
  <p>Type in the command line: suggestions appear as you type, matching tickers, company names and functions. Use the arrow keys and Enter, or Tab to complete. Any letter you press outside a field jumps to it.</p>
  <p>{help_tickers}<br>
  <code>MON</code> monitor · <code>PORT</code> book · <code>BLTR</code> orders · <code>SIG</code> signals<br>
  <code>RISK</code> risk · <code>BT</code> backtest · <code>MTH</code> monthly · <code>HELP</code> this panel<br>
  <code>EQUITY</code> / <code>CRYPTO</code> switch page · <code>LIVE</code> real-time prices · <code>LIVE OFF</code> disconnect{live_list}</p>
  <p>F1 to F8 map to the function bar. Data refreshes every five minutes; with LIVE on, prices and P&amp;L update tick by tick.</p>
  <form method="dialog"><button class="go">Close</button></form>
</dialog>

<script>window.PAGE = {{ kind: "{kind}", data: "{data}" }};</script>
<script src="terminal.js?v={js_v}"></script>
</body>
</html>
'''

PAGES = {
    "index.html": dict(
        title="AlphaForge Terminal", kind="equity", data="data.json", eq_cur=' aria-current="page"', cr_cur="",
        desc="AlphaForge equities: multi-factor stock strategy with live paper book, signals, risk and research.",
        placeholder="Ticker or company (NVDA, apple), or a function: PORT, SIG, RISK, BT, HELP",
        strip_label="Markets", book_title="Equities book",
        sig_note="cross-sectional z-scores",
        foot="Equities sleeve. Delayed data from Yahoo Finance; live prices and account data from Alpaca.",
        live_text="Streams real-time stock trades from Alpaca's free IEX feed for up to 30 tickers, during market hours (9:30 to 16:00 New York). Every ticker you open is live tracked; past 30, the one you opened longest ago drops off.",
        help_tickers="<code>NVDA</code> or <code>nvidia</code>: chart it and live track it",
        live_list=" · <code>LIVE LIST</code> tracked tickers", feed_sel=""),
    "crypto.html": dict(
        title="AlphaForge Crypto", kind="crypto", data="crypto.json", eq_cur="", cr_cur=' aria-current="page"',
        desc="AlphaForge crypto: trend-following crypto sleeve with live paper book, signals, risk and research.",
        placeholder="Coin (BTC, ether, sol), or a function: PORT, SIG, RISK, BT, HELP",
        strip_label="Coins", book_title="Crypto book",
        sig_note="time-series trend",
        foot="Crypto sleeve, kept separate from the stock strategy. Daily data from Yahoo Finance; live prices from Alpaca, or Coinbase as the backup; account data from Alpaca.",
        live_text="Crypto prices stream live 24/7. Pick the source with the Feed switch next to this chip: Coinbase needs no key and works in any number of windows; Alpaca matches your account but uses your one Alpaca connection, so it can clash with the equities page. If Alpaca fails, the page falls back to Coinbase. Enter your key here to use Alpaca, or leave it empty and press Connect for Coinbase. Every coin you open is live tracked; past 30, the one you opened longest ago drops off.",
        help_tickers="<code>BTC</code> or <code>solana</code>: chart it and live track it",
        live_list=" · <code>LIVE LIST</code> tracked coins",
        feed_sel='\n    <span class="feed">Feed <span class="tabs" id="feedsel" role="group" aria-label="Live price source">'
                 '<button type="button" data-f="coinbase">Coinbase</button><button type="button" data-f="alpaca">Alpaca</button></span></span>'),
}

for fname, v in PAGES.items():
    with open(os.path.join(SITE, fname), "w", encoding="utf-8", newline="\n") as f:
        f.write(TEMPLATE.format(**v, css_v=ver("terminal.css"), js_v=ver("terminal.js")))
print("pages written")
