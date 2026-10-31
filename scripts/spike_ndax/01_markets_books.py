"""Public-endpoint probe of ccxt.ndax. No keys."""
import json, time, traceback
import ccxt

e = ccxt.ndax({"enableRateLimit": True})
out = {"ccxt": ccxt.__version__}
h = e.has
out["has"] = {k: h.get(k) for k in ["fetchOHLCV", "fetchOrderBook", "fetchTicker", "fetchTickers",
    "fetchTradingFees", "fetchTradingFee", "createStopOrder", "createStopLossOrder", "createStopLimitOrder",
    "createStopMarketOrder", "createTriggerOrder", "fetchMyTrades", "fetchOrder", "fetchOpenOrders",
    "fetchClosedOrders", "fetchOrders", "cancelOrder", "fetchBalance", "withdraw", "fetchDepositAddress",
    "fetchL2OrderBook", "fetchTrades", "fetchCurrencies"]}
out["timeframes"] = list(e.timeframes)
out["fees_static"] = e.fees.get("trading")

def step(name, fn):
    t = time.time()
    try:
        r = fn(); out[name] = {"ok": True, "s": round(time.time() - t, 2), "result": r}
    except Exception as ex:
        out[name] = {"ok": False, "error": f"{type(ex).__name__}: {str(ex)[:300]}"}

def markets():
    m = e.load_markets()
    rows = {}
    for s, v in m.items():
        rows[s] = {"active": v.get("active"), "spot": v.get("spot"), "min_amount": v["limits"]["amount"]["min"],
                   "min_cost": v["limits"]["cost"]["min"], "amount_prec": v["precision"]["amount"],
                   "price_prec": v["precision"]["price"], "maker": v.get("maker"), "taker": v.get("taker")}
    return {"count": len(m), "quotes": sorted({v["quote"] for v in m.values()}), "markets": rows}
step("markets", markets)

pairs = []
for base in ["BTC", "ETH", "SOL", "XRP", "LINK", "LTC", "AVAX", "DOT"]:
    for q in ["CAD", "USDT", "USD"]:
        if f"{base}/{q}" in e.markets: pairs.append(f"{base}/{q}")
out["candidate_pairs"] = pairs

def ohlcv(sym, tf):
    def f():
        c = e.fetch_ohlcv(sym, tf, limit=1000)
        return {"n": len(c), "first": e.iso8601(c[0][0]) if c else None, "last": e.iso8601(c[-1][0]) if c else None,
                "last_candle": c[-1] if c else None}
    return f
def ohlcv_since(sym, tf, since):
    def f():
        c = e.fetch_ohlcv(sym, tf, since=e.parse8601(since), limit=1000)
        return {"n": len(c), "first": e.iso8601(c[0][0]) if c else None, "last": e.iso8601(c[-1][0]) if c else None}
    return f
def book(sym):
    def f():
        b = e.fetch_order_book(sym, limit=50)
        bid, ask = b["bids"][0][0], b["asks"][0][0]
        mid = (bid + ask) / 2
        def depth(side, usd):
            tot = 0; amt = 0
            for p, a, *_ in side:
                take = min(a, (usd - tot) / p); tot += take * p; amt += take
                if tot >= usd - 1e-9: return round(abs(tot / amt / mid - 1) * 1e4, 2)
            return None
        return {"bid": bid, "ask": ask, "spread_bps": round((ask - bid) / mid * 1e4, 2),
                "levels": [len(b["bids"]), len(b["asks"])],
                "top_bid_notional": round(b["bids"][0][0] * b["bids"][0][1], 2),
                "slip_bps_buy_40": depth(b["asks"], 40), "slip_bps_sell_40": depth(b["bids"], 40),
                "slip_bps_buy_1000": depth(b["asks"], 1000)}
    return f
for s in pairs:
    if s.endswith("/CAD") or s.endswith("/USDT"):
        step(f"ohlcv_4h {s}", ohlcv(s, "4h"))
        step(f"ohlcv_1d {s}", ohlcv(s, "1d"))
        step(f"book {s}", book(s))
step("ohlcv_1d_since_2022 BTC/CAD", ohlcv_since("BTC/CAD", "1d", "2022-01-01T00:00:00Z"))
step("ohlcv_4h_since_2022 BTC/CAD", ohlcv_since("BTC/CAD", "4h", "2022-01-01T00:00:00Z"))
step("ticker BTC/CAD", lambda: {k: e.fetch_ticker("BTC/CAD").get(k) for k in ["last", "quoteVolume", "baseVolume", "timestamp"]})
step("fetchTradingFees (public)", lambda: e.fetch_trading_fees())
print(json.dumps(out, indent=1, default=str))
