#!/usr/bin/env python3
"""官方收盘价落在连续竞价价差之外吗 —— 两天各查一遍。

11-20 实测:88.91 在收盘前后每一个采样盘口里都在卖价之上
(21:00:00Z ask=88.60，之后 88.65)。连续竞价不会在卖价之上成交，
收盘撮合可以(它清 on-close 不平衡)。

若 11-19 的 97.17 也如此，这条就不是一天的巧合，
7.9 那条 caveat 可以从「公开端点分不开」升级成「有盘口证据指向撮合印」。

强度:**证据不是证明** —— 本路分辨率 2.6s(11-20)/ 4.18s(11-19)，
最后几秒价格可以动，所以不能断言「最后一笔」。
能断言的是「本路采样到的每一个盘口把官方收盘价排在哪一侧」。
"""
import io
import json
import os
import sys

D = os.path.expanduser("~/ant-convergence/data")
A = os.path.expanduser("~/ant-spot-archive")

CASES = [
    ("2026-11-19", 97.17, "20:58:00", "21:02:00"),
    ("2026-11-20", 88.91, "20:58:00", "21:02:00"),
]


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


for day, close, lo, hi in CASES:
    print("══════════ %s  官方收盘价 $%s ══════════" % (day, close))
    rows = load(day)
    win = []
    for d in rows:
        ts = str(d.get("ts") or "")[:19]
        if not ts.startswith(day):
            continue
        if not (day + "T" + lo <= ts <= day + "T" + hi):
            continue
        i = d.get("nasdaq_info") or {}
        b, a = i.get("bid_usd"), i.get("ask_usd")
        if b is None or a is None:
            continue
        win.append((ts, float(b), float(a), i.get("price_usd"), i.get("state_src")))
    win.sort(key=lambda x: x[0])
    if not win:
        print("  窗口内没有带盘口的记录 —— 本路当时没采到 bid/ask，无法判。")
        print()
        continue

    above_ask = sum(1 for _, b, a, _, _ in win if close > a)
    inside = sum(1 for _, b, a, _, _ in win if b <= close <= a)
    below_bid = sum(1 for _, b, a, _, _ in win if close < b)
    print("  窗口 %s–%s，带盘口的采样 %d 条" % (lo, hi, len(win)))
    print("  | 官方收盘价相对盘口 | 条数 | 占比 |")
    print("  |---|---|---|")
    for label, n in (("**高于卖价**", above_ask), ("在价差之内", inside),
                     ("低于买价", below_bid)):
        print("  | %s | %d | %.1f%% |" % (label, n, 100.0 * n / len(win)))
    asks = [a for _, _, a, _, _ in win]
    print("  窗口内 ask 的范围: %.4f – %.4f（最大 ask 仍比收盘价低 %+.4f）"
          % (min(asks), max(asks), max(asks) - close))
    # 最接近收盘那一刻的几条
    print("  最接近 21:00:00Z 的 5 条:")
    ref = day + "T21:00:00"
    near = sorted(win, key=lambda x: abs((x[0] > ref) - 0.5) * 0 + abs(
        int(x[0][11:13]) * 3600 + int(x[0][14:16]) * 60 + int(x[0][17:19])
        - (21 * 3600)))[:5]
    for ts, b, a, p, st in sorted(near, key=lambda x: x[0]):
        rel = "高于卖价" if close > a else ("价差内" if b <= close <= a else "低于买价")
        print("     %sZ  price=%-9s bid/ask=%s/%s  state=%-12s ⇒ %s"
              % (ts[11:], p, b, a, st, rel))
    print()

print("=== 判读 ===")
print("  两天都「高于卖价」占绝大多数 ⇒ 官方收盘价系统性地落在连续竞价价差之外，")
print("  这更像收盘撮合印而不是最后一笔连续成交。**证据，非证明。**")
print("  若某一天大量落在价差之内 ⇒ 那一天的收盘价与连续竞价一致，本条不成立。")
