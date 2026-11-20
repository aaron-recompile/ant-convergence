#!/usr/bin/env python3
"""找出哪种「阶梯变动」定义给出 127 次事件（他的数），以定位那 5–7pp 的差额。

背景：我 107 次（上调 81 / 下调 26），他 127 次（92 / 36）。
他已排除端点约定，我已排除估计量与并集。**剩下两边都知道存在的唯一差异就是事件定义。**

算术上它就够解释差额：我 107 次中 mark 同向 79（73.8%）；
若他 127 次同向 88（69.3%），则**多出的 20 次里只有 9 次同向（45%）** ——
正是「无信息事件被掺进来」的样子。

比寄时刻列表更省事：直接把几种合理定义都跑一遍，看哪个落在 127。
"""
import calendar
import io
import json
import os
import time

P = os.path.expanduser("~/ant-convergence/data/ant_2026-11-19.jsonl")
R = os.path.expanduser("~/ant-rescue/rescued_ant_2026-11-19.jsonl")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"

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


def build(require_eq, require_not_traded, use_bid_only, dedupe_same_sec):
    """按不同定义取指示价序列。"""
    out = []
    for ep, d in rows:
        sp = d.get("spot_ANT_nasdaq") or {}
        b, a = sp.get("bid"), sp.get("ask")
        if b is None:
            continue
        if not use_bid_only and a is None:
            continue
        if require_not_traded and sp.get("traded"):
            continue
        if require_eq and (a is None or abs(float(b) - float(a)) > 1e-9):
            continue
        out.append((ep, float(b)))
    if dedupe_same_sec:
        seen_t, ded = set(), []
        for t, v in out:
            if t in seen_t:
                continue
            seen_t.add(t)
            ded.append((t, v))
        out = ded
    return out


def steps_of(seq, tol=0.0):
    return [(seq[i][0], seq[i][1] - seq[i - 1][1])
            for i in range(1, len(seq))
            if abs(seq[i][1] - seq[i - 1][1]) > tol]


VARIANTS = [
    ("本路（bid==ask 且未成交；相邻不同即一次）", dict(require_eq=True, require_not_traded=True,
                                                 use_bid_only=False, dedupe_same_sec=False), 0.0),
    ("去掉 traded 过滤", dict(require_eq=True, require_not_traded=False,
                            use_bid_only=False, dedupe_same_sec=False), 0.0),
    ("去掉 bid==ask 过滤（只要有 bid 和 ask）", dict(require_eq=False, require_not_traded=True,
                                               use_bid_only=False, dedupe_same_sec=False), 0.0),
    ("只要有 bid（忽略 ask 是否存在）", dict(require_eq=False, require_not_traded=True,
                                      use_bid_only=True, dedupe_same_sec=False), 0.0),
    ("两个过滤都去掉", dict(require_eq=False, require_not_traded=False,
                       use_bid_only=True, dedupe_same_sec=False), 0.0),
    ("本路 + 同秒去重", dict(require_eq=True, require_not_traded=True,
                         use_bid_only=False, dedupe_same_sec=True), 0.0),
]

print("| 定义 | 序列长度 | 阶梯变动 | 上调 | 下调 |")
print("|---|---|---|---|---|")
for label, kw, tol in VARIANTS:
    seq = build(**kw)
    st = steps_of(seq, tol)
    u = sum(1 for _, s in st if s > 0)
    print("| %s | %d | **%d** | %d | %d |"
          % (label, len(seq), len(st), u, len(st) - u))

print()
print("=== 容差扫描（本路定义，改变「算不算一次变动」的阈值）===")
seq = build(require_eq=True, require_not_traded=True,
            use_bid_only=False, dedupe_same_sec=False)
for tol in (0.0, 0.004, 0.009, 0.019, 0.049):
    st = steps_of(seq, tol)
    u = sum(1 for _, s in st if s > 0)
    print("  tol > $%.3f  →  %3d 次（上调 %d / 下调 %d）" % (tol, len(st), u, len(st) - u))

print()
print("=== 他的 127（92/36）落在哪 ===")
print("  若上表某一行给出 127 且 92/36，差额就是事件定义，账可以结清。")
print("  若没有一行命中，则事件定义也不是原因，差额来源仍未定位 ——")
print("  那时才值得寄时刻列表。")
