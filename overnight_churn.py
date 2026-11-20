#!/usr/bin/env python3
"""实测:POST_CLOSE 之后守护循环会不会空转拉起,持续多久。

推理是:01:00Z 时 ET 为 11-20 的 20:00,tm_hour=20 不小于 4,
derive_trading_day 仍返回 2026-11-20 ⇒ 新进程的 POST_CLOSE 已过
⇒ exit_if_session_over 立刻 os._exit(0) ⇒ 守护 15 秒后再拉起。
直到 11-21 04:00 ET = 09:00Z 才会推出新的交易日。

**不凭推理,逐小时实测 derive_trading_day 与 POST_CLOSE 的关系。**
"""
import calendar
import os
import sys
import time

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot as S   # noqa: E402


def ep(iso_s):
    return calendar.timegm(time.strptime(iso_s, "%Y-%m-%dT%H:%M:%SZ"))


def hm(t):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def post_close_for(day):
    """照 ant_spot.py 的推导算某个交易日的 POST_CLOSE。"""
    base = ep(day + "T00:00:00Z")
    off = S._et_offset_for(int(day[:4]), int(day[5:7]), int(day[8:10]))
    return base + 20 * 3600 + off


print("| 假想时刻(UTC) | derive_trading_day | 该日 POST_CLOSE | now>=POST_CLOSE ⇒ 启动即退? |")
print("|---|---|---|---|")
churn_from = churn_to = None
for h in range(20, 44):                 # 11-20 20:00Z 到 11-21 19:00Z
    t = ep("2026-11-20T00:00:00Z") + h * 3600
    day = S.derive_trading_day(t)
    pc = post_close_for(day)
    dead = t >= pc
    print("| %s | %s | %s | %s |"
          % (hm(t), day, hm(pc), "**是（空转）**" if dead else "否（正常跑）"))
    if dead and churn_from is None:
        churn_from = t
    if dead:
        churn_to = t
    if not dead and churn_from is not None and churn_to is not None and t > churn_to:
        break

print()
if churn_from is not None:
    # 精确找首尾
    lo = churn_from - 3600
    while lo < churn_from:
        day = S.derive_trading_day(lo)
        if lo >= post_close_for(day):
            break
        lo += 60
    hi = churn_to
    while True:
        day = S.derive_trading_day(hi)
        if hi < post_close_for(day):
            break
        hi += 60
    print("=== 空转窗口 ===")
    print("  起: %s（本场 POST_CLOSE 到达）" % hm(lo))
    print("  止: %s（derive_trading_day 推出新交易日）" % hm(hi))
    print("  时长: %.1f 小时" % ((hi - lo) / 3600.0))
    print("  守护间隔 15 秒 ⇒ 空转拉起约 **%d 次**" % int((hi - lo) / 15))
    print()
    print("  每次启动都会执行 log_constant_audit(\"启动\", quiet_ok=False) ——")
    print("  我刻意让启动总是打心跳。于是 spot.log 会收到约 %d 条启动心跳。" % int((hi - lo) / 15))
    print("  **不是数据损失(本场已结束),但「启动心跳」这个信号会被淹成噪声** ——")
    print("  正是 7.33 那个形状:一个没人看的告警。")
else:
    print("=== 未发现空转窗口 —— 推理不成立,停下来重看。 ===")
