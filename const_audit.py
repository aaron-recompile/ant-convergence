"""审计本路代码里所有手算的时间常量 —— 与库函数算出的值对账。

动机：spot_gaps.py 初版手算 epoch 差了整 600 秒（7.17.1）。
另一个会话把它推广成「凡能从源头推导的，都不要手抄」。
`ant_spot.py` 里 REGULAR_OPEN / REGULAR_CLOSE / POST_CLOSE / ET_TO_UTC_OFFSET
都是由 TRADING_DAY 推出来的，必须逐个对账 —— 若 REGULAR_CLOSE 偏了，
收盘 ±600s 的密集采样窗口就对错了中心。

**2026-11-20 更正（7.47）。** 初版把真值表手抄成三个 **2026-11-19 的绝对时刻**，
并硬断言「11 月是 EST ⇒ 18000 秒」。于是 11-20 当天跑它，打出三行
「**REGULAR_OPEN 错了 +86400 秒**」—— 全是假警报：那天采集器的常量本来
就该是 11-20 的。更难看的是它同时读 **11-19 的数据**做反验，
一份报告里混了两天的东西，还给出一个自信的判决。

**这个脚本的 docstring 引着「凡能从源头推导的都不要手抄」，
然后把真值手抄了 —— 审计器违反了它自己要执行的那条规则。**
一个会喊狼来了的审计器会被忽略，而它恰好是专门负责告诉我常量对不对的那个工具。

现在：真值由 `S.TRADING_DAY` + `zoneinfo` 推出（DST 也不再由我断言），
反验读的是同一天的数据（靠 `ant_spot_read._set_day`，见 7.46）。
"""
import calendar
import collections
import datetime as dt
import os
import sys
import time
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot as S      # noqa: E402  只读常量，不启动任何循环
import ant_spot_read as R  # noqa: E402

ET = ZoneInfo("America/New_York")


def ep(iso_s):
    return calendar.timegm(time.strptime(iso_s, "%Y-%m-%dT%H:%M:%SZ"))


