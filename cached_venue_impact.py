#!/usr/bin/env python3
"""另一路实测:gate / bitget / kucoin 走 `_throttled` 缓存,命中时返回上一次取数的值
(实测已见早 6.8–7.1 秒,按 15s 放宽);binance_sent 按 60s;
而 `spot_ANT_nasdaq` **不走**缓存,每轮新取。

**后果打到本路自己的东西上:** 本路 7.40 的阈值表与基差符号序列都把
bitget / gate / kucoin 当成同时刻观测用了。

本脚本两件:
  ① 查本路哪些已提交脚本引用了缓存源
  ② 把基差符号序列按「只用非缓存源」重算,看结论动不动

非缓存的永续只有 hl_xyz_ANT 与 kraken_PF_ANTXUSD 两家
(binance_ANTUSDT 另有问题:另一路实测 ant_*.jsonl 里它 14,978 条全是
 via=coingecko,本就被 R5 排除)。
"""
import collections
import io
import json
import os
import statistics
import subprocess

HERE = os.path.expanduser("~/ant-convergence")
D = os.path.join(HERE, "data")
RESC = os.path.expanduser("~/ant-rescue")

CACHED = ["bitget_ANTUSDT", "gate_ANT_USDT", "kucoin_ANTUSDTM", "binance_sent"]
CLEAN = ["hl_xyz_ANT", "kraken_PF_ANTXUSD"]

print("=== ① 本路哪些脚本引用了缓存源 ===")
hits = collections.defaultdict(list)
for f in sorted(os.listdir(HERE)):
    if not f.endswith(".py"):
        continue
    try:
        txt = io.open(os.path.join(HERE, f), errors="replace").read()
    except Exception:
        continue
    for v in CACHED:
        if v in txt:
            hits[f].append(v)
if not hits:
    print("  无")
for f, vs in sorted(hits.items()):
    print("  %-30s %s" % (f, ", ".join(vs)))

print()
print("=== ② 基差符号序列:全部五家 vs 只用非缓存两家 ===")
P = os.path.join(D, "ant_2026-11-19.jsonl")
R = os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
WIN_LO, WIN_HI = "2026-11-19T15:40:00", "2026-11-19T16:30:00"
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

rows, seen = [], set()
for path in (P, R):
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
        if not (LO <= ts <= HI):
            continue
        rows.append((ts, d))
rows.sort(key=lambda x: x[0])


def basis(venues, min_n):
    out = []
    for ts, d in rows:
        sp = d.get("spot_ANT_nasdaq") or {}
        b, a = sp.get("bid"), sp.get("ask")
        if b is None or a is None or sp.get("traded"):
            continue
        if abs(float(b) - float(a)) > 1e-9:
            continue
        marks = [float((d.get(v) or {}).get("mark"))
                 for v in venues
                 if isinstance((d.get(v) or {}).get("mark"), (int, float))]
        if len(marks) < min_n:
            continue
        pm = statistics.median(marks)
        out.append((ts, float(b), pm, pm - float(b)))
    return out


ALL5 = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
        "gate_ANT_USDT", "kucoin_ANTUSDTM"]
CASES = [("全部五家（≥3）", ALL5, 3),
         ("**只用非缓存两家（≥2）**", CLEAN, 2),
         ("只用非缓存两家（≥1）", CLEAN, 1)]

print("| 口径 | 全窗口配对 | P−I 为正 | 占比 | 15:40–16:30Z 配对 | 该窗口为正 | 最长连负 | 最后由正转负 |")
print("|---|---|---|---|---|---|---|---|")
res = {}
for label, vs, mn in CASES:
    pr = basis(vs, mn)
    res[label] = pr
    if not pr:
        print("| %s | 0 | — | — | — | — | — | — |" % label)
        continue
    pos = sum(1 for x in pr if x[3] > 0)
    win = [x for x in pr if WIN_LO <= x[0] <= WIN_HI]
    wpos = sum(1 for x in win if x[3] > 0)
    best = cur = 0
    for _, _, _, dl in pr:
        cur = cur + 1 if dl < 0 else 0
        best = max(best, cur)
    flip = None
    for i in range(1, len(pr)):
        if pr[i - 1][3] > 0 and pr[i][3] < 0:
            flip = pr[i][0]
    print("| %s | %d | %d | %.2f%% | %d | %d | %d | %s |"
          % (label, len(pr), pos, 100.0 * pos / len(pr), len(win), wpos,
             best, (flip[11:] + "Z") if flip else "无"))

print()
print("=== 判读 ===")
a = res.get("全部五家（≥3）") or []
b = res.get("**只用非缓存两家（≥2）**") or []
if a and b:
    print("  配对数 %d → %d（%+d）" % (len(a), len(b), len(b) - len(a)))
    med_a = statistics.median([x[3] for x in a])
    med_b = statistics.median([x[3] for x in b])
    print("  P−I 中位 %.4f → %.4f（%+.4f）" % (med_a, med_b, med_b - med_a))
    sa = sum(1 for x in a if x[3] > 0) / len(a)
    sb = sum(1 for x in b if x[3] > 0) / len(b)
    print("  为正占比 %.2f%% → %.2f%%" % (100 * sa, 100 * sb))
    print()
    print("  若两者定性一致（几乎恒为负）⇒ 缓存不改变结论，但口径要写明；")
    print("  若定性不同 ⇒ 原结论依赖三家可能陈旧 15 秒的报价，必须改写。")
