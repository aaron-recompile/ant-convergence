#!/usr/bin/env python3
"""独立算第三遍「当日最高价及其时刻」,并给出它自己的区间。

43 秒那条是我的错:我假设他的 69 秒锚在 16:48:00Z 而替他减了 26 秒,
但 16:48:26 + 69 = 16:49:35 —— 他本来就锚对了。43 无条件收回。

但有一件两边都还没说的:**最高价那个时刻本身也只能定位到一个采样区间内。**
本路常规时段 iv=3(实现约 5.2s),所以「最高价发生在 16:49:35Z」真正的含义是
「在包含 16:49:35Z 的那个采样间隔内,观测到的最高值是 114.853」。

于是「首笔到最高价」这段时长是**两端各带区间**:
  起点 ∈ (16:48:21Z, 16:48:26Z]      ← traded 翻转区间
  终点 ∈ (上一次采样, 16:49:35Z]      ← 最高价观测区间
⇒ 时长的下界 = 终点下界 − 起点上界,上界 = 终点上界 − 起点下界
"""
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot_read as R   # noqa: E402

R._set_day("2026-11-19")

FIRST_LO = "2026-11-19T16:48:21Z"
FIRST_HI = "2026-11-19T16:48:26Z"
import calendar  # noqa: E402


def ep(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def hm(t):
    return time.strftime("%H:%M:%SZ", time.gmtime(t))


spot, _ = R.load_spot()
bars, _ = R.load_bars()

# ── ① 从 spot 快照序列找最高观测 ───────────────────────────────
qs = [(r["t_epoch"], (r.get("best") or {}).get("price_usd"))
      for r in spot
      if r.get("kind") == "quote" and r.get("t_epoch")
      and (r.get("best") or {}).get("price_usd") is not None]
qs.sort()
# 只看常规时段当天
lo, hi = ep("2026-11-19T14:30:00Z"), ep("2026-11-19T21:00:01Z")
qs = [(t, float(p)) for t, p in qs if lo <= t <= hi]
print("本路 spot 常规时段带价观测: %d 条  %s – %s"
      % (len(qs), hm(qs[0][0]) if qs else "—", hm(qs[-1][0]) if qs else "—"))

if qs:
    mx = max(p for _, p in qs)
    at = [t for t, p in qs if p == mx]
    print("  **spot 侧最高观测 = %.4f**，出现 %d 次，首次 %s"
          % (mx, len(at), hm(at[0])))
    i = [t for t, _ in qs].index(at[0])
    prev = qs[i - 1][0] if i > 0 else None
    if prev:
        print("  其前一次采样 %s ⇒ 最高价发生在 (%s, %s]，宽 %d 秒"
              % (hm(prev), hm(prev), hm(at[0]), at[0] - prev))

# ── ② 从 minbars 找最高（分钟级，只能定位到分钟）────────────────
bh = [(b.get("bar_ts"), b.get("high_usd"), b.get("src"))
      for b in bars if b.get("high_usd") is not None]
if bh:
    m = max(x[1] for x in bh)
    print()
    print("  minbars 侧最高 high_usd = %.4f" % m)
    for ts, v, src in sorted(bh):
        if v == m:
            print("     src=%s  bar_ts=%s（分钟标签，非事件时刻 —— 7.44）"
                  % (src, time.strftime("%H:%MZ", time.gmtime(ts)) if isinstance(ts, (int, float)) else ts))

# ── ③ 两端都带区间的时长 ──────────────────────────────────────
print()
print("=== 「首笔 → 最高价」的时长：两端各带区间 ===")
PEER_HIGH_AT = ep("2026-11-19T16:49:35Z")       # 他报的最高价时刻
f_lo, f_hi = ep(FIRST_LO), ep(FIRST_HI)
print("  起点区间（traded 翻转）: (%s, %s]" % (hm(f_lo), hm(f_hi)))
print("  他报的最高价时刻: %s" % hm(PEER_HIGH_AT))
print("  → 距上界 %d 秒（= 他报的 69）" % (PEER_HIGH_AT - f_hi))
print("  → 距下界 %d 秒（= 他报的 74）" % (PEER_HIGH_AT - f_lo))
print("  **两个都对；43 是我的错（我误以为他的 69 锚在 16:48:00Z，替他减了 26 秒）。**")

if qs:
    i = [t for t, _ in qs].index(at[0])
    prev = qs[i - 1][0] if i > 0 else at[0]
    print()
    print("  若把最高价的采样区间也算进去（本路 spot 侧）:")
    print("    终点区间: (%s, %s]" % (hm(prev), hm(at[0])))
    print("    时长下界 = 终点下界 − 起点上界 = %d 秒" % (prev - f_hi))
    print("    时长上界 = 终点上界 − 起点下界 = %d 秒" % (at[0] - f_lo))
    print("  ⇒ **这段时长本身是个区间，不是一个数。**")
    print("    报「69 秒」隐含了「最高价时刻是精确的」—— 而它和首笔一样，")
    print("    只能定位到一个采样间隔内。两端都报，才是同一个标准。")
