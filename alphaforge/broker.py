"""Brokers. SimBroker is a file-backed paper account; AlpacaBroker talks to Alpaca (paper or live).

Both expose what the trading job and the terminal need:
    equity(prices) -> float
    positions()    -> {symbol: {"qty", "avg_cost", "cls", ...}}   cls: "us_equity" | "crypto"
    submit(symbol, qty, price, client_id=None) -> order dict    (qty signed: + buy, - sell)
    fills(since)   -> [{"symbol", "qty", "price", "time", "cls"}]   filled orders after `since`
    cancel_stale(cls, keep_prefix) -> cancel this job's open orders that aren't from today's run

Crypto symbols use Alpaca's pair format everywhere ("BTC/USD").
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


def asset_class(symbol):
    return "crypto" if "/" in symbol else "us_equity"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SimBroker:
    """Paper account persisted as JSON. Fills immediately at `price` adjusted for slippage."""

    queues_orders = False  # fills are synchronous, so the job simulates the execution lag itself

    def __init__(self, path, capital=100_000.0, slippage_bps=5.0, commission_bps=2.0):
        self.path = path
        self.slip = slippage_bps / 1e4
        self.fee = commission_bps / 1e4
        state = {"cash": capital, "positions": {}, "fills": []}
        if os.path.exists(path):
            with open(path) as f:
                state.update(json.load(f))
        self.cash = float(state["cash"])
        self._pos = state["positions"]
        self._fills = state["fills"]

    def equity(self, prices):
        return self.cash + sum(p["qty"] * float(prices[s]) for s, p in self._pos.items())

    def positions(self):
        return {s: {**p, "cls": asset_class(s)} for s, p in self._pos.items()}

    def submit(self, symbol, qty, price, client_id=None):
        if qty == 0:
            return None
        px = float(price) * (1 + self.slip if qty > 0 else 1 - self.slip)
        fee = abs(qty * px) * self.fee
        self.cash -= qty * px + fee
        cur = self._pos.get(symbol, {"qty": 0.0, "avg_cost": 0.0})
        new_qty = cur["qty"] + qty
        if abs(new_qty) < 1e-9:
            self._pos.pop(symbol, None)
        else:
            # Average cost moves only when adding to (or opening) a position.
            adding = cur["qty"] == 0 or (cur["qty"] > 0) == (qty > 0)
            flipped = cur["qty"] != 0 and (cur["qty"] > 0) != (new_qty > 0)
            if flipped:
                avg = px
            elif adding:
                avg = (cur["qty"] * cur["avg_cost"] + qty * px) / new_qty
            else:
                avg = cur["avg_cost"]
            self._pos[symbol] = {"qty": new_qty, "avg_cost": avg}
        fill = {"symbol": symbol, "qty": qty, "price": px, "fee": fee, "status": "filled",
                "client_id": client_id, "time": _now()}
        self._fills.append(fill)
        return fill

    def fills(self, since):
        return [{**f, "cls": asset_class(f["symbol"])} for f in self._fills if f["time"] >= since]

    def cancel_stale(self, cls, keep_prefix):
        return 0

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"cash": self.cash, "positions": self._pos, "fills": self._fills[-2000:]}, f, indent=1)


def _pair(symbol, cls):
    """Alpaca positions report crypto as BTCUSD; orders use BTC/USD. Normalize to the pair."""
    if cls != "crypto" or "/" in symbol:
        return symbol
    for quote in ("USDT", "USDC", "USD", "BTC"):
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return f"{symbol[:-len(quote)]}/{quote}"
    return symbol


def _f(x):
    return None if x in (None, "") else float(x)


class AlpacaBroker:
    """Alpaca REST v2. Paper unless live=True.

    Equity orders are market/day: placed after the close they queue for the next open.
    Crypto orders are market/gtc and fill immediately, 24/7. Every order carries a
    deterministic client_order_id, so a retried run can't place the same order twice.
    """

    queues_orders = True
    PAPER = "https://paper-api.alpaca.markets"
    LIVE = "https://api.alpaca.markets"

    def __init__(self, key, secret, live=False):
        if not key or not secret:
            raise ValueError("ALPACA_KEY_ID and ALPACA_SECRET_KEY must be set")
        self.base = self.LIVE if live else self.PAPER
        self.headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret,
                        "Content-Type": "application/json"}

    def _req(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method, headers=self.headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Alpaca {method} {path} -> {e.code}: {e.read().decode()[:300]}") from e
        return json.loads(raw) if raw else None

    def equity(self, prices=None):
        return float(self._req("GET", "/v2/account")["equity"])

    def positions(self):
        out = {}
        for p in self._req("GET", "/v2/positions"):
            cls = p.get("asset_class", "us_equity")
            out[_pair(p["symbol"], cls)] = {
                "qty": float(p["qty"]), "avg_cost": float(p["avg_entry_price"]), "cls": cls,
                "last": _f(p.get("current_price")), "mv": _f(p.get("market_value")),
                "cost_basis": _f(p.get("cost_basis")), "upl": _f(p.get("unrealized_pl")),
                "upl_pct": _f(p.get("unrealized_plpc")), "day_pl": _f(p.get("unrealized_intraday_pl")),
                "day_pct": _f(p.get("change_today")), "lastday": _f(p.get("lastday_price")),
            }
        return out

    def account(self):
        a = self._req("GET", "/v2/account")
        return {"equity": float(a["equity"]), "cash": float(a["cash"]),
                "buying_power": float(a["buying_power"]),
                "day_pl": float(a["equity"]) - float(a["last_equity"])}

    @staticmethod
    def _order(o):
        sign = 1 if o["side"] == "buy" else -1
        return {"time": o.get("filled_at") or o.get("submitted_at"), "symbol": o["symbol"],
                "qty": sign * float(o.get("qty") or o.get("filled_qty") or 0),  # notional orders have no qty
                "filled": sign * float(o.get("filled_qty") or 0),
                "price": _f(o.get("filled_avg_price")), "status": o["status"],
                "id": o.get("id"), "client_id": o.get("client_order_id"),
                "cls": o.get("asset_class") or asset_class(o["symbol"])}

    def orders(self, limit=200):
        """Recent orders, newest first (qty signed, ISO UTC timestamps)."""
        return [self._order(o) for o in self._req("GET", f"/v2/orders?status=all&limit={limit}&direction=desc")]

    def fills(self, since):
        """Every filled (or partly filled) order submitted after `since`, oldest first."""
        out, after = [], since
        while True:
            q = urllib.parse.urlencode({"status": "closed", "after": after, "direction": "asc", "limit": 500})
            page = self._req("GET", f"/v2/orders?{q}") or []
            for o in page:
                x = self._order(o)
                if x["filled"]:
                    out.append({**x, "qty": x["filled"]})
            if len(page) < 500:
                return out
            after = page[-1]["submitted_at"]

    def history(self):
        """Daily equity for the past year as [(YYYY-MM-DD, equity)], skipping unfunded days."""
        h = self._req("GET", "/v2/account/portfolio/history?period=1A&timeframe=1D")
        return [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), e)
                for t, e in zip(h.get("timestamp") or [], h.get("equity") or []) if e]

    def cancel_stale(self, cls, keep_prefix):
        """Cancel this job's open orders in one asset class unless they came from today's run.

        Orders placed by hand (no "af-" client id) are never touched."""
        n = 0
        for o in self._req("GET", "/v2/orders?status=open&limit=500") or []:
            cid = o.get("client_order_id") or ""
            if cid.startswith("af-") and not cid.startswith(keep_prefix) and \
                    (o.get("asset_class") or asset_class(o["symbol"])) == cls:
                self._req("DELETE", f"/v2/orders/{o['id']}")
                n += 1
        return n

    def submit(self, symbol, qty, price=None, client_id=None):
        if qty == 0:
            return None
        crypto = asset_class(symbol) == "crypto"
        body = {"symbol": symbol, "qty": f"{abs(qty):.9f}".rstrip("0").rstrip(".") if crypto else str(int(abs(qty))),
                "side": "buy" if qty > 0 else "sell", "type": "market",
                "time_in_force": "gtc" if crypto else "day"}
        if client_id:
            body["client_order_id"] = client_id
        base = {"symbol": symbol, "qty": qty, "price": price, "fee": 0.0, "client_id": client_id}
        try:
            o = self._req("POST", "/v2/orders", body)
        except RuntimeError as e:
            dup = "client_order_id" in str(e) and "unique" in str(e)
            return {**base, "status": "duplicate" if dup else "error", "error": str(e)[:300]}
        return {**base, "status": o.get("status", "submitted"), "id": o.get("id")}

    def save(self):
        pass  # state lives at the broker
