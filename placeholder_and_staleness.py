#!/usr/bin/env python3
"""三件:核首笔那一秒的 cnbc 记录、核占位价的真实口径、把 last_timedate 做成探测器。

另一路报:
  - 16:48:26Z mini 的 ant_ 记录 src=cnbc、traded=True、**price=83.0**(发行价);
    成因是 spot_ant() 的胜出条件 `if r.get("traded") and r.get("price")`;
  - README 必读第 4 条写「**纳斯达克接口**把发行价当行情返回,窗口内 45 条」
    —— 而 src=nasdaq 的占位价 **0 条**,那 70 条(并集全天)是 yahoo 69 + cnbc 1;
    「45 条」的真实口径是「仅 mini 的文件、全天」= 44 条首笔前 + **1 条就在首笔那一秒**;
  - 那条 cnbc 自带陈旧标记:`last_timedate: "11/18/26 EST"` —— 它自己说报价来自前一天,
    **而那个字段我们从没用过**。

本脚本第三件是本路的加项:**把 `last_timedate` 做成通用陈旧探测器** ——
扫全部 spot 块,看有多少条的 last_timedate 不指向 11/19。
"""
import collections
import io
import json
import os
import re

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
FILES = [(os.path.join(D, "ant_2026-11-19.jsonl"), "ant_(mini)"),
         (os.path.join(D, "binance_2026-11-19.jsonl"), "binance_(MacBook)"),
         (os.path.join(RESC, "rescued_ant_2026-11-19.jsonl"), "抢救档")]
FIRST = "2026-11-19T16:48:26"

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
        if ts.startswith("2026-11-19") and isinstance(sp, dict):
            rows.append((ts, tag, sp))
rows.sort(key=lambda x: x[0])
print("全天 spot 块 %d 个" % len(rows))

print()
print("=== ① 首笔那一秒的全部记录 ===")
for ts, tag, sp in rows:
    if not ("2026-11-19T16:48:21" <= ts <= "2026-11-19T16:48:31"):
        continue
    print("  %sZ [%-18s] src=%-8s traded=%-5s price=%-9s bid=%-8s ask=%-8s last_timedate=%s"
          % (ts[11:], tag, sp.get("src"), sp.get("traded"),
             sp.get("price"), sp.get("bid"), sp.get("ask"),
             json.dumps(sp.get("last_timedate"), ensure_ascii=False)))

print()
print("=== ② 占位价（traded=True ∧ price==83.0）的真实口径 ===")
ph = [(ts, tag, sp) for ts, tag, sp in rows
      if sp.get("traded") and isinstance(sp.get("price"), (int, float))
      and abs(float(sp["price"]) - 83.0) < 1e-9]
print("  | 口径 | 条数 | src 分布 |")
print("  |---|---|---|")


def srcs(items):
    c = collections.Counter(sp.get("src") or "(无)" for _, _, sp in items)
    return ", ".join("%s %d" % (k, v) for k, v in c.most_common())


print("  | 并集全天 | **%d** | %s |" % (len(ph), srcs(ph)))
pre = [x for x in ph if x[0] < FIRST]
post = [x for x in ph if x[0] >= FIRST]
print("  | 首笔之前 | %d | %s |" % (len(pre), srcs(pre)))
print("  | **首笔及之后** | **%d** | **%s** |" % (len(post), srcs(post)))
ant_only = [x for x in ph if x[1] == "ant_(mini)"]
print("  | 仅 ant_(mini) 全天 | **%d** | %s |" % (len(ant_only), srcs(ant_only)))
nas = [x for x in ph if (x[2].get("src") == "nasdaq")]
print("  | **src=nasdaq** | **%d** | —— |" % len(nas))
print()
print("  首笔及之后那些的时刻: %s"
      % ", ".join("%sZ[%s]" % (t[11:], sp.get("src")) for t, _, sp in post))

print()
print("=== ③ 本路加项:把 last_timedate 做成通用陈旧探测器 ===")
have = [(ts, tag, sp) for ts, tag, sp in rows if sp.get("last_timedate")]
print("  带 last_timedate 的块: %d / %d" % (len(have), len(rows)))
pat = collections.Counter()
stale = []
for ts, tag, sp in have:
    v = str(sp["last_timedate"])
    # 形如 "11/18/26 EST" 或 "Nov 19, 2026 11:48 AM ET"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", v)
    if m:
        mm, dd = int(m.group(1)), int(m.group(2))
        key = "%02d/%02d" % (mm, dd)
    else:
        m2 = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})", v)
        key = ("%s %02d" % (m2.group(1), int(m2.group(2)))) if m2 else "(未解析)"
    pat[key] += 1
    if key not in ("11/19", "Nov 19"):
        stale.append((ts, tag, sp.get("src"), v, sp.get("price")))
print("  last_timedate 解析出的日期分布:")
for k, n in pat.most_common(8):
    flag = "  **← 不是 11/19**" if k not in ("11/19", "Nov 19") else ""
    print("     %-12s %d%s" % (k, n, flag))
print()
print("  **不指向 11/19 的块: %d 条**" % len(stale))
for ts, tag, src, v, pr in stale[:8]:
    print("     %sZ [%s] src=%s  last_timedate=%r  price=%s"
          % (ts[11:], tag, src, v, pr))

print()
print("=== ④ 本路有没有任何路径读 spot_ANT_nasdaq.price ===")
HERE = os.path.expanduser("~/ant-convergence")
hits = []
for f in sorted(os.listdir(HERE)):
    if not f.endswith(".py"):
        continue
    try:
        txt = io.open(os.path.join(HERE, f), errors="replace").read()
    except Exception:
        continue
    if "spot_ANT_nasdaq" not in txt:
        continue
    reads_price = bool(re.search(r'spot_ANT_nasdaq[^\n]{0,80}', txt)) and \
        bool(re.search(r'sp\.get\("price"\)|sp\["price"\]|\bprice\b', txt))
    hits.append((f, reads_price))
print("  引用 spot_ANT_nasdaq 的本路脚本:")
for f, rp in hits:
    print("     %-34s 文本里出现 price: %s" % (f, "是（需人工看）" if rp else "否"))
print()
print("  注:本路的指示价判据只读 bid / ask / traded;7.48 查 114.853 时读过 price,")
print("     而那 4 条已确认 src=nasdaq。此表只是提示哪些文件需要人工过一眼。")
