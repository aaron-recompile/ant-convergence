#!/usr/bin/env python3
"""那条 16:48:26Z 的 yahoo 记录是不是对开盘印的一次直接观测?

实测:yahoo/cnbc 胜出的 72 轮里最高价是 **111.5000 @ 16:48:26Z, src=yahoo** ——
而 16:48:26Z 正是 `traded` 首次翻转的那一刻,111.50 是日线确认的开盘价。

若那条记录的 `price` 是最后成交价,则它是对开盘印的一次**直接观测** ——
而本路 7.49.7 把「日线 open 就是 IPO 撮合印」当成了标准机制下的**推论**。

本脚本:列出该时刻前后所有 spot 块的全文(含 src),并看 yahoo 那条有没有
`open` 字段、它等于多少。
"""
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
FILES = [(os.path.join(D, "ant_2026-11-19.jsonl"), "ant_"),
         (os.path.join(D, "binance_2026-11-19.jsonl"), "binance_"),
         (os.path.join(RESC, "rescued_ant_2026-11-19.jsonl"), "rescue")]

rows, seen = [], set()
for p, tag in FILES:
    if not os.path.exists(p):
        continue
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen or any(ln.startswith(x) for x in CONFLICT):
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        sp = d.get("spot_ANT_nasdaq")
        if isinstance(sp, dict) and "2026-11-19T16:48:20" <= ts <= "2026-11-19T16:48:35":
            rows.append((ts, tag, sp))
rows.sort(key=lambda x: x[0])

print("=== 16:48:20–16:48:35Z 的全部 spot_ANT_nasdaq 块 ===")
for ts, tag, sp in rows:
    print()
    print("  %sZ  [%s]  src=%s  traded=%s" % (ts[11:], tag, sp.get("src"), sp.get("traded")))
    for k in sorted(sp.keys()):
        print("      %-16s %s" % (k, json.dumps(sp[k], ensure_ascii=False)))

print()
print("=== yahoo 那条的关键字段 ===")
y = [(ts, sp) for ts, _, sp in rows if sp.get("src") == "yahoo"]
for ts, sp in y:
    print("  %sZ  price=%s  open=%s  quoted=%s  traded=%s  last_timedate=%s"
          % (ts[11:], sp.get("price"), sp.get("open"), sp.get("quoted"),
             sp.get("traded"), sp.get("last_timedate")))

print()
print("=== 判读 ===")
print("  若 yahoo 那条的 price == 111.50 且 traded=True ⇒")
print("  **那是对首笔成交价的一次直接观测,而它等于日线的 open。**")
print("  若它同时带 open == 111.50 ⇒ yahoo 自己的开盘字段也给同一个数,")
print("  则 111.50 有三个独立出处:本路指示价末值 / yahoo / Nasdaq 日线。")
print()
print("  **但要分清:yahoo 的 `price` 是不是「最后成交价」本路没有确立** ——")
print("  那是另一个端点的字段语义,与 7.57 的 mark/last 之别同类。")
