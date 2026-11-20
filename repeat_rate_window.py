#!/usr/bin/env python3
"""独立核:重复率在「结论所在的窗口」是多少,以及闭式解对不对。

另一路指出本路 7.58.3 报的 63% 是**全天**数,而本路那三个载重数字
(窗口内为正 / 最长连负 / 最后由正转负)所在的竞价窗口是 **73%**。
**又是「报了数没带窗口」** —— 而换成 63% 会低估约 10pp。

它还给了闭式解:取数发生在 `now − c[0] >= every` 的第一个采样上
⇒ 每 ceil(every/iv) 个采样只有 1 个真取数
⇒ 预测重复率 = 1 − 1/ceil(15/iv)

本脚本:逐窗口算实测间隔中位、实测重复率、闭式预测,三者并排。
见证字段须全天真的变过(避免恒真)。
"""
import collections
import io
import json
import math
import os
import statistics

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD",
          "gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"]
CACHED = {"gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"}
EVERY = 15.0

import calendar
import time


def ep(s):
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


rows, seen = [], set()
for path in (os.path.join(D, "ant_2026-11-19.jsonl"),
             os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")):
    if not os.path.exists(path):
        continue
    for ln in io.open(path, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen or any(ln.startswith(x) for x in CONFLICT):
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if ts.startswith("2026-11-19"):
            rows.append((ts, d))
rows.sort(key=lambda x: x[0])

# 见证字段（全天变过）
vals = {v: collections.defaultdict(set) for v in VENUES}
for ts, d in rows:
    for v in VENUES:
        b = d.get(v)
        if isinstance(b, dict):
            for k, x in b.items():
                if isinstance(x, (int, float, str, bool)) or x is None:
                    vals[v][k].add(repr(x))
WIT = {v: sorted(k for k, s in vals[v].items() if len(s) > 1) for v in VENUES}

WINDOWS = [
    ("全天", "00:00:00", "23:59:59"),
    ("**竞价窗口 14:50:06–16:48:21（结论所在）**", "14:50:06", "16:48:21"),
    ("00:00–13:00 (名义 10s)", "00:00:00", "13:00:00"),
    ("13:00–14:30 (名义 3s)", "13:00:00", "14:30:00"),
    ("14:30–19:00 (名义 2s)", "14:30:00", "19:00:00"),
    ("19:00–21:30 (名义 5s)", "19:00:00", "21:30:00"),
    ("21:30–24:00 (名义 10s)", "21:30:00", "23:59:59"),
]

print("| 窗口 | 记录 | 实测间隔中位 | 闭式预测 | gate | bitget | kucoin | hl | kraken |")
print("|---|---|---|---|---|---|---|---|---|")
for label, lo, hi in WINDOWS:
    seg = [(ts, d) for ts, d in rows
           if "2026-11-19T" + lo <= ts <= "2026-11-19T" + hi]
    if len(seg) < 3:
        print("| %s | %d | — | — | — | — | — | — | — |" % (label, len(seg)))
        continue
    # 实测间隔（按秒去重后相邻差）
    ts_list = sorted({ep(t) for t, _ in seg})
    gaps = [ts_list[i] - ts_list[i - 1] for i in range(1, len(ts_list))]
    iv = statistics.median(gaps) if gaps else 0
    pred = (1 - 1.0 / math.ceil(EVERY / iv)) * 100 if iv > 0 else float("nan")
    # 实测重复率（本窗口内，相对本窗口内上一条）
    rate = {}
    for v in VENUES:
        prev, nf, nt = None, 0, 0
        for ts, d in seg:
            b = d.get(v)
            if not isinstance(b, dict):
                continue
            sig = tuple(repr(b.get(k)) for k in WIT[v])
            nt += 1
            if prev is not None and prev == sig:
                nf += 1
            prev = sig
        rate[v] = 100.0 * nf / max(1, nt)
    print("| %s | %d | %ds | **%.1f%%** | %.1f%% | %.1f%% | %.1f%% | %.1f%% | %.1f%% |"
          % (label, len(seg), iv, pred,
             rate["gate_ANT_USDT"], rate["bitget_ANTUSDT"],
             rate["kucoin_ANTUSDTM"], rate["hl_xyz_ANT"],
             rate["kraken_PF_ANTXUSD"]))

print()
print("=== 判读 ===")
print("  ① 若竞价窗口的三家都在 73% 附近,则本路 7.58.3 的 63% 要更正为 73%：")
print("     那是全天数,而三个载重数字都在竞价窗口里。")
print("  ② 若闭式预测与实测逐窗口对上(除跨取整边界的那一档),")
print("     则这个率是**采集器配置的函数**,不是场所的性质 ——")
print("     论文里写它必须连 every=15s 与采样节奏一起写。")
print("  ③ hl / kraken 在每个窗口都接近 0 ⇒ 判据测的是节流不是市场安静。")