def hm(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


DAY = S.TRADING_DAY
_d = dt.date.fromisoformat(DAY)


def et_instant(day, h, m):
    """那一天 ET 的 h:m 对应的 epoch —— 由 tz 库推，不手算偏移。"""
    return int(dt.datetime(day.year, day.month, day.day, h, m, tzinfo=ET).timestamp())


# 由 TRADING_DAY 推导，而不是手抄。POST_CLOSE 是 20:00 ET，仍在同一个 ET 日。
TRUTH = {
    "REGULAR_OPEN":  (et_instant(_d, 9, 30),  "09:30 ET 开市"),
    "REGULAR_CLOSE": (et_instant(_d, 16, 0),  "16:00 ET 收盘"),
    "POST_CLOSE":    (et_instant(_d, 20, 0),  "20:00 ET 盘后结束"),
}

_off_s = -int(dt.datetime(_d.year, _d.month, _d.day, 12, 0,
                          tzinfo=ET).utcoffset().total_seconds())
_tzname = dt.datetime(_d.year, _d.month, _d.day, 12, 0, tzinfo=ET).tzname()

print("== 审计对象 ==")
print("   ant_spot.py 本次导入推出的 TRADING_DAY = %s（%s，ET = UTC-%d）"
      % (DAY, _tzname, _off_s // 3600))
print("   真值由该日 + zoneinfo 推出，**不再手抄绝对时刻**（7.47）")

# 7.8 的教训：读到的是制品，跑着的是进程。导入推出的日子不一定是在跑那个进程的日子。
print()
print("== 制品 vs 进程：实际在被写的是哪一天的文件 ==")
_data = os.path.expanduser("~/ant-convergence/data")
_cands = sorted(f for f in os.listdir(_data)
                if f.startswith("spot_") and f.endswith(".jsonl"))
if _cands:
    _newest = max(_cands, key=lambda f: os.path.getmtime(os.path.join(_data, f)))
    _nday = _newest[len("spot_"):-len(".jsonl")]
    _age = time.time() - os.path.getmtime(os.path.join(_data, _newest))
    print("   最近被追加的 spot 文件: %s（%.0f 秒前）" % (_newest, _age))
    if _nday != DAY:
        print("   **⚠ 与本次导入推出的 %s 不一致** —— 在跑的进程与本脚本看的不是同一天，"
              % DAY)
        print("     下面的对账说的是「代码此刻会推出什么」，不是「进程当初推出了什么」。")
    else:
        print("   与本次导入推出的 %s 一致。" % DAY)

print()
print("== ant_spot.py 的时间常量对账 ==")
bad = []
for name, (want, what) in TRUTH.items():
    got = getattr(S, name, None)
    if got is None:
        print("   %-14s **代码里没有这个常量**" % name)
        bad.append((name, None, want, None))
        continue
    d = got - want
    flag = "OK" if d == 0 else "**差 %+d 秒**" % d
    print("   %-14s 代码 %d (%s)   应为 %d (%s)   %s"
          % (name, got, hm(got), want, hm(want), flag))
    print("                  %s" % what)
    if d != 0:
        bad.append((name, got, want, d))

print()
print("== ET_TO_UTC_OFFSET ==")
off = getattr(S, "ET_TO_UTC_OFFSET", None)
print("   代码 %s 秒；%s 在 %s ⇒ 应为 %d  %s"
      % (off, DAY, _tzname, _off_s, "OK" if off == _off_s else "**不符**"))

print()
print("== 用实际数据反验 REGULAR_CLOSE：密集采样窗口的中心在哪 ==")
R._set_day(DAY)          # 7.46：读同一天的数据，不要拿别日的数据反验今日的常量
spot, _ = R.load_spot()
q = sorted(r["t_epoch"] for r in spot
           if r.get("kind") == "quote" and r.get("t_epoch"))
if not q:
    print("   %s 没有 quote 记录 —— 无法反验。" % DAY)
else:
    buck = collections.Counter(int(t // 60) * 60 for t in q)
    top = buck.most_common(1)[0]
    dense = sorted(b for b, n in buck.items() if n >= 20)
    print("   数据日 = %s，quote 共 %d 条，覆盖 %s – %s"
          % (DAY, len(q), hm(q[0]), hm(q[-1])))
    print("   最密的一分钟: %s 有 %d 条" % (hm(top[0]), top[1]))
    if q[-1] < S.REGULAR_CLOSE:
        print("   **本场尚未收盘（最后一条 %s < REGULAR_CLOSE %s）**"
              % (hm(q[-1]), hm(S.REGULAR_CLOSE)))
        print("   ⇒ 密集窗口还没出现，这一项**本次不可反验**，不是不符。")
    elif dense:
        print("   条数 >=20 的分钟区间: %s → %s（共 %d 个分钟）"
              % (hm(dense[0]), hm(dense[-1]), len(dense)))
        mid = (dense[0] + dense[-1]) // 2
        print("   该区间中点: %s" % hm(mid))
        print("   与代码 REGULAR_CLOSE 的差: %+d 秒" % (mid - S.REGULAR_CLOSE))
        print("   ⇒ 若差值在 ±120 秒内，说明 ±600s 密集窗口确实以收盘为中心")
    else:
        print("   没有任何一分钟达到 20 条 —— 密集窗口未生效或采样率变了，值得看。")

print()
print("== 结论 ==")
if not bad and off == _off_s:
    print("   %s 的时间常量全部与 zoneinfo 推出的值一致，未发现偏差。" % DAY)
else:
    for name, got, want, d in bad:
        if d is None:
            print("   **%s 缺失**" % name)
        else:
            print("   **%s 错了 %+d 秒**（代码 %d / 应为 %d）" % (name, d, got, want))
    if off != _off_s:
        print("   **ET_TO_UTC_OFFSET 不符**（代码 %s / 应为 %d）" % (off, _off_s))
