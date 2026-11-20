#!/usr/bin/env python3
"""两件:(a) 核另一路关于 mark 赋值点的代码断言;(b) 查本路 7.40 有没有混进 coingecko。

(a) 它说 `_kucoin()` 的 mark 直读端点 `markPrice`,五家全是端点字段直读、
    采集器从不推算 mark ⇒ 「mark 变了 ⇒ 这一次是真取数」成立 ⇒ 本路 1127 的前提确立。
    它说「这一问你答不了,答案在采集代码里」—— 但那份代码在 mini 上,
    **读它来核是可以的**(读以核实做过;改不碰)。

(b) 它查出 `binance_via_coingecko()` 里 `mark = last`(mark 是 last 的副本),
    而 `ant_*` 里 11-19 的 14,978 条币安全是这一路。R5 说整体排除。
    **但本路 event_preopen_threshold.py 的 PERPS 里有 binance_ANTUSDT: "last"** ——
    必须查本路那 50,710 个观测里有没有混进它,以及剔掉后结论动不动。
"""
import collections
import io
import json
import os
import re
import subprocess

HERE = os.path.expanduser("~/ant-convergence")
D = os.path.join(HERE, "data")
RESC = os.path.expanduser("~/ant-rescue")

print("════════ (a) 核代码:mark 的全部赋值点 ════════")
col = os.path.join(HERE, "collector.py")
if not os.path.exists(col):
    print("  collector.py 不在 %s" % HERE)
else:
    src = io.open(col, encoding="utf-8", errors="replace").read()
    lines = src.split("\n")
    hits = [(i, l) for i, l in enumerate(lines, 1)
            if re.search(r'"mark"\s*:', l)]
    print("  含 \"mark\": 的行 %d 处" % len(hits))
    for i, l in hits:
        # 找所属函数
        fn = "?"
        for j in range(i - 1, 0, -1):
            m = re.match(r"\s*def\s+(\w+)", lines[j - 1])
            if m:
                fn = m.group(1)
                break
        txt = l.strip()
        # 判断是直读端点字段还是本地推算
        direct = bool(re.search(r'"mark"\s*:\s*\w*\(?["\']?\w*(markPrice|mark_price'
                                r'|markPx|mark)["\']?', txt))
        copy_of = re.search(r'"mark"\s*:\s*([A-Za-z_][\w.\[\]()"\']*)', txt)
        print("    L%-5d %-26s %s" % (i, fn, txt[:88]))
        if copy_of:
            rhs = copy_of.group(1)
            flag = ("**直读端点字段**" if direct
                    else ("**不是端点 mark —— 右侧是 %s**" % rhs))
            print("           ⇒ %s" % flag)

print()
print("════════ (b) 本路 7.40 有没有混进 via=coingecko ════════")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
PRE_LO, PRE_HI = "2026-11-19T00:00:00", "2026-11-19T16:48:26"
PERPS = {"hl_xyz_ANT": "mid", "kraken_PF_ANTXUSD": "last",
         "bitget_ANTUSDT": "last", "gate_ANT_USDT": "last",
         "kucoin_ANTUSDTM": "last", "binance_ANTUSDT": "last"}
FILES = [os.path.join(D, "ant_2026-11-19.jsonl"),
         os.path.join(D, "binance_2026-11-19.jsonl"),
         os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")]

obs = []          # (venue, via, value, 文件)
seen = set()
for p in FILES:
    if not os.path.exists(p):
        continue
    base = os.path.basename(p)
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
        if not (PRE_LO <= ts < PRE_HI):
            continue
        for v, f in PERPS.items():
            b = d.get(v)
            if not isinstance(b, dict):
                continue
            x = b.get(f)
            if x is None:
                x = b.get("mark")
            if isinstance(x, (int, float)):
                obs.append((v, b.get("via"), float(x), base))

print("  盘前观测总数: %d   (7.40 报 50,710)" % len(obs))
by = collections.Counter((v, via, base) for v, via, _, base in obs)
print()
print("  | 场所 | via | 文件 | 条数 |")
print("  |---|---|---|---|")
for (v, via, base), n in sorted(by.items(), key=lambda kv: -kv[1]):
    mark = "  **← coingecko**" if via == "coingecko" else ""
    print("  | %s | %s | %s | %d |%s" % (v, via, base, n, mark))

cg = [o for o in obs if o[1] == "coingecko"]
print()
print("  **via=coingecko 的观测: %d 条（占 %.2f%%）**"
      % (len(cg), 100.0 * len(cg) / max(1, len(obs))))

print()
print("=== 剔掉 coingecko 之后，7.40 的阈值结论动不动 ===")
THRESH = [(111.50, "最后一个指示价 / 日线 open"),
          (111.13, "yahoo 首个真实分钟收盘"),
          (115.10, "当日最高价（日线）")]
for label, sel in (("7.40 原口径（全部）", obs),
                   ("**剔掉 via=coingecko**",
                    [o for o in obs if o[1] != "coingecko"])):
    vals = [x for _, _, x, _ in sel]
    if not vals:
        continue
    print("  %s  n=%d  最高 %.4f" % (label, len(vals), max(vals)))
    for th, src in THRESH:
        k = sum(1 for x in vals if x > th)
        print("     高于 %.2f (%s): **%d**  (%.2f%%)"
              % (th, src, k, 100.0 * k / len(vals)))
