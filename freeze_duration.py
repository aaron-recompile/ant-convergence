#!/usr/bin/env python3
"""直接量 11-19 的缓存陈旧幅度 —— 不需要新加的 obs_epoch_f 字段。

办法:对每个场所,量「同一个 mark 连续不变持续多少秒」。
走缓存的场所应出现明显更长的冻结平台;非缓存的应几乎每笔都动。

这把另一路给的规格(「按 15s 放宽，实测已见 −7s」)
变成 11-19 当天的实测值 —— 而那一天没有 obs_epoch_f。
"""
import collections
import io
import json
import os
import statistics

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD",
          "bitget_ANTUSDT", "gate_ANT_USDT", "kucoin_ANTUSDTM"]
CACHED = {"bitget_ANTUSDT", "gate_ANT_USDT", "kucoin_ANTUSDTM"}
import calendar
import time


def ep(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


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

print("竞价窗口 %s–%s，记录 %d 条" % (LO[11:], HI[11:], len(rows)))
print("（同一秒可能多条，按秒去重后算冻结时长）")
print()

series = {v: [] for v in VENUES}
for ts, d in rows:
    t = ep(ts)
    for v in VENUES:
        m = (d.get(v) or {}).get("mark")
        if isinstance(m, (int, float)):
            series[v].append((t, float(m)))

print("| 场所 | 样本 | 不同取值 | **冻结时长 中位** | p90 | 最大 | 每笔都变的比例 |")
print("|---|---|---|---|---|---|---|")
for v in VENUES:
    s = series[v]
    if len(s) < 5:
        print("| %s | %d | — | — | — | — | — |" % (v, len(s)))
        continue
    # 按秒去重（保留该秒第一个）
    ded, seent = [], set()
    for t, m in s:
        if t in seent:
            continue
        seent.add(t)
        ded.append((t, m))
    runs = []
    start = ded[0][0]
    cur = ded[0][1]
    changes = 0
    for i in range(1, len(ded)):
        t, m = ded[i]
        if m != cur:
            runs.append(t - start)
            changes += 1
            start, cur = t, m
    runs.append(ded[-1][0] - start)
    runs = [r for r in runs if r >= 0]
    srt = sorted(runs)
    tag = " **[缓存]**" if v in CACHED else ""
    print("| %s%s | %d | %d | **%.0fs** | %.0fs | %.0fs | %.1f%% |"
          % (v, tag, len(ded), len(set(m for _, m in ded)),
             statistics.median(srt), srt[int(0.9 * (len(srt) - 1))], srt[-1],
             100.0 * changes / max(1, len(ded) - 1)))

print()
print("=== 16:12:50–16:13:20Z（那 4 次为正所在的区间）逐秒 ===")
print("| 时刻 | hl | kraken | kucoin | gate | bitget |")
print("|---|---|---|---|---|---|")
shown = set()
for ts, d in rows:
    if not ("2026-11-19T16:12:50" <= ts <= "2026-11-19T16:13:20"):
        continue
    if ts in shown:
        continue
    shown.add(ts)
    cells = []
    for v in ("hl_xyz_ANT", "kraken_PF_ANTXUSD", "kucoin_ANTUSDTM",
              "gate_ANT_USDT", "bitget_ANTUSDT"):
        m = (d.get(v) or {}).get("mark")
        cells.append("%.4f" % m if isinstance(m, (int, float)) else "—")
    print("| %sZ | %s |" % (ts[11:], " | ".join(cells)))

print()
print("=== 判读 ===")
print("  若缓存三家的冻结时长中位显著大于非缓存两家,")
print("  则 11-19 当天的缓存陈旧幅度已被直接量出 —— 不依赖 obs_epoch_f。")
print("  而那三家在 16:12:50–16:13:20Z 一动不动、两家非缓存逐笔在动,")
print("  就是那 4 次「P−I 为正」的直接成因。")
