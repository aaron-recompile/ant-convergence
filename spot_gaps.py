#!/usr/bin/env python3
"""本路的**独立缺口度量**：不看归档、不看 stash，只看并集序列自身的时间连续性。

**为什么需要第三条路径。** 本路此前两次度量损失都依赖某个机制的视野：
  - 「归档有而仓内没有」—— 只能发现归档**已经读到过**的行（7.16 栽在这里）
  - 「stash 里有而三处没有」—— 只能发现**进了 stash** 的损失

另一个会话给出了现成反例：`binance_*.jsonl` 的冲突标记是 git 把两侧都写进文件，
**根本没走 autostash**；而他们的 depth 文件在 rebase 的 **checkout** 阶段被截断，
同样不经 stash，所以 19 个 stash 里一条深度记录都没有 ——
**那段 70 秒的损失是任何「读 stash」的工具都永远找不到的**，不是漏了，
而是它看的地方根本没有。

本脚本因此不依赖任何防护机制的记录，只问一句：
**并集序列自己的时间轴上有没有解释不了的空洞。**

判据（阈值取法沿用另一个会话的做法）：
    间隔 > max(4 × 本时段中位间隔, 4 × 计划采样间隔, 20s)
计划采样间隔取自 `ant_spot.py` 自己的循环常量，不是猜的：
    quote 路：收盘 ±600s 内 2s，常规时段 3s，盘后 10s，其余 60s
    multi 路：15s
已登记的、有解释的空洞（进程换代、重启）单独列出，不计入「无法解释」。
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot_read as R  # noqa: E402

REGULAR_OPEN = 1795098600      # 14:30Z
REGULAR_CLOSE = 1795122000     # 21:00Z
POST_CLOSE = 1795136400        # 01:00Z+1

# 本路已登记、有明确解释的空洞（不计入「无法解释」）—— 每条都注明出处
# **不要手算 epoch。** 初版这里手算的两个值差了整 600 秒，导致已登记的 72s 空洞
# 没被匹配上、被报成「无法解释」。用 calendar.timegm 从 ISO 串算。
import calendar as _cal


def _ep(iso_s):
    return _cal.timegm(time.strptime(iso_s, "%Y-%m-%dT%H:%M:%SZ"))


EXPLAINED = [
    (_ep("2026-11-19T18:29:52Z"), _ep("2026-11-19T18:31:04Z"),
     "单线程版换双线程版，进程换代（7.6 已登记）"),
    (_ep("2026-11-19T21:14:39Z"), _ep("2026-11-19T21:15:02Z"),
     "为改对收盘路径由守护重启（7.9.2 已登记）"),
    # 单线程期（部署 18:24:43Z → 换双线程 18:31:04Z）本身就是宽间隔：
    # 当时实测均值 13.7s、最大 71s（7.x 已登记，正是改双线程的原因）。
    # 该期的计划间隔不是 3s，拿 3s 去判它必然误报。
    (_ep("2026-11-19T18:24:43Z"), _ep("2026-11-19T18:31:04Z"),
     "单线程期，实测均值 13.7s / 最大 71s（7.x 已登记，即改双线程的动因）"),
]


def planned_interval(ts, kind):
    if kind == "multi":
        return 15.0
    if abs(ts - REGULAR_CLOSE) <= 600:
        return 2.0
    if REGULAR_OPEN <= ts < REGULAR_CLOSE:
        return 3.0
    if REGULAR_CLOSE <= ts < POST_CLOSE:
        return 10.0
    return 60.0


def iso(t):
    return time.strftime("%H:%M:%SZ", time.gmtime(t))


def analyse(ts_list, kind, label):
    ts_list = sorted(ts_list)
    if len(ts_list) < 3:
        print("  %s: 不足 3 条，跳过" % label)
        return []
    gaps = [(ts_list[i], ts_list[i + 1], ts_list[i + 1] - ts_list[i])
            for i in range(len(ts_list) - 1)]
    med_all = statistics.median(g[2] for g in gaps)
    flagged = []
    for a, b, d in gaps:
        # 本时段中位：取该点前后各 100 个间隔的中位，避免跨阶段（常规/盘后）误判
        i = ts_list.index(a)
        win = [g[2] for g in gaps[max(0, i - 100):i + 100]]
        med_local = statistics.median(win) if win else med_all
        thr = max(4 * med_local, 4 * planned_interval(a, kind), 20.0)
        if d > thr:
            why = None
            for s0, e0, txt in EXPLAINED:
                if a <= e0 and b >= s0:
                    why = txt
                    break
            flagged.append((a, b, d, thr, why))
    print("  %s: %d 条, 中位间隔 %.1fs, 超阈值空洞 %d 个"
          % (label, len(ts_list), med_all, len(flagged)))
    for a, b, d, thr, why in flagged:
        print("     %s → %s  %.1fs (阈值 %.1fs)  %s"
              % (iso(a), iso(b), d, thr, ("【已登记】" + why) if why else "**无法解释**"))
    return [f for f in flagged if f[4] is None]


print("== 本路独立缺口度量（不看归档、不看 stash，只看并集自身时间连续性）==")
spot, sr = R.load_spot()
bars, br = R.load_bars()
print("并集：spot 记录 %d 条 / bar 分钟 %d 个" % (len(spot), len(bars)))
print()

unexplained = []
for kind in ("quote", "multi"):
    ts = [r["t_epoch"] for r in spot if r.get("kind") == kind and r.get("t_epoch")]
    unexplained += analyse(ts, kind, "spot kind=%s" % kind)

# 无 kind 的最早 27 条，形状与 quote 相同，并入 quote 一起看连续性
ts_all = [r["t_epoch"] for r in spot
          if r.get("t_epoch") and r.get("kind") in (None, "quote", "multi")]
print()
unexplained += analyse(ts_all, "quote", "spot 全部快照（含最早无 kind 的 27 条）")

print()
print("== 分钟线的分钟覆盖（整分钟网格，与采样间隔无关）==")
for src in ("yahoo_1m", "nasdaq_chart"):
    mins = sorted({b["bar_ts"] for b in bars if b["src"] == src})
    if not mins:
        continue
    grid = list(range(mins[0], mins[-1] + 1, 60))
    miss = [t for t in grid if t not in set(mins)]
    print("  %-13s %s → %s  覆盖 %d/%d  缺 %d 个分钟%s"
          % (src, iso(mins[0]), iso(mins[-1]), len(mins), len(grid), len(miss),
             ("：" + ", ".join(iso(t) for t in miss[:8]) +
              (" …" if len(miss) > 8 else "")) if miss else ""))

print()
print("== 结论 ==")
print("无法解释的空洞：**%d 个**" % len(unexplained))
for a, b, d, thr, _ in unexplained:
    print("   %s → %s  %.1fs" % (iso(a), iso(b), d))
if not unexplained:
    print("   → 这是对「136 + 19 条抢救已覆盖本路全部损失」的独立确认，")
    print("     不再依赖「归档读到了什么」或「stash 里有什么」这两个前提。")
sys.exit(0)
