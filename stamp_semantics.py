#!/usr/bin/env python3
"""「一秒之内」那个结论真正依赖的前提是什么。

7.53.2 我登记的前提是「两台采集器的时钟同步到 <<1s」。
**那条可能说错了方向** —— 两个采集器都在 mini 上(本路 ant_spot.py pid 49915、
另一路 collector.py pid 2797),同一个时钟,这个前提自动满足。

真正的前提是**时戳语义**:一个记录的 ts 是在 HTTP 取数之**前**打的还是之**后**打的?
本路 `official_close()` 是 `t = now_s()` 然后 `get(...)` ⇒ **ts = 取数开始**。
若另一路的 ts_utc 是取数结束,则两者的"观测时刻"系统性相差一个取数耗时
(本路中位 2.18s,p90 3.24s)—— **那会直接摧毁"一秒之内"这个结论。**

本脚本:
  ① 确认两个采集进程是否同机
  ② 从各自的记录里推时戳语义(ts 与 fetch ms 的关系、同一记录内多个块的 ms)
  ③ 若语义不同,给出"一秒之内"该放宽到多少
"""
import io
import json
import os
import subprocess

print("=== ① 两个采集进程是否同机 ===")
for name in ("ant_spot.py", "collector.py"):
    r = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True)
    pids = [x for x in r.stdout.split() if x]
    print("  %-16s pid=%s (本机 = mini)" % (name, pids))
print("  ⇒ 若两者都在本机,则无跨机时钟问题。")

print()
print("=== ② 本路记录的时戳语义 ===")
D = os.path.expanduser("~/ant-convergence/data")
mine = None
for ln in io.open(os.path.join(D, "spot_2026-11-19.jsonl"), errors="replace"):
    ln = ln.strip()
    if not ln:
        continue
    try:
        d = json.loads(ln)
    except Exception:
        continue
    if d.get("kind") == "multi" and d.get("nasdaq_info"):
        mine = d
        break
if mine:
    print("  本路 kind=multi 记录:")
    print("    ts = %s" % mine.get("ts"))
    for k in ("nasdaq_info", "nasdaq_summary", "nasdaq_nls", "yahoo", "cnbc"):
        b = mine.get(k) or {}
        if b:
            print("    %-16s ms=%s" % (k, b.get("ms")))
    tot = sum((mine.get(k) or {}).get("ms") or 0
              for k in ("nasdaq_info", "nasdaq_summary", "nasdaq_nls", "yahoo", "cnbc"))
    print("    各块 ms 之和 = %d ms" % tot)
    print("    ⇒ 本路一条 multi 记录里,各源不是同一瞬间取的;")
    print("      ts 是该轮**开始**的时刻（代码:t = now_s() 在 get() 之前）。")
    print("      所以本路某个源的实际观测时刻 ≈ ts + 它之前那些源的 ms 之和。")

print()
print("=== ③ 另一路记录的时戳语义（读其文件，不改） ===")
peer = None
for ln in io.open(os.path.join(D, "ant_2026-11-19.jsonl"), errors="replace"):
    ln = ln.strip()
    if not ln or ln.startswith(("<<<", "===", ">>>", "|||")):
        continue
    try:
        d = json.loads(ln)
    except Exception:
        continue
    if d.get("spot_ANT_nasdaq"):
        peer = d
        break
if peer:
    print("  另一路记录的顶层键:", sorted(peer.keys())[:14])
    sp = peer.get("spot_ANT_nasdaq") or {}
    print("  ts_utc = %s" % peer.get("ts_utc"))
    print("  spot_ANT_nasdaq 的键: %s" % sorted(sp.keys()))
    for k in ("ms", "latency_ms", "elapsed_ms", "fetched_at", "t_fetch"):
        if k in sp:
            print("    %s = %s" % (k, sp[k]))
    tl = [k for k in peer if "ms" in k.lower() or "latency" in k.lower()
          or "elapsed" in k.lower()]
    print("  顶层带 ms/latency 的键: %s" % (tl or "无"))

print()
print("=== 判读 ===")
print("  本路 ts = 该轮取数开始;某源的观测时刻需加上它之前各源的 ms。")
print("  **若另一路的 ts_utc 语义不同(例如取数结束),两边的『同一时刻』**")
print("  **就系统性错开一个取数耗时量级(本路中位 2.18s)。**")
print()
print("  ⇒ 对 7.53.2 那个「一秒之内」:")
print("     真正的前提不是时钟同步(同机,自动满足),")
print("     而是**两边时戳语义一致**。若语义未经核对,")
print("     那个区间应放宽到 ±(取数耗时) 量级,即约 ±2–3 秒,")
print("     **而不是一秒之内**。")
