#!/usr/bin/env python3
"""两件事:
① 独立复核他那个判别性检验(按指示价修订方向拆开) —— 确认撤回和确认发现一样重要。
② 回答他的核查请求:事件前偏高是**方向不平衡**造成的,还是**单场所口径**造成的?

他的说法:窗口内 72% 是上调,而上调组的事件前同向就有 60.4%;
所以「事件前偏高」里有一部分本来就是方向不平衡,不是单场所口径。
**若成立,我 7.35.6 已撤回的那条还要再弱化一层 —— 连「口径解释」这个归因也是错的。**

判别逻辑(他的,我认为对):
  真跟随   预测:上调后永续涨、下调后永续跌  —— 两组都应显著
  共同趋势 预测:两组都倾向跟随整体上行     —— 只有上调组显著
  **所以识别力全在下调组。**

只读。
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
import time

P = os.path.expanduser("~/ant-convergence/data/ant_2026-11-19.jsonl")
R = os.path.expanduser("~/ant-rescue/rescued_ant_2026-11-19.jsonl")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
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
up = [(t, s) for t, s in steps if s > 0]
dn = [(t, s) for t, s in steps if s < 0]
print("阶梯变动 %d 次：上调 %d / 下调 %d（上调占 %.1f%%）"
      % (len(steps), len(up), len(dn), 100.0 * len(up) / len(steps)))
print("  他报 n=127（上调 92 / 下调 36）—— 我是 %d（%d / %d），"
      "**事件计数本身两边不同,须一并说明**" % (len(steps), len(up), len(dn)))


def series(v, f):
    return [(ep, float((d.get(v) or {}).get(f)))
            for ep, d in rows if isinstance((d.get(v) or {}).get(f), (int, float))]


SR = {(v, f): series(v, f) for v in PERPS
      for f in ("mark", "last", "index", "mid")}
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


def rate(field, events, before, W=60, min_n=3):
    """方向投票:≥3 家同向。"""
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


# ── 实测无条件基准:窗口内 60 秒前向变动的涨/跌概率 ────────────────
def baseline(field, W=60):
    srs = [s for (v, f), s in SR.items() if f == field]
    up_n = dn_n = tot = 0
    ts = [ep for ep, _ in rows]
    for t in ts:
        ag_up = ag_dn = cnt = 0
        for s in srs:
            v0, v1 = at(s, t), at(s, t + W)
            if v0 is None or v1 is None or abs(v1 - v0) < 1e-12:
                continue
            cnt += 1
            if v1 > v0:
                ag_up += 1
            else:
                ag_dn += 1
        if cnt < 3:
            continue
        tot += 1
        if ag_up >= 3:
            up_n += 1
        elif ag_dn >= 3:
            dn_n += 1
    return (up_n / tot if tot else float("nan"),
            dn_n / tot if tot else float("nan"), tot)


def z(k, n, p0):
    return float("nan") if not n or not (0 < p0 < 1) else \
        (k / n - p0) / ((p0 * (1 - p0) / n) ** 0.5)


print()
print("=== ① 判别性检验:按方向拆开（事件后 60s，方向投票）===")
print("| 字段 | 事件集 | n | 事件后同向 | 实测 p0 | z |")
print("|---|---|---|---|---|---|")
for f in ("mark", "last", "index"):
    pu, pd, tot = baseline(f)
    for label, ev, p0 in (("全部", steps, (len(up) * pu + len(dn) * pd) / len(steps)),
                          ("上调", up, pu), ("下调（全部识别力）", dn, pd)):
        k, n = rate(f, ev, False)
        if not n:
            continue
        print("| %s | %s | %d | %.1f%% (%d/%d) | %.3f | %+.2f |"
              % (f, label, n, 100.0 * k / n, k, n, p0, z(k, n, p0)))
    print("| %s | *（实测基准 P(涨)=%.3f P(跌)=%.3f，n=%d）* | | | | |"
          % (f, pu, pd, tot))

print()
print("=== ② 他的核查请求:事件前偏高 —— 方向不平衡 还是 单场所口径？===")
print("| 场所·字段 | 全部事件前 | 上调事件前 | 下调事件前 |")
print("|---|---|---|---|")
for (v, f), s in sorted(SR.items()):
    out = []
    for ev in (steps, up, dn):
        k = n = 0
        for t, sign in ev:
            v0, v1 = at(s, t - 60), at(s, t)
            if v0 is None or v1 is None or abs(v1 - v0) < 1e-12:
                continue
            n += 1
            if (v1 - v0) * sign > 0:
                k += 1
        out.append("%.1f%% (%d/%d)" % (100.0 * k / n, k, n) if n else "—")
    print("| %s·%s | %s | %s | %s |" % (v.split("_")[0], f, out[0], out[1], out[2]))

print()
print("判读②：若「上调事件前」普遍高而「下调事件前」普遍低，")
print("        则事件前偏高来自**方向不平衡**（上调占多数 × 整体上行），")
print("        而不是单场所口径 —— 那我 7.35.6 的归因还要再弱化一层。")
