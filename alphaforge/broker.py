"""Brokers. SimBroker is a file-backed paper account; AlpacaBroker talks to Alpaca (paper or live).

Both expose the same four calls the trading job needs:
    equity(prices) -> float
    positions()    -> {symbol: {"qty", "avg_cost"}}
    submit(symbol, qty, price) -> fill/order dict   (qty signed: + buy, - sell)
    flatten(prices) -> list of fills/orders
"""
import json
import os
import urllib.error
from datetime import datetime, timezone
import urllib.request


class SimBroker:
    """Paper account persisted as JSON. Fills immediately at `price` adjusted for slippage."""

    queues_orders = False  # fills are synchronous, so the job simulates the execution lag itself

    def __init__(self, path, capital=100_000.0, slippage_bps=5.0, commission_bps=2.0):
        self.path = path
        self.slip = slippage_bps / 1e4
        self.fee = commission_bps / 1e4
        state = {"cash": capital, "positions": {}}
        if os.path.exists(path):
            with open(path) as f:
                state = json.load(f)
        self.cash = float(state["cash"])
        self._pos = state["positions"]

    def equity(self, prices):
        return self.cash + sum(p["qty"] * float(prices[s]) for s, p in self._pos.items())

    def positions(self):
        return {s: dict(p) for s, p in self._pos.items()}

    def submit(self, symbol, qty, price):
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
        return {"symbol": symbol, "qty": qty, "price": px, "fee": fee, "status": "filled"}

    def flatten(self, prices):
        return [self.submit(s, -p["qty"], prices[s]) for s, p in list(self._pos.items())]

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w") as f:
            json.dump({"cash": self.cash, "positions": self._pos}, f, indent=1)


class AlpacaBroker:
    """Alpaca REST v2. Paper unless live=True. Orders are market/day and queue for the next open."""

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
        return {p["symbol"]: {"qty": float(p["qty"]), "avg_cost": float(p["avg_entry_price"]),
                              "last": float(p["current_price"])}
                for p in self._req("GET", "/v2/positions")}

    def account(self):
        a = self._req("GET", "/v2/account")
        return {"equity": float(a["equity"]), "cash": float(a["cash"]),
                "buying_power": float(a["buying_power"]),
                "day_pl": float(a["equity"]) - float(a["last_equity"])}

    def orders(self, limit=150):
        """Recent orders, newest first, in the blotter schema (qty signed, UTC timestamps)."""
        out = []
        for o in self._req("GET", f"/v2/orders?status=all&limit={limit}&direction=desc"):
            sign = 1 if o["side"] == "buy" else -1
            when = (o.get("filled_at") or o.get("submitted_at") or "")[:16].replace("T", " ")
            out.append({"date": when, "symbol": o["symbol"], "qty": sign * float(o.get("qty") or 0),
                        "filled": sign * float(o.get("filled_qty") or 0),
                        "price": float(o["filled_avg_price"]) if o.get("filled_avg_price") else None,
                        "status": o["status"]})
        return out

    def history(self):
        """Daily equity for the past year as [(YYYY-MM-DD, equity)], skipping unfunded days."""
        h = self._req("GET", "/v2/account/portfolio/history?period=1A&timeframe=1D")
        return [(datetime.fromtimestamp(t, timezone.utc).date().isoformat(), e)
                for t, e in zip(h.get("timestamp") or [], h.get("equity") or []) if e]

    def cancel_open(self):
        self._req("DELETE", "/v2/orders")

    def submit(self, symbol, qty, price=None):
        if qty == 0:
            return None
        o = self._req("POST", "/v2/orders", {
            "symbol": symbol, "qty": str(abs(qty)), "side": "buy" if qty > 0 else "sell",
            "type": "market", "time_in_force": "day"})
        return {"symbol": symbol, "qty": qty, "price": price, "fee": 0.0,
                "status": o.get("status", "submitted"), "id": o.get("id")}

    def flatten(self, prices=None):
        self._req("DELETE", "/v2/positions?cancel_orders=true")
        return [{"symbol": "*", "qty": 0, "price": None, "fee": 0.0, "status": "flatten_all"}]

    def save(self):
        pass  # state lives at the broker
