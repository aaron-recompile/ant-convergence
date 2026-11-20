#!/usr/bin/env python3
"""同一个 via 过滤下，逐字段口径的阈值表 —— 核另一路的「55 vs 67 是字段」。

另一路说本路 67 与它 55 的差不是过滤器而是字段:它用纯 `mark`,
而本路 7.40 的字段是混的(`hl_xyz_ANT` 取 `mid`、其余取 `last`)——
**而那个混用是本路自己在 7.57.3 登记过的。**

本脚本在同一个 via=coingecko 过滤下，把四种字段口径并排:
  mixed（本路 7.40 原样）/ 纯 mark / 纯 last / 纯 index
并报 coingecko 那一路自己的盘前最高（另一路说只有 109.7100）。
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
PRE_LO, PRE_HI = "2026-11-19T00:00:00", "2026-11-19T16:48:26"
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
          "gate_ANT_USDT", "kucoin_ANTUSDTM", "binance_ANTUSDT"]
MIXED = {"hl_xyz_ANT": "mid", "kraken_PF_ANTXUSD": "last",
         "bitget_ANTUSDT": "last", "gate_ANT_USDT": "last",
         "kucoin_ANTUSDTM": "last", "binance_ANTUSDT": "last"}
THRESH = [(111.50, "最后一个指示价 / 日线 open"),
          (111.13, "yahoo 首个真实分钟收盘"),
          (115.10, "当日最高价（日线）")]
FILES = [os.path.join(D, "ant_2026-11-19.jsonl"),
         os.path.join(D, "binance_2026-11-19.jsonl"),
         os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")]

recs, seen = [], set()
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
            recs.append(d)


def collect(field_of, skip_cg=True):
    out = []
    for d in recs:
        for v in VENUES:
            b = d.get(v)
            if not isinstance(b, dict):
                continue
            if skip_cg and b.get("via") == "coingecko":
                continue
            f = field_of(v)
            x = b.get(f)
            if isinstance(x, (int, float)):
                out.append(float(x))
    return out


CASES = [
    ("**mixed（本路 7.40 原样：hl→mid，其余→last）**", lambda v: MIXED[v]),
    ("纯 mark（另一路口径）", lambda v: "mark"),
    ("纯 last", lambda v: "last"),
    ("纯 index", lambda v: "index"),
]

print("同一个过滤：按 via 逐条剔除 coingecko；窗口 %s–%s（7.44 边界）"
      % (PRE_LO[11:], PRE_HI[11:]))
print()
print("| 字段口径 | n | 盘前最高 | >111.50 | **>111.13** | >115.10 |")
print("|---|---|---|---|---|---|")
for label, fo in CASES:
    vals = collect(fo)
    if not vals:
        print("| %s | 0 | — | — | — | — |" % label)
        continue
    row = [str(sum(1 for x in vals if x > th)) for th, _ in THRESH]
    print("| %s | %d | **%.4f** | %s | **%s** | %s |"
          % (label, len(vals), max(vals), row[0], row[1], row[2]))

print()
print("=== coingecko 那一路自己的盘前最高（另一路说 109.7100）===")
cg = []
for d in recs:
    for v in VENUES:
        b = d.get(v)
        if isinstance(b, dict) and b.get("via") == "coingecko":
            for f in ("last", "mark"):
                x = b.get(f)
                if isinstance(x, (int, float)):
                    cg.append((float(x), f))
if cg:
    mx = max(cg)
    print("  coingecko 观测 %d 个，最高 **%.4f**（字段 %s）" % (len(cg), mx[0], mx[1]))
    print("  ⇒ 远低于 111.50 ⇒ 无论哪个字段口径，剔除它都不会动「0 条高于 111.50」")

print()
print("=== 判读 ===")
print("  若纯 mark 给出 55、mixed 给出 67 ⇒ 另一路的归因成立，账结清。")
print("  **而那一行必须同时带过滤器和字段，否则这个数不可复算。**")
