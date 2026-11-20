#!/usr/bin/env python3
"""核实:指示价序列的正确来源是否必须包含 binance_2026-11-19.jsonl。

另一路报:全并集 2,678 条 / 86 个不同取值 / 128 次变动(92 上 36 下)/ 43 回访,
而「ant + 抢救」= 1,523 / 83 / 107 / 25 —— 与本路报的一字不差。
并指出三个**只在 binance 文件里出现过**的价位:105.30 / 107.55 / 110.14。

**这件事是本路的错**:那四样里的「文件」是本路给他的,给的是
`ant_*.jsonl ∪ rescued_ant` —— 漏了 binance 文件。
正是本路这两天一直在登记的那个形状(只在一个地方找),这次犯在本路给出的权威答案里。

注意 binance_2026-11-19.jsonl 里有 3 行 git 冲突标记(行 1/3/8094,已推到 origin/main),
解析时必须跳过 —— 本脚本按 7.26 的办法在 Python 里判,不经 shell。
"""
import calendar
import io
import json
import os
import time

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"

SOURCES = {
    "ant": [os.path.join(D, "ant_2026-11-19.jsonl")],
    "ant+抢救": [os.path.join(D, "ant_2026-11-19.jsonl"),
                os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")],
    "全并集(+binance)": [os.path.join(D, "ant_2026-11-19.jsonl"),
                        os.path.join(RESC, "rescued_ant_2026-11-19.jsonl"),
                        os.path.join(D, "binance_2026-11-19.jsonl")],
}

CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")


def is_marker(ln):
    return any(ln.startswith(x) for x in CONFLICT)


def load(paths):
    """返回 {ts: 指示价},按时刻去重(同一时刻只保留第一个遇到的)。"""
    out, nmark, nbad = {}, 0, 0
    for p in paths:
        if not os.path.exists(p):
            continue
        for ln in io.open(p, errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            if is_marker(ln):
                nmark += 1
                continue
            try:
                d = json.loads(ln)
            except Exception:
                nbad += 1
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
    return out, nmark, nbad


print("| 序列 | 长度 | 不同取值 | 阶梯变动 | 上 | 下 | 回访 | 跳过标记/坏行 |")
print("|---|---|---|---|---|---|---|---|")
built = {}
for name, paths in SOURCES.items():
    m, nmark, nbad = load(paths)
    built[name] = m
    seq = [m[t] for t in sorted(m)]
    ch = [seq[i] - seq[i - 1] for i in range(1, len(seq)) if seq[i] != seq[i - 1]]
    u = sum(1 for x in ch if x > 0)
    dis = len(set(seq))
    print("| %s | %d | **%d** | **%d** | %d | %d | %d | %d/%d |"
          % (name, len(seq), dis, len(ch), u, len(ch) - u,
             len(ch) - dis + 1, nmark, nbad))

print()
print("=== binance 文件独有的时刻与价位 ===")
a2 = built["ant+抢救"]
full = built["全并集(+binance)"]
only_ts = sorted(set(full) - set(a2))
print("  binance 独有时刻数: %d" % len(only_ts))
only_vals = sorted({full[t] for t in only_ts})
a2_vals = set(a2.values())
new_vals = sorted(v for v in only_vals if v not in a2_vals)
print("  这些时刻上出现的价位数: %d" % len(only_vals))
print("  **其中「ant+抢救」从未出现过的价位: %s**" % new_vals)
for v in new_vals:
    ts = [t for t in only_ts if full[t] == v]
    print("     %.2f  出现 %d 次,首次 %sZ" % (v, len(ts), sorted(ts)[0][11:]))

print()
print("=== 冲突标记确认(7.26 的办法,在 Python 里判)===")
bp = os.path.join(D, "binance_2026-11-19.jsonl")
marks = [(i, ln.strip()[:24]) for i, ln in
         enumerate(io.open(bp, errors="replace"), 1) if is_marker(ln.strip())]
print("  binance_2026-11-19.jsonl 里的标记行: %s" % marks)
print("  → 任何重建指示价路径的脚本都必须跳过它们(本脚本已跳过)。")
