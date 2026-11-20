#!/usr/bin/env python3
"""把「估计量效应」与「陈旧性效应」分开:那 4 个 P−I 为正的时刻，谁坐在中位?

剔掉缓存源后 15:40–16:30Z 窗口的「P−I 为正」从 4 变 0。但这里混着两件:
  A 估计量:五家中位 ↔ 两家中位(两家的"中位"是均值)
  B 陈旧性:gate/bitget/kucoin 命中缓存时返回上一次取数的值(实测早 6.8–7.1s)

分开的办法:对那 4 个时刻逐一列出五家的 mark 与指示价。
  - 若中位由某个**缓存源**占据,而两家非缓存源都明显低于指示价
    ⇒ 那 4 次为正是**缓存陈旧**造出来的(B)。
  - 若两家非缓存源本身就跨在指示价两侧
    ⇒ 是估计量差异(A),与缓存无关。
"""
import io
import json
import os
import statistics

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
WIN_LO, WIN_HI = "2026-11-19T15:40:00", "2026-11-19T16:30:00"
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
ALL5 = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
        "gate_ANT_USDT", "kucoin_ANTUSDTM"]
CACHED = {"bitget_ANTUSDT", "gate_ANT_USDT", "kucoin_ANTUSDTM"}

rows, seen = [], set()
for path in (os.path.join(D, "ant_2026-11-19.jsonl"),
             os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")):
    if not os.path.exists(path):
        continue
    for ln in io.open(path, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen or any(ln.startswith(x) for x in CONFLICT):
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if LO <= ts <= HI:
            rows.append((ts, d))
rows.sort(key=lambda x: x[0])

cands = []
for ts, d in rows:
    sp = d.get("spot_ANT_nasdaq") or {}
    b, a = sp.get("bid"), sp.get("ask")
    if b is None or a is None or sp.get("traded"):
        continue
    if abs(float(b) - float(a)) > 1e-9:
        continue
    marks = {}
    for v in ALL5:
        m = (d.get(v) or {}).get("mark")
        if isinstance(m, (int, float)):
            marks[v] = float(m)
    if len(marks) < 3:
        continue
    I = float(b)
    pm5 = statistics.median(marks.values())
    if not (WIN_LO <= ts <= WIN_HI):
        continue
    if pm5 - I > 0:
        cands.append((ts, I, marks, pm5))

print("=== 15:40–16:30Z 窗口里 P−I 为正的时刻（全五家中位）===")
print("  共 %d 个" % len(cands))
print()
for ts, I, marks, pm5 in cands:
    clean = {k: v for k, v in marks.items() if k not in CACHED}
    cm = statistics.median(clean.values()) if clean else None
    ordered = sorted(marks.items(), key=lambda kv: kv[1])
    mid_name = ordered[len(ordered) // 2][0] if len(ordered) % 2 else "(两者均值)"
    print("  %sZ   指示价 I = %.4f" % (ts[11:], I))
    for k, v in ordered:
        tag = " **[缓存]**" if k in CACHED else ""
        print("     %-22s %9.4f   (−I = %+.4f)%s" % (k, v, v - I, tag))
    print("     五家中位 = %.4f  (P−I = %+.4f)   中位由: %s"
          % (pm5, pm5 - I, mid_name))
    if cm is not None:
        print("     非缓存两家中位 = %.4f  (P−I = %+.4f)" % (cm, cm - I))
        both_below = all(v < I for v in clean.values())
        print("     两家非缓存是否都低于指示价: %s" % ("**是**" if both_below else "否"))
    print()

print("=== 判读 ===")
n_mid_cached = sum(1 for ts, I, marks, pm5 in cands
                   if sorted(marks.items(), key=lambda kv: kv[1])
                   [len(marks) // 2][0] in CACHED)
n_clean_below = 0
for ts, I, marks, pm5 in cands:
    clean = [v for k, v in marks.items() if k not in CACHED]
    if clean and all(v < I for v in clean):
        n_clean_below += 1
print("  中位由缓存源占据的时刻: %d / %d" % (n_mid_cached, len(cands)))
print("  两家非缓存都低于指示价的时刻: %d / %d" % (n_clean_below, len(cands)))
print()
if cands and n_clean_below == len(cands):
    print("  **所有为正的时刻上，两家非缓存源都在指示价下方**")
    print("  ⇒ 那几次「P−I 为正」是由缓存源的报价抬上去的，")
    print("     而缓存源命中时返回的是上一次取数(实测早 6.8–7.1 秒)的值。")
    print("  ⇒ **它们是陈旧性造出来的(B)，不是估计量差异(A)。**")
elif cands:
    print("  有时刻上非缓存源本身跨在指示价两侧 ⇒ 至少部分是估计量差异(A)。")
else:
    print("  窗口内没有为正的时刻 —— 无需分离。")
