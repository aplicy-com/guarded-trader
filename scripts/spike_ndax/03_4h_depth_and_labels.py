import ccxt
e = ccxt.ndax({"enableRateLimit": True}); e.load_markets()
H = 4*3600_000; D = 86400_000
now = e.milliseconds()
# 4h coverage: walk forward from 2021-06-01 in 1000-candle windows; skip empty windows
for s in ["BTC/CAD", "ETH/CAD", "LTC/CAD"]:
    since = e.parse8601("2021-06-01T00:00:00Z"); ts = []
    while since < now:
        c = e.fetch_ohlcv(s, "4h", since=since, limit=1000)
        c = [x for x in c if (not ts or x[0] > ts[-1])]
        if c:
            ts += [x[0] for x in c]; since = c[-1][0] + H
        else:
            since += 1000 * H
    gaps = [(e.iso8601(a), round((b - a) / H) - 1) for a, b in zip(ts, ts[1:]) if b - a > H]
    exp = (ts[-1] - ts[0]) // H + 1
    print(s, "4h n", len(ts), "of", exp, "expected; first", e.iso8601(ts[0]), "gaps", len(gaps),
          "largest", sorted(gaps, key=lambda g: -g[1])[:4])
# Close-time vs open-time labelling: aggregate 4h into days under both conventions, compare to 1d
d = {x[0]: x for x in e.fetch_ohlcv("BTC/CAD", "1d", since=now - 40 * D, limit=60)}
h = {x[0]: x for x in e.fetch_ohlcv("BTC/CAD", "4h", since=now - 40 * D, limit=300)}
def agg(keys):
    ks = [k for k in keys if k in h]
    if len(ks) != 6: return None
    return [h[ks[0]][1], max(h[k][2] for k in ks), min(h[k][3] for k in ks), h[ks[-1]][4], round(sum(h[k][5] for k in ks), 6)]
ok_open = ok_close = n = 0
for t, row in sorted(d.items())[-30:-2]:
    a_open = agg([t + i * H for i in range(6)])          # label = open time
    a_close = agg([t - D + (i + 1) * H for i in range(6)])  # label = close time
    if a_open is None or a_close is None: continue
    n += 1
    ok_open += a_open[:4] == row[1:5]; ok_close += a_close[:4] == row[1:5]
print("1d vs 4h OHLC matches over", n, "days: open-time labelling", ok_open, "close-time labelling", ok_close)
t = sorted(d)[-1]; print("latest 1d label", e.iso8601(t), "now", e.iso8601(now))
