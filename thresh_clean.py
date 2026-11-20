#!/usr/bin/env python3
"""核 7.40 的阈值结论在剔掉缓存源后是否成立 —— 测了再说，不写成判断。

我向另一路说「阈值类结论不受影响:一个陈旧报价仍然是窗口内某一刻的真实报价,
阈值问题不要求同时刻配对」。**那是个判断,不是实测。** 这里实测。

两个口径:
  全部六家(含 bitget/gate/kucoin 缓存源、含 binance_ANTUSDT)
  只用非缓存两家(hl_xyz_ANT / kraken_PF_ANTXUSD)

注意边界效应:缓存值可能把**窗口之前**的报价带进窗口的最初 ~20 秒
(冻结 p90 20s、最大 103s)。所以额外报一个「掐掉窗口头 120 秒」的版本。
"""
import io
import json
import os
import statistics

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
PRE_LO, PRE_HI = "2026-11-19T00:00:00", "2026-11-19T16:48:26"   # 7.44 更正后的边界
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

ALL6 = {"hl_xyz_ANT": "mid", "kraken_PF_ANTXUSD": "last",
        "bitget_ANTUSDT": "last", "gate_ANT_USDT": "last",
        "kucoin_ANTUSDTM": "last", "binance_ANTUSDT": "last"}
CLEAN = {"hl_xyz_ANT": "mid", "kraken_PF_ANTXUSD": "last"}
THRESHOLDS = [
    (111.50, "最后一个指示价 / 日线 open（两个独立出处）"),
    (111.13, "yahoo 首个真实分钟收盘（7.17）"),
    (115.10, "当日最高价（日线，7.49.6）"),
    (97.17, "当日官方收盘价（三源一致）"),
]

FILES = [os.path.join(D, "ant_2026-11-19.jsonl"),
         os.path.join(D, "binance_2026-11-19.jsonl"),
         os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")]

recs = []
seen = set()
for p in FILES:
    if not os.path.exists(p):
        continue
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen or any(ln.startswith(x) for x in CONFLICT):
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if PRE_LO <= ts < PRE_HI:
            recs.append((ts, d))
recs.sort(key=lambda x: x[0])


def collect(venues, skip_head_s=0):
    out = []
    lo = PRE_LO
    if skip_head_s:
        # 掐掉首个有观测时刻之后的 skip_head_s 秒
        first = None
        for ts, d in recs:
            if any(isinstance((d.get(v) or {}).get(f), (int, float))
                   or isinstance((d.get(v) or {}).get("mark"), (int, float))
                   for v, f in venues.items()):
                first = ts
                break
        if first:
            import calendar
            import time
            t0 = calendar.timegm(time.strptime(first, "%Y-%m-%dT%H:%M:%S"))
            lo = time.strftime("%Y-%m-%dT%H:%M:%S",
                               time.gmtime(t0 + skip_head_s))
    for ts, d in recs:
        if ts < lo:
            continue
        for v, f in venues.items():
            blk = d.get(v)
            if not isinstance(blk, dict):
                continue
            x = blk.get(f)
            if x is None:
                x = blk.get("mark")
            if isinstance(x, (int, float)):
                out.append((ts, float(x)))
    return out


CASES = [("全部六家（含缓存，7.40 原口径）", ALL6, 0),
         ("**只用非缓存两家**", CLEAN, 0),
         ("全部六家，掐掉窗口头 120 秒", ALL6, 120)]

for label, venues, skip in CASES:
    obs = collect(venues, skip)
    if not obs:
        print("%s: 无观测" % label)
        continue
    vals = [x for _, x in obs]
    print("══ %s ══" % label)
    print("  观测数 %d   最高 %.4f   中位 %.4f" % (len(vals), max(vals),
                                             statistics.median(vals)))
    print("  | 阈值 | 出处 | 高于它的 | 占比 |")
    print("  |---|---|---|---|")
    for th, src in THRESHOLDS:
        k = sum(1 for x in vals if x > th)
        print("  | **%.2f** | %s | **%d** | %.2f%% |"
              % (th, src, k, 100.0 * k / len(vals)))
    print()

print("=== 判读 ===")
print("  若三个口径下「高于 111.50」都是 0,则 7.40 的头号结论与缓存无关,")
print("  我那句「阈值问题不要求同时刻配对」成立 —— 而现在它是实测的,不是判断。")
print("  若某个口径下不为 0,那句话要撤。")
