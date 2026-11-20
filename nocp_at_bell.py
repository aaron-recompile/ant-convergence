#!/usr/bin/env python3
"""只看贴着收盘钟那几笔 —— 那是唯一有判别力的部分。

±2 分钟窗口的统计没有判别力:任何固定价格拿去比一个移动市场在 4 分钟里的
各个价差,都会落在大多数之外(实测 11-19 高于卖价 68.6% / 低于买价 28.6%,
11-20 72.1% / 27.9% —— 分裂在两侧,正说明它只反映价格在动)。

有判别力的是:**收盘钟前后紧邻的那一两个盘口,官方收盘价落在哪一侧。**
"""
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
A = os.path.expanduser("~/ant-spot-archive")
CASES = [("2026-11-19", 97.17), ("2026-11-20", 88.91)]


def load(day):
    seen, rows = set(), []
    for p in (os.path.join(D, "spot_%s.jsonl" % day),
              os.path.join(A, "spot_%s.jsonl" % day),
              os.path.join(A, "recovered_from_autostash_%s.jsonl" % day),
              os.path.join(A, "recovered_from_stash_pass2_%s.jsonl" % day)):
        if not os.path.exists(p):
            continue
        for ln in io.open(p, errors="replace"):
            ln = ln.strip()
            if not ln or ln in seen:
                continue
            seen.add(ln)
            try:
                d = json.loads(ln)
            except Exception:
                continue
            rows.append(d)
    return rows


for day, close in CASES:
    print("══════════ %s  官方收盘价 $%s ══════════" % (day, close))
    bell = day + "T21:00:00"
    recs = []
    for d in load(day):
        ts = str(d.get("ts") or "")[:19]
        if not ts.startswith(day):
            continue
        i = d.get("nasdaq_info") or {}
        b, a = i.get("bid_usd"), i.get("ask_usd")
        if b is None or a is None:
            continue
        recs.append((ts, float(b), float(a), i.get("price_usd"), i.get("state_src")))
    recs.sort(key=lambda x: x[0])
    before = [r for r in recs if r[0] < bell]
    after = [r for r in recs if r[0] >= bell]
    print("  钟前最后 3 个带盘口的采样 / 钟后最早 3 个:")
    print("  | 相对 | 时刻 | price | bid | ask | state | 收盘价 − ask |")
    print("  |---|---|---|---|---|---|---|")
    for tag, group in (("钟前", before[-3:]), ("钟后", after[:3])):
        for ts, b, a, p, st in group:
            print("  | %s | %sZ | %s | %s | %s | %s | **%+.4f** |"
                  % (tag, ts[11:], p, b, a, st, close - a))
    if before:
        ts, b, a, p, st = before[-1]
        print("  → 钟前最后一个盘口 %s/%s（%sZ，间隔 %s 秒内）"
              % (b, a, ts[11:], "?"))
        print("    **官方收盘价 %s − ask %s = %+.4f**" % (close, a, close - a))
        print("    %s" % ("在卖价之上 ⇒ 连续竞价不会这样成交"
                          if close > a else
                          ("在价差之内 ⇒ 与连续竞价一致，本条不成立"
                           if b <= close <= a else "在买价之下")))
    print()

print("=== 两天合起来的判读 ===")
print("  若两天「钟前最后一个盘口」都把官方收盘价排在卖价之上,")
print("  且差额量级相当,则这不是一天的巧合 —— 是收盘撮合价的特征。")
print("  **仍是证据不是证明**:本路分辨率 2.6s(11-20)/4.18s(11-19),")
print("  最后几秒价格可以动;且没有任何端点给出撮合标记。")
