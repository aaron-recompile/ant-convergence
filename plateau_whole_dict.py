#!/usr/bin/env python3
"""决定性检验:16:12:59–16:13:12 那个平台上，三家缓存源是「回放」还是「上游 mark 真没变」?

本路 7.56 断言「16:13:15Z 是一次缓存刷新」,**前提是那三家在回放**。
但另一路实测 bitget 整字典全冻 0%、gate 4% —— 若那个平台上它们的
买卖价/成交量在动而只有 mark 不变,**那就是上游 mark 真的没变**,
于是那 4 次 P−I 为正是真实市场结构,**7.56 的因果要撤**。

办法(另一路给的,本路独立实现):逐字段看平台期间谁动了。
见证字段必须**全天真的变过**,否则一个常量字段会把「全冻」判成真 ——
那正是另一路第一版恒真的来源,本路不重犯。
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD",
          "gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"]
# **窗口必须止于刷新之前。** 初版用 16:12:55–16:13:16，把 16:13:15Z 那次刷新
# 包进去了，于是五家的 mark 都「在动」—— 它们就是在那一刻动的。
# 要测的是冻结区间本身：那 4 条 mark 不变的采样。
PLATEAU_LO, PLATEAU_HI = "2026-11-19T16:12:59", "2026-11-19T16:13:12"

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

# ── ① 先定出每个场所「全天真的变过」的字段 ────────────────────
varying = {}
for v in VENUES:
    vals = collections.defaultdict(set)
    for ts, d in rows:
        b = d.get(v)
        if not isinstance(b, dict):
            continue
        for k, x in b.items():
            if isinstance(x, (int, float, str, bool)) or x is None:
                vals[k].add(repr(x))
    varying[v] = sorted(k for k, s in vals.items() if len(s) > 1)
    print("  %-22s 全天变过的字段 %d 个: %s"
          % (v, len(varying[v]), ", ".join(varying[v][:9])
             + (" …" if len(varying[v]) > 9 else "")))

print()
print("=== ② 那个平台上，逐场所看哪些字段动了 ===")
seg = [(ts, d) for ts, d in rows if PLATEAU_LO <= ts <= PLATEAU_HI]
print("  平台窗口 %s–%s，记录 %d 条" % (PLATEAU_LO[11:], PLATEAU_HI[11:], len(seg)))
print()
for v in VENUES:
    obs = [(ts, d.get(v)) for ts, d in seg if isinstance(d.get(v), dict)]
    if len(obs) < 2:
        print("  %-22s 样本不足" % v)
        continue
    wits = varying[v]
    moved, frozen, allnone = [], [], []
    for k in wits:
        vs = [repr(b.get(k)) for _, b in obs]
        nonnull = [x for x in vs if x != "None"]
        if not nonnull:
            allnone.append(k)
        elif len(set(vs)) > 1:
            moved.append(k)
        else:
            frozen.append(k)
    print("  %-22s 见证字段 %d  **动了 %d**  冻住 %d  全空 %d"
          % (v, len(wits), len(moved), len(frozen), len(allnone)))
    print("      mark 本身: %s"
          % ("**冻住**" if len({repr(b.get("mark")) for _, b in obs}) == 1
             else "在动"))
    if moved:
        print("      动了的: %s" % ", ".join(moved[:10]))
    if allnone:
        print("      全空(不可作见证): %s" % ", ".join(allnone[:8]))

print()
print("=== ③ 自检:窗口选对了吗 ===")
for v in ("gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"):
    obs = [d.get(v) for ts, d in seg if isinstance(d.get(v), dict)]
    uniq = {repr(b.get("mark")) for b in obs}
    print("  %-22s 窗口内 mark 取值数 %d  %s"
          % (v, len(uniq), "✓ 冻住" if len(uniq) == 1 else "**✗ 在动 —— 窗口选错了**"))
print()
print("=== ④ 判读 ===")
print("  对 gate / bitget / kucoin:")
print("    若 mark 冻住**且**见证字段也全冻 ⇒ 回放 ⇒ 7.56 的因果成立;")
print("    若 mark 冻住**而**见证字段在动 ⇒ 上游 mark 真没变")
print("       ⇒ **那 4 次 P−I 为正是真实结构,7.56 的因果要撤。**")
print()
print("  注意:本检验要求见证字段全天变过(上面①已筛),")
print("  否则常量字段会把「全冻」判成真 —— 那是另一路第一版恒真的来源。")
