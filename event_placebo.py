#!/usr/bin/env python3
"""把口径对齐到他的做法（5 家投票、≥3 同向），再比真事件 vs 安慰剂。

目的：上一轮我按**单个场所**算，得到「事件前 56–60%」而他报的是 50%。
那个差可能只是口径不同（他是 5 家投票），也可能是数字不对。
**对齐口径才能区分这两件事** —— 否则我报的是前者，却会被读成后者。
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
import random
import time

P = os.path.expanduser("~/ant-convergence/data/ant_2026-11-19.jsonl")
R = os.path.expanduser("~/ant-rescue/rescued_ant_2026-11-19.jsonl")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
W = 60
SEED = 20261119
REPS = 200

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
        if not (LO <= ts <= HI):
            continue
        ep = d.get("ts_epoch")
        if ep is None:
            try:
                ep = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%S"))
            except Exception:
                continue
        rows.append((ep, d))
rows.sort(key=lambda x: x[0])

# 先看这 5 家永续在窗口里各字段的可用率 —— 投票要知道分母
PERPS = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
         "gate_ANT_USDT", "kucoin_ANTUSDTM"]
print("=== 窗口内各永续场所的字段可用率（投票的分母）===")
for v in PERPS:
    n = sum(1 for _, d in rows if isinstance(d.get(v), dict))
    for f in ("mark", "last", "index", "mid"):
        k = sum(1 for _, d in rows
                if isinstance((d.get(v) or {}).get(f), (int, float)))
        if k:
            print("  %-22s %-6s %5d / %5d 条" % (v, f, k, len(rows)))

ind = []
for ep, d in rows:
    sp = d.get("spot_ANT_nasdaq") or {}
    b, a = sp.get("bid"), sp.get("ask")
    if b is None or a is None or sp.get("traded"):
        continue
    if abs(float(b) - float(a)) > 1e-9:
        continue
    ind.append((ep, float(b)))
steps = [(ind[i][0], ind[i][1] - ind[i - 1][1])
         for i in range(1, len(ind)) if abs(ind[i][1] - ind[i - 1][1]) > 1e-9]


def series(v, f):
    return [(ep, float((d.get(v) or {}).get(f)))
            for ep, d in rows
            if isinstance((d.get(v) or {}).get(f), (int, float))]


def at(sr, t):
    lo, hi, best = 0, len(sr) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if sr[m][0] <= t:
            best = sr[m][1]
            lo = m + 1
        else:
            hi = m - 1
    return best


def vote(field, events, before, min_agree=3):
    """他的口径：5 家各自判方向，≥min_agree 家同向才算这个事件「同向」。"""
    srs = {v: series(v, field) for v in PERPS}
    srs = {v: s for v, s in srs.items() if len(s) >= 50}
    k = n = 0
    for t, sign in events:
        t0, t1 = (t - W, t) if before else (t, t + W)
        agree_n = tot = 0
        for v, s in srs.items():
            v0, v1 = at(s, t0), at(s, t1)
            if v0 is None or v1 is None or abs(v1 - v0) < 1e-12:
                continue
            tot += 1
            if (v1 - v0) * sign > 0:
                agree_n += 1
        if tot < min_agree:
            continue
        n += 1
        if agree_n >= min_agree:
            k += 1
    return k, n, len(srs)


def z(k, n, p0=0.5):
    if not n:
        return float("nan")
    return (k / n - p0) / ((p0 * (1 - p0) / n) ** 0.5)


print()
print("=== 他的口径（%d 家投票、≥3 同向）：真事件 ===" % len(PERPS))
print("| 字段 | 事件前 60s | 事件后 60s | 参与场所数 |")
print("|---|---|---|---|")
real = {}
for f in ("mark", "last", "index"):
    kb, nb, nv = vote(f, steps, True)
    ka, na, _ = vote(f, steps, False)
    if not na:
        continue
    real[f] = (ka, na)
    print("| %s | %.1f%% (%d/%d) z=%+.2f | **%.1f%% (%d/%d) z=%+.2f** | %d |"
          % (f, 100.0 * kb / nb if nb else 0, kb, nb, z(kb, nb),
             100.0 * ka / na, ka, na, z(ka, na), nv))

print()
print("=== 同口径的安慰剂（%d 次重抽）===" % REPS)
random.seed(SEED)
t_lo, t_hi = ind[0][0], ind[-1][0]
signs = [s for _, s in steps]
print("| 字段 | 真事件后 | 安慰剂后 | 净效应 | 对安慰剂基准的 z |")
print("|---|---|---|---|---|")
for f in ("mark", "last", "index"):
    if f not in real:
        continue
    acc = []
    for _ in range(REPS):
        fake = [(random.uniform(t_lo, t_hi), random.choice(signs))
                for _ in range(len(steps))]
        k, n, _ = vote(f, fake, False)
        if n:
            acc.append(k / n)
    ka, na = real[f]
    p0 = sum(acc) / len(acc)
    print("| %s | **%.1f%%** | %.1f%% | %+.1f pp | z=%+.2f |"
          % (f, 100.0 * ka / na, 100.0 * p0, 100.0 * (ka / na - p0),
             z(ka, na, p0)))

print()
print("判读：净效应 = 真事件 − 安慰剂。**用 0.5 当基准会高估**，")
print("      因为安慰剂继承了同一个上行趋势，本身就高于 50%。")
