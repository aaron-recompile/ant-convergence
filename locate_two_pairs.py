#!/usr/bin/env python3
"""定位 kucoin 分子 1129 vs 1127 那两对。

另一路穷尽排查过它那一侧(见证集全天筛/窗口筛、阈值 >0/≥1%/≥5%、去重)
都给 1129,并交来一张 10 分钟桶表。

**而它列出的那 10 个见证字段里没有 `mark`:**
  index / last / oi_contracts / chg24h_pct / vol24h_usd /
  funding_8h / funding_apr / funding_hrs / high24h / low24h

本路测过 kucoin 的 `mark` 变动率 24.2%(窗口内),它在本路的见证集里。
**往「全部不变」的合取里加一个字段只会让它更难成立 ⇒ 本路 1127 ≤ 它 1129,
方向对得上。** 假设:差的两对就是「其余全冻而 mark 变了」。

本脚本:
  ① 用它那 10 个字段算本路分子 —— 应得 1129
  ② 加上 mark 再算 —— 应得 1127
  ③ 若是,逐条列出那两对
  ④ 并出本路的 10 分钟桶表与它对照
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
V = "kucoin_ANTUSDTM"
WLO, WHI = "2026-11-19T14:50:06", "2026-11-19T16:48:21"

PEER10 = ["index", "last", "oi_contracts", "chg24h_pct", "vol24h_usd",
          "funding_8h", "funding_apr", "funding_hrs", "high24h", "low24h"]

rows, seen = [], set()
for p in (os.path.join(D, "ant_2026-11-19.jsonl"),
          os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")):
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
        if WLO <= ts <= WHI:
            rows.append((ts, d))
rows.sort(key=lambda x: x[0])
print("窗口内记录 %d 条 ⇒ 相邻对 %d 对" % (len(rows), len(rows) - 1))
print("（另一路：1,524 记录 / 1,523 对；分母之别已结清）")


def frozen_pairs(wit):
    prev, out = None, []
    for ts, d in rows:
        b = d.get(V)
        if not isinstance(b, dict):
            prev = None
            continue
        sig = tuple(repr(b.get(k)) for k in wit)
        if prev is not None and prev[1] == sig:
            out.append((prev[0], ts))
        prev = (ts, sig)
    return out


a = frozen_pairs(PEER10)
b = frozen_pairs(PEER10 + ["mark"])
print()
print("=== ①② 两种见证集下的分子 ===")
print("  它那 10 个字段:            **%d**  （它报 1129）" % len(a))
print("  那 10 个 + mark:           **%d**  （本路此前报 1127）" % len(b))

print()
print("=== ③ 差的那几对（其余全冻而 mark 变了）===")
sb = set(b)
diff = [p for p in a if p not in sb]
print("  共 %d 对:" % len(diff))
for t0, t1 in diff:
    d0 = next(d for t, d in rows if t == t0)
    d1 = next(d for t, d in rows if t == t1)
    m0 = (d0.get(V) or {}).get("mark")
    m1 = (d1.get(V) or {}).get("mark")
    print("     %sZ → %sZ   mark %s → %s   (差 %+.4f)"
          % (t0[11:], t1[11:], m0, m1,
             (float(m1) - float(m0)) if (m0 is not None and m1 is not None) else 0))
    others = [k for k in PEER10
              if repr((d0.get(V) or {}).get(k)) != repr((d1.get(V) or {}).get(k))]
    print("        那 10 个字段里变了的: %s" % (others or "无（全冻）"))

print()
print("=== ④ 本路 10 分钟桶表（它那 10 个字段，与它对照）===")
PEER_BUCKETS = {"14:50": (86, 120), "15:00": (94, 125), "15:10": (97, 130),
                "15:20": (96, 128), "15:30": (95, 129), "15:40": (97, 131),
                "15:50": (94, 128), "16:00": (94, 128), "16:10": (95, 128),
                "16:20": (99, 134), "16:30": (99, 132), "16:40": (83, 110)}
num = collections.Counter()
den = collections.Counter()
prev = None
for ts, d in rows:
    bb = d.get(V)
    if not isinstance(bb, dict):
        prev = None
        continue
    sig = tuple(repr(bb.get(k)) for k in PEER10)
    if prev is not None:
        bucket = "%s:%s0" % (ts[11:13], ts[14:15])
        den[bucket] += 1
        if prev == sig:
            num[bucket] += 1
    prev = sig
print("| 10 分钟桶 | 本路 | 另一路 | 分子差 | 分母差 |")
print("|---|---|---|---|---|")
tn = td = 0
for k in sorted(set(list(num) + list(den) + list(PEER_BUCKETS))):
    mine = (num[k], den[k])
    peer = PEER_BUCKETS.get(k)
    tn += mine[0]
    td += mine[1]
    if peer:
        dn = mine[0] - peer[0]
        dd = mine[1] - peer[1]
        mark = "" if (dn == 0 and dd == 0) else "  **←**"
        print("| %s | %d/%d | %d/%d | %+d | %+d |%s"
              % (k, mine[0], mine[1], peer[0], peer[1], dn, dd, mark))
    else:
        print("| %s | %d/%d | —— | | |" % (k, mine[0], mine[1]))
print("| **合计** | **%d/%d** | **1129/1523** | **%+d** | **%+d** |"
      % (tn, td, tn - 1129, td - 1523))

print()
print("=== 判读 ===")
print("  若 ① 得 1129 ⇒ 分子差完全由见证集合是否含 mark 造成,账结清;")
print("  且 ③ 列出的那几对就是「其余全冻而 mark 变了」—— 两边都没错,口径不同。")
print("  **而 mark 该不该进见证集:它是被判定的那个量本身。**")
