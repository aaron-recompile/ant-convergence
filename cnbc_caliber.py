#!/usr/bin/env python3
"""决定性检验:CNBC 的 last 是收盘价字段,还是贴着 4:00 PM 标签的盘后实时价?

若 last 在动而 last_time 不动 ⇒ 两个字段不同步 ⇒ last 不能用来识别正常时段收盘价。
若两者都不动 ⇒ 它确实钉在收盘那一笔,则今天 88.30 vs 88.91 是真分歧。

同时取 yahoo 的 regularMarketPrice(口径明写 regularMarket)与
nasdaq secondaryData(带 "Closed at" 戳)作为对照 —— 它们应当不动。
"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get(u):
    req = urllib.request.Request(u, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def money(s):
    if s is None:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


CNBC = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
        "?symbols=ANT&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1"
        "&output=json&events=1")
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/ANT?range=1d&interval=1m"
NASDAQ = "https://api.nasdaq.com/api/quote/ANT/info?assetclass=stocks"

print("| 轮次 | 取样时刻(UTC) | cnbc.last | cnbc.last_time | cnbc.last_timedate | yahoo.regularMarketPrice | nasdaq.secondary + 戳 |")
print("|---|---|---|---|---|---|---|")
rows = []
for i in range(3):
    now = time.strftime("%H:%M:%SZ", time.gmtime())
    c = y = n = ns = ct = ctd = None
    try:
        d = get(CNBC)
        q = d["FormattedQuoteResult"]["FormattedQuote"][0]
        c = money(q.get("last"))
        ct = q.get("last_time") or q.get("last_time_msec")
        ctd = q.get("last_timedate")
    except Exception as e:
        ct = "ERR %s" % type(e).__name__
    try:
        d = get(YAHOO)
        m = ((d.get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
        y = m.get("regularMarketPrice")
    except Exception:
        pass
    try:
        d = get(NASDAQ)
        sec = ((d or {}).get("data") or {}).get("secondaryData") or {}
        n = money(sec.get("lastSalePrice"))
        ns = sec.get("lastTradeTimestamp")
    except Exception:
        pass
    rows.append((now, c, ct, ctd, y, n, ns))
    print("| %d | %s | **%s** | %s | %s | %s | %s / %s |"
          % (i + 1, now, c, ct, ctd, y, n, (ns or "")[:34]))
    if i < 2:
        time.sleep(12)

print()
print("=== 判读 ===")
cs = [r[1] for r in rows if r[1] is not None]
cts = {str(r[2]) for r in rows if r[2] is not None}
ys = {r[4] for r in rows if r[4] is not None}
ns = {r[5] for r in rows if r[5] is not None}
print("  cnbc.last 取值集合:      %s  (变了: %s)" % (sorted(set(cs)), len(set(cs)) > 1))
print("  cnbc.last_time 集合:     %s  (变了: %s)" % (sorted(cts), len(cts) > 1))
print("  yahoo.regularMarketPrice: %s  (变了: %s)" % (sorted(ys), len(ys) > 1))
print("  nasdaq.secondaryData:     %s  (变了: %s)" % (sorted(ns), len(ns) > 1))
print()
if len(set(cs)) > 1 and len(cts) == 1:
    print("  **CNBC 的 last 在动而 last_time 不动 ⇒ 两字段不同步。**")
    print("  ⇒ cnbc.last 不能用来识别正常时段收盘价:它是盘后实时价,贴着 4:00 PM 的标签。")
    print("  ⇒ 今天的 88.30/88.52 不是「异议收盘价」,是口径不同的数。")
    print("  ⇒ 昨天的「三源一致 97.17」里,CNBC 那一票是**凑巧**(当时 last 恰好还停在收盘那笔),")
    print("     真正口径匹配的只有 nasdaq secondaryData 与 yahoo regularMarketPrice 两源。")
elif len(set(cs)) == 1:
    print("  CNBC 的 last 三轮未变 —— 本检验不能判定;需在价格确实变动的时段重做。")
else:
    print("  CNBC 的 last 与 last_time 同步变化 ⇒ 它在跟踪实时价且戳也跟着走,")
    print("  则今天的差异需要另找解释。")
