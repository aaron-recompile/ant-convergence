#!/usr/bin/env python3
"""核三处:两条 ask 的量、整本书的起始时刻、盘口的场所覆盖面。

另一路指出本路 7.71.3 三处要改:
  ① ask_size 是 20.22（16:48:04Z）与 2.82（16:48:09Z）——
     **本路把第二条的量贴到了两条上**，写成「size 2.82（极薄）」；
  ② depth_*.jsonl 最早 18:22:33Z，**比撮合晚 94 分钟**
     ⇒ 「更深档位是否也在 111.50 之上」不可答；
  ③ 盘前带 `ask` 的只有 3/6 家（kraken / gate / bitget），
     而没有的三家包含 **hl_xyz_ANT —— 本数据集里最深的场所**。
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
            recs.append((ts, d))
recs.sort(key=lambda x: x[0])

print("=== ① 那两条 ask > 111.50 的全字段 ===")
for ts, d in recs:
    b = d.get("kraken_PF_ANTXUSD")
    if not isinstance(b, dict):
        continue
    a = b.get("ask")
    if isinstance(a, (int, float)) and float(a) > 111.5:
        print("  %sZ  ask=%s  **ask_size=%s**  bid=%s  bid_size=%s  mark=%s  index=%s  last=%s"
              % (ts[11:], a, b.get("ask_size"), b.get("bid"), b.get("bid_size"),
                 b.get("mark"), b.get("index"), b.get("last")))

print()
print("=== ② 整本盘口（depth）的起始时刻 ===")
for name, p in (("depth_2026-11-19.jsonl", os.path.join(D, "depth_2026-11-19.jsonl")),
                ("rescued_depth_2026-11-19.jsonl",
                 os.path.join(RESC, "rescued_depth_2026-11-19.jsonl"))):
    if not os.path.exists(p):
        print("  %-34s 不在本机" % name)
        continue
    n, first, last = 0, None, None
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or any(ln.startswith(x) for x in CONFLICT):
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or d.get("ts") or "")[:19]
        if not ts:
            continue
        n += 1
        if first is None or ts < first:
            first = ts
        if last is None or ts > last:
            last = ts
    print("  %-34s %5d 条   %sZ → %sZ" % (name, n, first[11:] if first else "—",
                                          last[11:] if last else "—"))
import calendar
import time
try:
    t0 = calendar.timegm(time.strptime("2026-11-19T18:22:33", "%Y-%m-%dT%H:%M:%S"))
    t1 = calendar.timegm(time.strptime("2026-11-19T16:48:26", "%Y-%m-%dT%H:%M:%S"))
    print("  **最早 18:22:33Z 比撮合 16:48:26Z 晚 %.0f 分钟**" % ((t0 - t1) / 60.0))
except Exception:
    pass

print()
print("=== ③ 盘口的场所覆盖面（盘前）===")
print("| 场所 | 盘前块 | **带 ask** | 占比 | ask 最高 |")
print("|---|---|---|---|---|")
for v in VENUES:
    blocks = [d.get(v) for _, d in recs if isinstance(d.get(v), dict)]
    blocks = [b for b in blocks if b.get("via") != "coingecko"]
    has = [b for b in blocks if b.get("ask") is not None]
    mx = max((float(b["ask"]) for b in has), default=None)
    flag = "  **← 无卖价**" if not has else ""
    print("| %s | %d | **%d** | %.0f%% | %s |%s"
          % (v, len(blocks), len(has),
             100.0 * len(has) / max(1, len(blocks)),
             ("%.4f" % mx) if mx is not None else "—", flag))

print()
print("=== 判读 ===")
print("  ① 若两条的 ask_size 不同 ⇒ 本路把其中一条的量贴到了两条上，要分开报。")
print("  ② 若 depth 最早晚于撮合 ⇒ 「更深档位」在任何场所上都不可答。")
print("  ③ 若只有 3/6 家带 ask ⇒ 卖价一侧的陈述只覆盖一半场所，")
print("     **而缺的那三家里有最深的那一家 ⇒ 不能说成「整个市场」。**")
