"""审计本路代码里所有手算的时间常量 —— 与库函数算出的值对账。

动机：spot_gaps.py 初版手算 epoch 差了整 600 秒（7.17.1）。
另一个会话把它推广成「凡能从源头推导的，都不要手抄」。
`ant_spot.py` 里 REGULAR_OPEN / REGULAR_CLOSE / POST_CLOSE / ET_TO_UTC_OFFSET
都是硬编码的，必须逐个对账 —— 若 REGULAR_CLOSE 偏了，
收盘 ±600s 的密集采样窗口就对错了中心。
"""
import calendar
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot as S      # noqa: E402  只读常量，不启动任何循环
import ant_spot_read as R  # noqa: E402


def ep(iso_s):
    return calendar.timegm(time.strptime(iso_s, "%Y-%m-%dT%H:%M:%SZ"))


def hm(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


# 2026-11-19 是 EST（DST 于 11/1 结束），ET = UTC-5
TRUTH = {
    "REGULAR_OPEN":  ("2026-11-19T14:30:00Z", "09:30 ET 开市"),
    "REGULAR_CLOSE": ("2026-11-19T21:00:00Z", "16:00 ET 收盘"),
    "POST_CLOSE":    ("2026-11-19T01:00:00Z", "占位，见下"),
}

print("== ant_spot.py 的时间常量对账 ==")
bad = []
for name, (iso_s, what) in TRUTH.items():
    got = getattr(S, name, None)
    if name == "POST_CLOSE":
        want = ep("2026-11-20T01:00:00Z")   # 20:00 ET 盘后结束 = 次日 01:00Z
        what = "20:00 ET 盘后结束（次日 01:00Z）"
    else:
        want = ep(iso_s)
    d = (got - want) if got is not None else None
    flag = "OK" if d == 0 else "**差 %+d 秒**" % d
    print("   %-14s 代码 %d (%s)   应为 %d (%s)   %s"
          % (name, got, hm(got), want, hm(want), flag))
    print("                  %s" % what)
    if d != 0:
        bad.append((name, got, want, d))

print()
print("== ET_TO_UTC_OFFSET ==")
off = getattr(S, "ET_TO_UTC_OFFSET", None)
print("   代码 %s 秒；2026-11-19 为 EST（DST 于 11/1 结束）⇒ 应为 18000  %s"
      % (off, "OK" if off == 18000 else "**不符**"))

print()
print("== 用实际数据反验 REGULAR_CLOSE：密集采样窗口的中心在哪 ==")
spot, _ = R.load_spot()
q = sorted(r["t_epoch"] for r in spot
           if r.get("kind") == "quote" and r.get("t_epoch"))
# 每 60 秒一桶，数 quote 条数，看最密的区间
import collections
buck = collections.Counter(int(t // 60) * 60 for t in q)
top = buck.most_common(1)[0]
dense = sorted(b for b, n in buck.items() if n >= 20)
print("   最密的一分钟: %s 有 %d 条" % (hm(top[0]), top[1]))
if dense:
    print("   条数 >=20 的分钟区间: %s → %s（共 %d 个分钟）"
          % (hm(dense[0]), hm(dense[-1]), len(dense)))
    mid = (dense[0] + dense[-1]) // 2
    print("   该区间中点: %s" % hm(mid))
    print("   与代码 REGULAR_CLOSE 的差: %+d 秒" % (mid - S.REGULAR_CLOSE))
    print("   ⇒ 若差值在 ±120 秒内，说明 ±600s 密集窗口确实以收盘为中心")

print()
print("== 结论 ==")
if not bad and off == 18000:
    print("   所有手算常量与库函数算出的值一致，未发现偏差。")
    print("   但它们仍是手抄的 —— 按「凡能从源头推导的都不要手抄」，")
    print("   本节把对账脚本留下，作为这些常量的持续校验。")
else:
    for name, got, want, d in bad:
        print("   **%s 错了 %+d 秒**（代码 %d / 应为 %d）" % (name, d, got, want))
