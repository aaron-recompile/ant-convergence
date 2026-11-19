"""缺口三分法（修正版）。

初版（gap_classify.py）自己犯了另一个会话警告的那个错 —— **把「缺交易」标成了「缺数据」**。
两个 bug：
  1. 把 `14:38Z→16:48Z` 判成「缺数据（当时在交易）」。错两处：
     (a) 本路 18:24:43Z 才部署，这段**根本不在采集范围内**，不是空洞；
     (b) 把右边界分钟 16:48Z（首笔成交那一分钟）算进了「有成交」，
         于是 `traded and not mine` 误触发 —— 131 个分钟里 130 个无值，
         结论本该是「无成交」。
  2. 把 `21:14:39Z` 那段判成「无成交」。错在：**yahoo 的 `range=1d` 1 分钟序列
     只覆盖正常时段，到 21:00Z 为止**，盘后分钟根本不在里面。
     **「yahoo 没有值」≠「没有交易」** —— 盘后要用别的源判。

所以本版：先分「是否在采集范围内」，再按时段选合适的「有无交易」判据。
"""
import calendar
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.expanduser("~/ant-convergence"))
import ant_spot_read as R  # noqa: E402

ANT = os.path.expanduser("~/ant-convergence/data/ant_2026-11-19.jsonl")
DEPLOY = "2026-11-19T18:24:43Z"        # 本路首条记录
YAHOO_1M_ENDS = "2026-11-19T21:00:00Z"  # yahoo range=1d 的 1m 序列只到收盘


def ep(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def hm(t):
    return time.strftime("%H:%M:%SZ", time.gmtime(t))


WINDOWS = [
    ("2026-11-19T18:29:52Z", "2026-11-19T18:31:04Z", "本路单线程版换双线程版（7.6）"),
    ("2026-11-19T21:14:39Z", "2026-11-19T21:15:02Z", "本路为改对收盘路径重启（7.9.2）"),
    ("2026-11-19T14:38:00Z", "2026-11-19T16:48:00Z", "yahoo_1m 的 130 个 null 分钟（7.17.3）"),
]

ant = []
for ln in open(ANT, errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    try:
        d = json.loads(ln)
    except Exception:
        continue
    t = d.get("ts_epoch")
    if t is None and d.get("ts_utc"):
        try:
            t = calendar.timegm(time.strptime(d["ts_utc"][:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            t = None
    if t:
        ant.append(t)
ant.sort()

spot, _ = R.load_spot()
bars, _ = R.load_bars()
yh = {b["bar_ts"]: b for b in bars if b["src"] == "yahoo_1m"}
# 盘后用本路自己的 multi 快照里的 nasdaq 最新成交时间戳判「有没有在成交」
post_trades = []
for r in spot:
    ni = r.get("nasdaq_info") or {}
    if ni.get("traded") and ni.get("price_usd") is not None and r.get("t_epoch"):
        post_trades.append(r["t_epoch"])
post_trades.sort()

print("本路部署于 %s；yahoo 1m 序列止于 %s（仅正常时段）" % (DEPLOY, YAHOO_1M_ENDS))
print("主采集器可解析 %d 条\n" % len(ant))

rows = []
for a_s, b_s, why in WINDOWS:
    a, b = ep(a_s), ep(b_s)
    print("== %s → %s  (%.0fs)  %s" % (hm(a), hm(b), b - a, why))

    if b <= ep(DEPLOY):
        verdict = "**不在本路采集范围内**（本路 %s 才部署），不是空洞" % DEPLOY[11:]
        print("   本路: 未部署")
    else:
        mine = [r for r in spot if r.get("t_epoch") and a < r["t_epoch"] < b]
        print("   本路 spot 记录: %d 条" % len(mine))
        verdict = None

    # 「有没有在交易」—— 按时段选判据，**左闭右开，不含右边界分钟**
    mins = [t for t in range(a - a % 60, b, 60)]
    if b <= ep(YAHOO_1M_ENDS):
        traded = [t for t in mins
                  if yh.get(t) and not yh[t].get("no_value")
                  and yh[t].get("close_usd") is not None]
        basis = "yahoo_1m（正常时段，权威）"
    else:
        traded = [t for t in mins
                  if any(a <= x < b for x in post_trades)]
        basis = "本路 nasdaq_info.traded + 价格在动（盘后，yahoo 1m 不覆盖）"
    print("   该窗口 %d 个分钟（左闭右开，不含右边界）：有成交 %d 个 / 无 %d 个  判据：%s"
          % (len(mins), len(traded), len(mins) - len(traded), basis))

    cov = [t for t in ant if a < t < b]
    if cov:
        g = [cov[i + 1] - cov[i] for i in range(len(cov) - 1)]
        print("   主采集器同期: %d 条，间隔中位 %.1fs" % (len(cov), statistics.median(g) if g else 0))
    else:
        print("   主采集器同期: 0 条")

    if verdict is None:
        if traded:
            verdict = "**缺数据**（当时在交易，本路没采到）"
            if cov:
                verdict += "；但主采集器覆盖该时段 ⇒ **不是整个数据集的信息损失**"
        else:
            verdict = "**缺交易**（那段没有成交，`close_usd: null` 是正确值，不要去抢救）"
    print("   定性: %s\n" % verdict)
    rows.append((hm(a), hm(b), b - a, verdict))

print("== 汇总 ==")
print("| 窗口 | 时长 | 定性 |")
print("|---|---|---|")
for s0, e0, d, v in rows:
    print("| %s → %s | %.0fs | %s |" % (s0, e0, d, v.replace("\n", " ")))
