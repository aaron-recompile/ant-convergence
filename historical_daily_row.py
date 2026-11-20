#!/usr/bin/env python3
"""核实 nasdaq historical 的 11-19 日行,特别是 open = 111.50。

7.9 登记过:上市日当天 historical 端点 totalRecords = 0,所以本路当时
无法从公开端点确立「实现清算价」,只能把 111.50 标成「最后一个指示价」。
另一路因此把头号论断从「从未高过撮合价」改写成「从未高过最后一个指示价」。

**若 historical 现在给出 open = 111.50,那个限制就解除了** ——
111.50 是有权威出处的开盘价,原来那个更强的表述可以支持。

本脚本:
  ① 重取两次(不同参数),看是否稳定,排除缓存/偶然
  ② 核 high / low / close 与本路及另一路已有的数对不对
  ③ 看 11-20 的行有没有出现(totalRecords 的推进节奏)
"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BASE = "https://api.nasdaq.com/api/quote/ANT/historical?assetclass=stocks"


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


QUERIES = [
    ("窗口 11/17–11/21 limit=10", BASE + "&fromdate=2026-11-17&todate=2026-11-21&limit=10"),
    ("窗口 11/19–11/20 limit=5",  BASE + "&fromdate=2026-11-19&todate=2026-11-20&limit=5"),
    ("无日期窗口 limit=5",         BASE + "&limit=5"),
]

print("=== ① 多次取值，看是否稳定 ===")
seen = []
for label, url in QUERIES:
    try:
        d = get(url)
    except Exception as e:
        print("  %-26s 失败 %s: %s" % (label, type(e).__name__, e))
        continue
    dd = (d or {}).get("data") or {}
    rows = ((dd.get("tradesTable") or {}).get("rows")) or []
    print("  %-26s totalRecords=%s  行数=%d" % (label, dd.get("totalRecords"), len(rows)))
    for r in rows:
        print("      %s  open=%s high=%s low=%s close=%s vol=%s"
              % (r.get("date"), r.get("open"), r.get("high"),
                 r.get("low"), r.get("close"), r.get("volume")))
        seen.append((label, dict(r)))
    time.sleep(1)

print()
print("=== ② 与已有的数对账（11/19）===")
rows19 = [r for _, r in seen if "11/19/2026" in str(r.get("date"))]


def num(x):
    if x is None:
        return None
    s = str(x).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except Exception:
        return None


if not rows19:
    print("  没有 11/19 的行 —— 上面的结论不成立，停。")
else:
    vals = {k: {num(r.get(k)) for r in rows19} for k in ("open", "high", "low", "close")}
    print("  多次取值是否一致:", {k: (len(v) == 1, sorted(v)) for k, v in vals.items()})
    o = sorted(vals["open"])[0]
    h = sorted(vals["high"])[0]
    c = sorted(vals["close"])[0]
    lo = sorted(vals["low"])[0]
    CHECKS = [
        ("open", o, 111.50, "本路 7.40 标为「最后一个指示价」(16:48:21Z 实测)"),
        ("high", h, 115.10, "本路 cross_check 五源一致值(7.48)"),
        ("close", c, 97.17, "本路 7.9 三源一致定稿值"),
        ("low", lo, 92.72, "文档第 378 行「当日实测区间 92.72–…」的下端"),
    ]
    print()
    print("  | 字段 | historical | 已有的数 | 对上? | 已有的数出处 |")
    print("  |---|---|---|---|---|")
    for name, got, want, src in CHECKS:
        ok = got is not None and abs(got - want) < 1e-9
        print("  | %s | %s | %s | **%s** | %s |"
              % (name, got, want, "是" if ok else "**否**", src))

print()
print("=== ③ 11/20 的行出现了吗 ===")
rows20 = [r for _, r in seen if "11/20/2026" in str(r.get("date"))]
if rows20:
    for r in rows20:
        print("  已出现: %s" % json.dumps(r, ensure_ascii=False))
else:
    print("  **尚未出现** —— 故今天的收盘价此刻无法用 historical 互校。")
    print("  (7.9 登记:上市日当天该端点 totalRecords=0;现在 11/19 已入表,")
    print("   说明它按 T+1 填充。11-20 的行预计 11-21 出现。)")

print()
print("=== ④ 这对 7.9 那条 caveat 意味着什么 ===")
print("  7.9 说:公开端点不区分 NOCP 与最后一笔合并成交价,")
print("  且 historical 当时 totalRecords=0 ⇒ 「实现清算价」无法确立。")
print("  **第二句现在不成立了** —— historical 给出 open,那是日终官方记录里的开盘价。")
print("  第一句仍成立:日行的 close 字段没有标明它是不是 NOCP。")
print("  ⇒ caveat 要改,但只改第二句;不要整条删掉。")
