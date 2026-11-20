#!/usr/bin/env python3
"""独立核另一路报的 3 个盘后例外:21:00:39–21:00:55Z 簿子短暂上穿 97.17。

他报(采样中位间隔 7.00s):
  21:00:39Z ask 97.310  不高于 (−0.140)
  21:00:48Z ask 97.390  不高于 (−0.220)
  21:00:55Z ask 97.390  不高于 (−0.220)
  21:01:01Z 起 ask 回落到 96.97–97.05

本路 11-19 收盘窗口间隔 4.18s(旧「取完再睡」),比他密 —— 该看得更清。
若本路也看到那段上穿,则是独立确认;若看不到,那是个要查的分歧。

同时按他 9.58 那条补齐:带限定的结论要写「去掉限定会变成什么」。
"""
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
A = os.path.expanduser("~/ant-spot-archive")
DAY, CLOSE = "2026-11-19", 97.17

seen, rows = set(), []
for p in (os.path.join(D, "spot_%s.jsonl" % DAY),
          os.path.join(A, "spot_%s.jsonl" % DAY),
          os.path.join(A, "recovered_from_autostash_%s.jsonl" % DAY),
          os.path.join(A, "recovered_from_stash_pass2_%s.jsonl" % DAY)):
    if not os.path.exists(p):
        continue
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen:
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts") or "")[:19]
        if not ts.startswith(DAY):
            continue
        i = d.get("nasdaq_info") or {}
        b, a = i.get("bid_usd"), i.get("ask_usd")
        if b is None or a is None:
            continue
        rows.append((ts, float(b), float(a), i.get("price_usd"), i.get("state_src")))
rows.sort(key=lambda x: x[0])

LO, HI = DAY + "T21:00:30", DAY + "T21:01:30"
seg = [r for r in rows if LO <= r[0] <= HI]
print("=== 本路 %s 的 21:00:30–21:01:30Z（他报例外的那一段）===" % DAY)
print("| 时刻 | price | bid | ask | state | 97.17 − ask | 是否例外 |")
print("|---|---|---|---|---|---|---|")
exc = []
for ts, b, a, p, st in seg:
    d = CLOSE - a
    is_exc = d <= 0
    if is_exc:
        exc.append((ts, a, d))
    print("| %sZ | %s | %s | %s | %s | %+.4f | %s |"
          % (ts[11:], p, b, a, st, d, "**是**" if is_exc else "否"))

print()
print("  本路在这一段看到的例外: %d 个" % len(exc))
for ts, a, d in exc:
    print("     %sZ  ask %.3f  (%+.4f)" % (ts[11:], a, d))
print("  他报的例外时刻: 21:00:39Z / 21:00:48Z / 21:00:55Z (ask 97.310 / 97.390 / 97.390)")

# 本路最接近他那三个时刻的采样
print()
print("  本路最接近他那三个时刻的采样:")
for target in ("21:00:39", "21:00:48", "21:00:55"):
    t = DAY + "T" + target
    near = min(rows, key=lambda r: abs(
        (int(r[0][11:13]) * 3600 + int(r[0][14:16]) * 60 + int(r[0][17:19]))
        - (int(target[0:2]) * 3600 + int(target[3:5]) * 60 + int(target[6:8]))))
    print("     他 %sZ → 本路最近 %sZ  ask=%s  97.17−ask=%+.4f"
          % (target, near[0][11:], near[2], CLOSE - near[2]))

# 按他 9.58 的要求:两个窗口都报，并说明去掉限定会变成什么
print()
print("=== 按 9.58:带限定的结论要写「去掉限定会变成什么」===")
for label, lo, hi in (("跨越收盘钟 20:59:25–21:00:35Z", "20:59:25", "21:00:35"),
                      ("±2 分钟 20:58:00–21:02:00Z", "20:58:00", "21:02:00")):
    w = [r for r in rows if DAY + "T" + lo <= r[0] <= DAY + "T" + hi]
    if not w:
        print("  %s: 无采样" % label)
        continue
    above = sum(1 for _, b, a, _, _ in w if CLOSE > a)
    inside = sum(1 for _, b, a, _, _ in w if b <= CLOSE <= a)
    below = sum(1 for _, b, a, _, _ in w if CLOSE < b)
    print("  %s: n=%d  高于卖价 %d(%.0f%%)  价差内 %d  低于买价 %d(%.0f%%)"
          % (label, len(w), above, 100.0 * above / len(w), inside,
             below, 100.0 * below / len(w)))
print()
print("  ⇒ 写法:「跨越收盘钟的采样 X/X 全部高于卖价;**放宽到 ±2 分钟则降到 Y%,")
print("     且有 Z% 落在买价之下 —— 该统计在宽窗口下无信息**。」")
print("     光写限定不够,要写去掉限定会变成什么,否则限定看起来像谨慎而不是必需。")
