#!/usr/bin/env python3
"""决定性检验:CNBC 的 88.30 是不是我自己加的 exthrs=1 造成的?

7.49.2 我断言「CNBC 88.30 是真异议,不是口径错位」,依据是 12 秒间隔
三次重取 last 稳定在 88.30、戳固定 16:00:00-0500。

**但那是 21:06Z 测的,盘后已经平静 —— 一个冻住的盘后价当然不动。**
而今天收盘前后的采样显示:88.30 不在收盘前的价格路径上(20:59:57Z 为 88.395),
它正落在盘后价区间 88.1–88.3 的中间。

而本路请求 CNBC 的 URL 带着 **exthrs=1** —— 那是「要盘后数据」。
若去掉它 last 变成 88.91,那么:
  - 这个「异议」是本路自己的请求参数造成的,不是厂商分歧;
  - 7.49.2 的结论要更正,而我先前提出又撤回的那个假设更接近对的。
"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BASE = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
        "?symbols=ANT&requestMethod=itv&noform=1&partnerId=2&fund=1"
        "&output=json&events=1")

VARIANTS = [
    ("本路一直用的（exthrs=1）", BASE + "&exthrs=1"),
    ("去掉 exthrs", BASE),
    ("exthrs=0", BASE + "&exthrs=0"),
]


def money(s):
    if s is None:
        return None
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


print("| 变体 | last | last_timedate | previous_day_closing | 其他可能的收盘字段 |")
print("|---|---|---|---|---|")
got = {}
for label, url in VARIANTS:
    try:
        req = urllib.request.Request(url, headers=UA)
        d = json.loads(urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace"))
        q = d["FormattedQuoteResult"]["FormattedQuote"][0]
        last = money(q.get("last"))
        got[label] = last
        # 找一找有没有别的字段像「正常时段收盘价」
        cand = {k: v for k, v in q.items()
                if isinstance(v, (str, int, float))
                and any(s in k.lower() for s in ("close", "last", "prev"))}
        extra = {k: v for k, v in cand.items()
                 if k not in ("last", "last_time", "last_timedate", "last_time_msec")}
        print("| %s | **%s** | %s | %s | %s |"
              % (label, last, q.get("last_timedate"),
                 q.get("previous_day_closing"),
                 json.dumps(extra, ensure_ascii=False)[:130]))
    except Exception as e:
        print("| %s | 失败 %s | | | |" % (label, type(e).__name__))
    time.sleep(1)

print()
print("=== 判读 ===")
a = got.get("本路一直用的（exthrs=1）")
b = got.get("去掉 exthrs")
c = got.get("exthrs=0")
print("  exthrs=1 → %s / 去掉 → %s / exthrs=0 → %s" % (a, b, c))
if a is not None and (b is not None or c is not None):
    other = b if b is not None else c
    if abs(a - other) > 1e-9:
        print()
        print("  **取值随 exthrs 改变 ⇒ 这个「异议」是本路自己的请求参数造成的。**")
        print("  ⇒ 7.49.2 的结论要更正:不是厂商分歧,是口径错位,")
        print("     而口径是**我选的**。我先前提出又撤回的那个假设更接近对的 ——")
        print("     撤回它的那次检验(21:06Z 三连取)在盘后平静期做的,")
        print("     **一个冻住的盘后价当然不动**,所以那次检验本身没有判别力。")
        if abs(other - 88.91) < 0.01:
            print("  ⇒ 且去掉 exthrs 后与 nasdaq/yahoo 一致 ⇒ **三源其实是一致的**。")
    else:
        print()
        print("  取值不随 exthrs 改变 ⇒ 不是请求参数造成的,7.49.2 的结论保留,")
        print("  但「为什么 88.30 落在盘后价区间里」仍未解释。")
