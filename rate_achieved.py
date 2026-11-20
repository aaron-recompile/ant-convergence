#!/usr/bin/env python3
"""名义采样间隔 vs 实际达到的采样率 —— 逐窗口实测。

动机:const_audit 的反验发现 2026-11-19 没有任何一分钟达到 20 条,
而收盘 ±600s 窗口里代码设 iv = 2(名义 30 条/分钟)。
固定频率的 sleep(max(0.5, iv - elapsed)) 意味着真实速率被
HTTP 往返时延封顶,不是被 iv 决定 —— 名义采样率不是实现采样率。

本脚本对每一个名义区间分别统计实际达到的速率,并把
「时延封顶」与「进程中断」两种解释分开:
  - 若相邻样本间隔的中位数 ≈ 时延,则是时延封顶
  - 若某几分钟整段缺失,则是中断(重启/autostash)
"""
import collections
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot_read as R   # noqa: E402

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-11-19"
R._set_day(DAY)

# ant_spot.py 的名义间隔(照代码):收盘 ±600s 用 2s,其余按时段
import ant_spot as S        # noqa: E402

RC = S.REGULAR_CLOSE
RO = S.REGULAR_OPEN


def hm(t):
    return time.strftime("%H:%M:%SZ", time.gmtime(t))


spot, _ = R.load_spot()
q = sorted(r["t_epoch"] for r in spot
           if r.get("kind") == "quote" and r.get("t_epoch"))
# 只看本交易日当天的记录 —— 11-19 的文件里混有跨日 bug 写进来的 11-20 记录
lo = RO - 8 * 3600
hi = RC + 5 * 3600
q = [t for t in q if lo <= t <= hi]
print("交易日 %s   本日窗口内 quote %d 条   %s – %s"
      % (DAY, len(q), hm(q[0]) if q else "—", hm(q[-1]) if q else "—"))
if not q:
    sys.exit(0)

WINDOWS = [
    ("收盘 ±600s（名义 iv=2 ⇒ 30/min）", RC - 600, RC + 600, 2),
    ("盘中（收盘窗之外）",                 RO,       RC - 600, None),
    ("盘后（收盘窗之后）",                 RC + 600, hi,       None),
]

print()
print("| 窗口 | quote 条数 | 跨越分钟 | 实际 条/分钟 | 相邻间隔中位数 | 名义 |")
print("|---|---|---|---|---|---|")
for label, a, b, iv in WINDOWS:
    w = [t for t in q if a <= t < b]
    if len(w) < 3:
        print("| %s | %d | — | — | — | %s |"
              % (label, len(w), ("%ds" % iv) if iv else "—"))
        continue
    mins = len({int(t // 60) for t in w})
    gaps = sorted(w[i] - w[i - 1] for i in range(1, len(w)))
    med = gaps[len(gaps) // 2]
    print("| %s | %d | %d | **%.1f** | %.2fs | %s |"
          % (label, len(w), mins, len(w) / mins, med,
             ("%ds ⇒ %.0f/min" % (iv, 60.0 / iv)) if iv else "—"))

print()
print("=== 收盘窗口逐分钟 ===")
cw = [t for t in q if RC - 600 <= t < RC + 600]
if not cw:
    print("   收盘窗口内一条都没有 —— 本场当时没在采,或尚未到收盘。")
else:
    buck = collections.Counter(int(t // 60) * 60 for t in cw)
    # 窗口过滤是 t < RC+600，所以 RC+600 那一分钟按构造不可能有样本 ——
    # 初版把它也列进 allmin，于是报出一个假的「整分钟缺失」。那是本脚本的
    # off-by-one，不是数据缺口。上界取 RC+600-60。
    allmin = sorted(range(int((RC - 600) // 60) * 60,
                          int((RC + 600) // 60) * 60, 60))
    miss = [m for m in allmin if m not in buck]
    for m in allmin:
        n = buck.get(m, 0)
        bar = "█" * min(n, 40)
        mark = "  ← 整分钟缺失" if n == 0 else ""
        print("   %s  %3d %s%s" % (hm(m), n, bar, mark))
    print()
    print("   整分钟缺失 %d 个 / 共 %d 个分钟" % (len(miss), len(allmin)))
    nz = [buck[m] for m in allmin if m in buck]
    if nz:
        print("   非空分钟的 条/分钟:  最小 %d  中位 %d  最大 %d"
              % (min(nz), sorted(nz)[len(nz) // 2], max(nz)))
        print()
        print("   判读:")
        print("     名义 30/min(iv=2)。若非空分钟的最大值远低于 30,")
        print("     且相邻间隔中位数 ≈ 单次抓取的往返时延 ⇒ **时延封顶**,不是代码没设密。")
        print("     若有整分钟缺失 ⇒ 那几分钟是**中断**(重启 / autostash),与速率无关。")
