import json, time, ccxt
e = ccxt.ndax({"enableRateLimit": True}); e.load_markets()
print("requiredCredentials", {k: v for k, v in e.requiredCredentials.items() if v})
print("now", e.iso8601(e.milliseconds()))
# USD-quoted books + 24h volume, 3 samples spaced to see spread stability
for s in ["BTC/USD","ETH/USD","SOL/USD","XRP/USD","LTC/USD","BTC/CAD","ETH/CAD","SOL/CAD","XRP/CAD","LINK/CAD","LTC/CAD"]:
    sp=[]
    for i in range(3):
        b=e.fetch_order_book(s, limit=20)
        if b["bids"] and b["asks"]:
            bid,ask=b["bids"][0][0],b["asks"][0][0]; sp.append(round((ask-bid)/((ask+bid)/2)*1e4,1))
        else: sp.append(None)
        time.sleep(4)
    t=e.fetch_ticker(s)
    print(s, "spread_bps samples", sp, "24h quoteVol", round(t.get("quoteVolume") or 0), "last", t.get("last"))
# History depth and gaps: page 4h and 1d from 2021-06-01
for s in ["BTC/CAD","ETH/CAD","SOL/CAD","XRP/CAD","LINK/CAD","LTC/CAD","BTC/USD"]:
    for tf, ms in [("4h", 4*3600_000), ("1d", 86400_000)]:
        since=e.parse8601("2021-06-01T00:00:00Z"); allc=[]
        for _ in range(30):
            c=e.fetch_ohlcv(s, tf, since=since, limit=1000)
            c=[x for x in c if not allc or x[0]>allc[-1][0]]
            if not c: break
            allc+=c; since=c[-1][0]+ms
            if since>e.milliseconds(): break
        ts=[x[0] for x in allc]
        gaps=[(e.iso8601(a),round((b-a)/ms)) for a,b in zip(ts,ts[1:]) if b-a>ms]
        big=sorted(gaps,key=lambda g:-g[1])[:3]
        zero=sum(1 for x in allc if x[5]==0)
        future=[e.iso8601(t) for t in ts if t>e.milliseconds()]
        print(s, tf, "n", len(allc), "first", e.iso8601(ts[0]) if ts else None, "last", e.iso8601(ts[-1]) if ts else None,
              "gaps", len(gaps), "missing", sum(g[1]-1 for g in gaps), "largest", big, "zero-vol", zero, "future-stamped", future)
