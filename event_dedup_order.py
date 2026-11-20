#!/usr/bin/env python3
"""核实遍历顺序对并集计数的影响,并列出冲突时刻。

本路 7.39 报了全并集 **2,678 / 86 / 128**,**没带敏感性** ——
而本路自己在 7.39.5 写过「保留先遇到的,取决于文件遍历顺序,本身是个未写下来的前提」。
另一路按这条查了自己的代码,实测 ant 优先 86/128、binance 优先 85/127。

**所以本路报的 86/128 是「ant 优先」这一侧的数,而我没说明那是哪一侧。**
本脚本两个顺序都跑,并列出冲突时刻 —— 把那个前提变成一个可报的敏感性区间。
"""
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

ANT = os.path.join(D, "ant_2026-11-19.jsonl")
BNC = os.path.join(D, "binance_2026-11-19.jsonl")
RES = os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")


def read_one(p):
    """返回 {ts: 指示价} —— 单个文件内按时刻保留先遇到的。"""
    out = {}
    if not os.path.exists(p):
        return out
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or any(ln.startswith(x) for x in CONFLICT):
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if not (LO <= ts <= HI):
            continue
        sp = d.get("spot_ANT_nasdaq") or {}
        b, a = sp.get("bid"), sp.get("ask")
        if b is None or a is None or sp.get("traded"):
            continue
        if abs(float(b) - float(a)) > 1e-9:
            continue
        out.setdefault(ts, float(b))
    return out


per = {"ant": read_one(ANT), "binance": read_one(BNC), "rescued": read_one(RES)}


def merge(order):
    m = {}
    for name in order:
        for ts, v in per[name].items():
            m.setdefault(ts, v)
    return m


def stats(m):
    seq = [m[t] for t in sorted(m)]
    ch = [seq[i] - seq[i - 1] for i in range(1, len(seq)) if seq[i] != seq[i - 1]]
    u = sum(1 for x in ch if x > 0)
    return len(seq), len(set(seq)), len(ch), u, len(ch) - u


print("| 遍历顺序 | 长度 | 档位 | 阶梯变动 | 上 | 下 |")
print("|---|---|---|---|---|---|")
for label, order in (("**ant 优先（本路 7.39 报的那一侧）**", ["ant", "rescued", "binance"]),
                     ("binance 优先", ["binance", "ant", "rescued"]),
                     ("rescued 优先", ["rescued", "ant", "binance"])):
    n, dis, nch, u, dn = stats(merge(order))
    print("| %s | %d | **%d** | **%d** | %d | %d |" % (label, n, dis, nch, u, dn))

print()
print("=== 两文件取值冲突的时刻（同一秒、同一零售接口、两个采集器各拿一个 tick）===")
both = sorted(set(per["ant"]) & set(per["binance"]))
conf = [(t, per["ant"][t], per["binance"][t]) for t in both
        if abs(per["ant"][t] - per["binance"][t]) > 1e-9]
print("  共同时刻 %d 个，其中取值冲突 **%d** 个：" % (len(both), len(conf)))
for t, a, b in conf:
    print("     %sZ   ant %.4f / bnc %.4f   差 %+.4f" % (t[11:], a, b, b - a))

print()
print("=== 冲突对档位的影响 ===")
va, vb = {x[1] for x in conf}, {x[2] for x in conf}
only_ant = sorted(v for v in va if v not in set(per["binance"].values()))
only_bnc = sorted(v for v in vb if v not in set(per["ant"].values()))
print("  只在 ant 一侧出现过的冲突取值: %s" % only_ant)
print("  只在 bnc 一侧出现过的冲突取值: %s" % only_bnc)
print()
print("  → 若某个冲突取值在另一侧从未出现，保留哪一侧就决定该档位在不在并集里。")
print("    这就是 86 vs 85 的机制。**两侧都不是错的**，所以必须报区间 + 保留规则。")
