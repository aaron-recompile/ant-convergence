#!/usr/bin/env python3
"""核 loop_close 自动写的收盘记录与 spot_close_fix 手写的差在哪,并独立算今天的三源。

11-19 的 close json 是 spot_close_fix.py(一次性)写的:带 sources 三源互校 + caveat。
11-20 的是 ant_spot.py 的 loop_close 自动写的:official_close() 只返回 nasdaq 一路。
⇒ **自动路径产出的记录比手动路径弱**,而自动路径才是以后每天都会走的那条。
"""
import io
import json
import os
import urllib.request

D = os.path.expanduser("~/ant-convergence/data")
Y = os.path.join(D, "close_2026-11-19.json")
T = os.path.join(D, "close_2026-11-20.json")

y = json.load(io.open(Y)) if os.path.exists(Y) else {}
t = json.load(io.open(T)) if os.path.exists(T) else {}

ky, kt = set(y), set(t)
print("=== 字段差 ===")
print("  11-19 字段 %d 个 / 11-20 字段 %d 个" % (len(ky), len(kt)))
only_y = sorted(ky - kt)
only_t = sorted(kt - ky)
print()
print("  **只在 11-19 有(即今天缺的):**")
for k in only_y:
    v = y[k]
    s = json.dumps(v, ensure_ascii=False)
    print("     %-28s %s" % (k, s[:96] + ("…" if len(s) > 96 else "")))
print()
print("  只在 11-20 有:")
for k in only_t:
    s = json.dumps(t[k], ensure_ascii=False)
    print("     %-28s %s" % (k, s[:96]))
print()
print("=== 今天那份的全部内容 ===")
for k in sorted(kt):
    s = json.dumps(t[k], ensure_ascii=False)
    print("  %-30s %s" % (k, s[:110]))

# ── 独立算今天的三源 ──────────────────────────────────────────
print()
print("=== 独立三源互校(今天)===")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def num(x):
    if x is None:
        return None
    s = str(x).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None


srcs = {}

# 1) nasdaq info secondaryData
try:
    d = get("https://api.nasdaq.com/api/quote/ANT/info?assetclass=stocks")
    sec = ((d or {}).get("data") or {}).get("secondaryData") or {}
    stamp = sec.get("lastTradeTimestamp")
    srcs["nasdaq_info_secondary"] = {
        "close_usd": num(sec.get("lastSalePrice")) if stamp and "Closed" in str(stamp) else None,
        "stamp": stamp,
        "path": "/api/quote/ANT/info  data.secondaryData.lastSalePrice",
    }
except Exception as e:
    srcs["nasdaq_info_secondary"] = {"error": "%s: %s" % (type(e).__name__, e)}

# 2) nasdaq summary PreviousClose 不是今日收盘 —— 用 summary 的 TodayHighLow 不行,
#    改用 nasdaq historical(收盘后应已有当日行)
try:
    d = get("https://api.nasdaq.com/api/quote/ANT/historical"
            "?assetclass=stocks&fromdate=2026-11-18&todate=2026-11-21&limit=10")
    rows = (((d or {}).get("data") or {}).get("tradesTable") or {}).get("rows") or []
    hit = [r for r in rows if "11/20/2026" in str(r.get("date"))]
    srcs["nasdaq_historical"] = {
        "close_usd": num(hit[0].get("close")) if hit else None,
        "totalRecords": ((d or {}).get("data") or {}).get("totalRecords"),
        "path": "/api/quote/ANT/historical  rows[date=11/20/2026].close",
    }
except Exception as e:
    srcs["nasdaq_historical"] = {"error": "%s: %s" % (type(e).__name__, e)}

# 3) yahoo chart meta
try:
    d = get("https://query1.finance.yahoo.com/v8/finance/chart/ANT?range=1d&interval=1d")
    res = (((d or {}).get("chart") or {}).get("result") or [{}])[0]
    meta = res.get("meta") or {}
    srcs["yahoo_meta"] = {
        "close_usd": num(meta.get("regularMarketPrice")),
        "chartPreviousClose": num(meta.get("chartPreviousClose")),
        "path": "v8/finance/chart  meta.regularMarketPrice",
    }
except Exception as e:
    srcs["yahoo_meta"] = {"error": "%s: %s" % (type(e).__name__, e)}

# 4) cnbc
try:
    d = get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
            "?symbols=ANT&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1"
            "&output=json&events=1")
    q = (((d or {}).get("FormattedQuoteResult") or {}).get("FormattedQuote") or [{}])[0]
    srcs["cnbc"] = {
        "close_usd": num(q.get("last")),
        "last_time": q.get("last_time_msec") or q.get("last_time"),
        "path": "quote.cnbc.com  FormattedQuote.last",
    }
except Exception as e:
    srcs["cnbc"] = {"error": "%s: %s" % (type(e).__name__, e)}

for k, v in srcs.items():
    print("  %-24s %s" % (k, json.dumps(v, ensure_ascii=False)[:150]))

vals = sorted({v["close_usd"] for v in srcs.values()
               if isinstance(v, dict) and v.get("close_usd") is not None})
print()
print("  取值集合 = %s   一致: %s" % (vals, len(vals) == 1))
print("  loop_close 写的是 %s" % t.get("official_close_usd"))
if vals and t.get("official_close_usd") is not None:
    agree = all(abs(v - float(t["official_close_usd"])) < 1e-9 for v in vals)
    print("  与 loop_close 一致: %s" % agree)

io.open("/tmp/today_sources.json", "w").write(
    json.dumps(srcs, ensure_ascii=False, indent=1))
print()
print("  三源结果已写 /tmp/today_sources.json")
