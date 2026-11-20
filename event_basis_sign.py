#!/usr/bin/env python3
"""独立算第三遍基差符号序列,并核本路第 7 节有没有引用过它。

动机:论文会话承认把笔记 §4 的基差符号数据当独立证据引用了多轮却从未自己算过;
另一路算了一遍,把「最后一次由正转负 15:33:24Z」更正为 16:13:15Z。
**那是个载重的改动,值得第三遍独立计算。**

配对定义(照他的):同一时刻既有指示价(bid==ask 且未成交),
又有 ≥3 家永续的标记价 —— 取各家 mark 的中位数。
符号约定:**P − I**(永续 − 指示价);为负 = 永续在指示价下方。
"""
# ╭───────────────────────────────────────────────────────────────────────────╮
# │ 口径声明（7.56，2026-11-20 加）                                          │
# │                                                                           │
# │ 本脚本用到的永续场所里，**bitget_ANTUSDT / gate_ANT_USDT /               │
# │ kucoin_ANTUSDTM 走 `_throttled` 缓存** —— 命中时返回上一次取数的值。      │
# │ 本路实测 11-19 竞价窗口的冻结平台（同一个 mark 连续不变多久）：          │
# │     缓存三家  中位 18s / p90 20s / 最大 103s / 仅 ~24% 样本在变           │
# │     hl + kraken  中位 5s（= 采样间隔）/ 79–92% 样本在变                   │
# │                                                                           │
# │ ⇒ **任何「同时刻配对」的结论都不能直接用这三家。** 实测后果：            │
# │   15:40–16:30Z 的「P−I 为正 4 次」在剔掉缓存源后变 0；                    │
# │   「最后由正转负 16:13:15Z」是一次缓存刷新，非缓存口径下是 16:41:49Z。    │
# │                                                                           │
# │ ⇒ **阈值穿越类结论不受影响**（已实测）：陈旧报价仍是窗口内真实存在过的   │
# │   报价，不要求同时刻配对。但**计数会随参与场所集合变** ——                │
# │   高于 111.13 的观测数 67（全六家）vs 26（非缓存两家）。                  │
# │                                                                           │
# │ `spot_ANT_nasdaq` **不走缓存**，指示价序列不受此影响。                    │
# ╰───────────────────────────────────────────────────────────────────────────╯
import calendar
import io
import json
import os
import statistics
import subprocess
import time

P = os.path.expanduser("~/ant-convergence/data/ant_2026-11-19.jsonl")
R = os.path.expanduser("~/ant-rescue/rescued_ant_2026-11-19.jsonl")
DOC = os.path.expanduser("~/ant-convergence/data/数据说明.md")
PERPS = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
         "gate_ANT_USDT", "kucoin_ANTUSDTM"]
WIN_LO, WIN_HI = "2026-11-19T15:40:00", "2026-11-19T16:30:00"
FULL_LO, FULL_HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"

# ── ① 先回答他的问题:本路文档有没有引用过这个数 ─────────────────
print("=== ① 本路第 7 节有没有引用过基差符号/P−I/那个翻转时刻 ===")
pats = ["15:33:24", "16:13:15", "P − I", "P-I", "基差符号", "几乎恒为负", "464", "631"]
hit_any = False
for p in pats:
    r = subprocess.run(["grep", "-n", p, DOC], capture_output=True, text=True)
    lines = [x for x in r.stdout.strip().split("\n") if x]
    if lines:
        hit_any = True
        print("  命中 %-12s %d 处" % (p, len(lines)))
        for x in lines[:3]:
            print("     %s" % x[:160])
if not hit_any:
    print("  **零命中 —— 本路第 7 节从未引用过这个数。**")
    print("  （本路第 7 节只写现货采集:文件/字段/口径/瑕疵/收盘价;")
    print("    基差与永续横截面不是本路的交付物。）")

# ── ② 独立算第三遍 ───────────────────────────────────────────
rows, seen = [], set()
for path in (P, R):
    if not os.path.exists(path):
        continue
    for ln in io.open(path, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen:
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if not (FULL_LO <= ts <= FULL_HI):
            continue
        rows.append((ts, d))
rows.sort(key=lambda x: x[0])

pairs = []          # (ts, I, P, P-I)
for ts, d in rows:
    sp = d.get("spot_ANT_nasdaq") or {}
    b, a = sp.get("bid"), sp.get("ask")
    if b is None or a is None or sp.get("traded"):
        continue
    if abs(float(b) - float(a)) > 1e-9:
        continue
    marks = [float((d.get(v) or {}).get("mark"))
             for v in PERPS
             if isinstance((d.get(v) or {}).get("mark"), (int, float))]
    if len(marks) < 3:
        continue
    pm = statistics.median(marks)
    pairs.append((ts, float(b), pm, pm - float(b)))

print()
print("=== ② 独立算第三遍（符号约定 P − I，负 = 永续在指示价下方）===")
win = [x for x in pairs if WIN_LO <= x[0] <= WIN_HI]
print("| 项 | 笔记报 | 他实测 | **本路实测** |")
print("|---|---|---|---|")
print("| 15:40–16:30Z 配对样本 | 631 | 661 | **%d** |" % len(win))
pos = [x for x in win if x[3] > 0]
print("| 该窗口 P − I 为正 | 4 | 4 | **%d** |" % len(pos))

# 最长连续为负(全窗口)
best = cur = 0
for _, _, _, dl in pairs:
    cur = cur + 1 if dl < 0 else 0
    best = max(best, cur)
print("| 最长连续为负（全窗口） | 464 | 423 | **%d** |" % best)

# 最后一次由正转负
flip = None
for i in range(1, len(pairs)):
    if pairs[i - 1][3] > 0 and pairs[i][3] < 0:
        flip = pairs[i][0]
print("| 最后一次由正转负 | 15:33:24Z | 16:13:15Z | **%s** |"
      % (flip[11:] + "Z" if flip else "无"))

print()
print("全窗口配对 %d 条，其中 P−I 为正 %d 条（%.2f%%）"
      % (len(pairs), sum(1 for x in pairs if x[3] > 0),
         100.0 * sum(1 for x in pairs if x[3] > 0) / len(pairs)))
print("翻转之后仍为正的时刻：")
if flip:
    after = [x for x in pairs if x[0] >= "2026-11-19T15:33:24" and x[3] > 0]
    for ts, I, Pm, dl in after:
        print("   %s  I=%.4f  P=%.4f  P−I=%+.4f" % (ts[11:] + "Z", I, Pm, dl))
    print("  → 共 %d 次。**「15:33:24Z 翻转并锁死」若有此说，不成立。**" % len(after))
