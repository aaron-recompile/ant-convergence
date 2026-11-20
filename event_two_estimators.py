#!/usr/bin/env python3
"""同一份数据、同一批事件、同一个安慰剂种子，同时跑两种估计量。

分歧：我报净效应 +22…+25pp（安慰剂 44–52%），他报 +17pp（安慰剂 53–55%）。
他猜是估计量差：我用**方向投票**（≥3 家同向），他用**横截面中位数变动**。
**与其互贴规则，不如一次把两种都跑出来** —— 若切换估计量后我的数落到他的数上，
分歧就是估计量；否则是别的东西（场所清单/字段/子样本）。

顺带核一条：他的逐场所清单第一项 57.5% 正是我的 HL `mid`（我也是 57.5%）；
而我报 z=+2.03 的是 HL **mark**，他说「HL 用 mid、其余用 last」——
**他没有算过 HL mark**。若如此，那条「分歧」根本不是分歧。

只读。
"""
import calendar
import io
import json
import os
import random
import statistics
import time

P = os.path.expanduser("~/ant-convergence/data/ant_2026-11-19.jsonl")
R = os.path.expanduser("~/ant-rescue/rescued_ant_2026-11-19.jsonl")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
W, SEED, REPS = 60, 20261119, 200
PERPS = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
         "gate_ANT_USDT", "kucoin_ANTUSDTM"]

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
            for ep, d in rows if isinstance((d.get(v) or {}).get(f), (int, float))]


SR = {(v, f): series(v, f) for v in PERPS for f in ("mark", "last", "index", "mid")}
SR = {k: s for k, s in SR.items() if len(s) >= 50}


def at(s, t):
    lo, hi, best = 0, len(s) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if s[m][0] <= t:
            best = s[m][1]
            lo = m + 1
        else:
            hi = m - 1
    return best


def est_vote(field, events, before, min_n=3):
    """我的估计量：每家各判方向，≥min_n 家同向 ⇒ 该事件算同向。"""
    srs = [s for (v, f), s in SR.items() if f == field]
    k = n = 0
    for t, sign in events:
        t0, t1 = (t - W, t) if before else (t, t + W)
        ag = tot = 0
        for s in srs:
            v0, v1 = at(s, t0), at(s, t1)
            if v0 is None or v1 is None or abs(v1 - v0) < 1e-12:
                continue
            tot += 1
            if (v1 - v0) * sign > 0:
                ag += 1
        if tot < min_n:
            continue
        n += 1
        if ag >= min_n:
            k += 1
    return k, n


def est_median(field, events, before, min_n=3):
    """他的估计量：取各家变动的横截面中位数，看它与该步同向。"""
    srs = [s for (v, f), s in SR.items() if f == field]
    k = n = 0
    for t, sign in events:
        t0, t1 = (t - W, t) if before else (t, t + W)
        ds = []
        for s in srs:
            v0, v1 = at(s, t0), at(s, t1)
            if v0 is None or v1 is None:
                continue
            ds.append(v1 - v0)
        if len(ds) < min_n:
            continue
        med = statistics.median(ds)
        if abs(med) < 1e-12:
            continue
        n += 1
        if med * sign > 0:
            k += 1
    return k, n


def z(k, n, p0=0.5):
    return float("nan") if not n else (k / n - p0) / ((p0 * (1 - p0) / n) ** 0.5)


def placebo(est, field):
    random.seed(SEED)
    t_lo, t_hi = ind[0][0], ind[-1][0]
    signs = [s for _, s in steps]
    acc = []
    for _ in range(REPS):
        fake = [(random.uniform(t_lo, t_hi), random.choice(signs))
                for _ in range(len(steps))]
        k, n = est(field, fake, False)
        if n:
            acc.append(k / n)
    return (sum(acc) / len(acc), statistics.pstdev(acc)) if acc else (float("nan"),) * 2


print("事件数 %d（阶梯变动）" % len(steps))
print()
print("=== 两种估计量，同一份数据、同一批事件、同一个安慰剂种子 ===")
print("| 估计量 | 字段 | 事件前 | 事件后 | 安慰剂 | 净效应 | 对安慰剂 z |")
print("|---|---|---|---|---|---|---|")
for name, est in (("方向投票（我）", est_vote), ("中位数变动（他）", est_median)):
    for f in ("mark", "last", "index"):
        kb, nb = est(f, steps, True)
        ka, na = est(f, steps, False)
        if not na:
            continue
        p0, sd = placebo(est, f)
        print("| %s | %s | %.1f%% (%d/%d) | **%.1f%% (%d/%d)** | %.1f%% ±%.1f | **%+.1f pp** | %+.2f |"
              % (name, f, 100.0 * kb / nb, kb, nb, 100.0 * ka / na, ka, na,
                 100.0 * p0, 100.0 * sd, 100.0 * (ka / na - p0), z(ka, na, p0)))

print()
print("=== 逐场所·事件前同向率（核那条「单场所伪效应」的分歧）===")
print("| 场所 | 字段 | 事件前 | z(vs 0.5) |")
print("|---|---|---|---|")
for v in PERPS:
    for f in ("mark", "mid", "last"):
        if (v, f) not in SR:
            continue
        s = SR[(v, f)]
        k = n = 0
        for t, sign in steps:
            v0, v1 = at(s, t - W), at(s, t)
            if v0 is None or v1 is None or abs(v1 - v0) < 1e-12:
                continue
            n += 1
            if (v1 - v0) * sign > 0:
                k += 1
        if n:
            print("| %-20s | %-5s | %.1f%% (%d/%d) | %+.2f |"
                  % (v, f, 100.0 * k / n, k, n, z(k, n)))
print()
print("判读：他的逐场所清单是「HL 用 mid、其余用 last」。")
print("      若上表 HL mid 与他第一项相同、而 HL mark 明显更高，")
print("      则我报的 z=+2.03 是 HL **mark**，他根本没算过那一项 —— 不是分歧。")
