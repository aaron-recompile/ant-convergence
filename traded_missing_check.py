#!/usr/bin/env python3
"""【要紧】指示价判据里「没有 traded 键」被当成了「没有成交」吗?

本路的指示价判据(全程使用,产出 1,523 个时刻 / 85–86 个档位 / 127–128 次变动):

    b, a = sp.get("bid"), sp.get("ask")
    if b is None or a is None or sp.get("traded"): continue
    if abs(b - a) > 1e-9: continue
    → 记为指示价

`sp.get("traded")` 在键**不存在**时返回 None,而 None 是假值
⇒ **「没有 traded 键」与「traded == False」被同等对待。**

而普查实测:`spot_ANT_nasdaq` 块里 `traded` 只在 35.586% 出现、
`bid`/`ask` 在 31.735% 出现。**若 traded 组不是 bid/ask 组的超集,
就有「bid==ask 而无 traded 键」的块被当成指示价。**

本脚本:
  ① bid/ask 都在的块里,traded 键在不在
  ② 其中 bid==ask 的块里,traded 键在不在 —— 这才是判据实际触及的集合
  ③ 若有「bid==ask 且无 traded 键」的块,列出来并算它们对 1,523 的影响
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
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
        if LO <= ts <= HI:
            recs.append((ts, d))
recs.sort(key=lambda x: x[0])

n_blk = n_ba = n_ba_traded_key = n_eq = n_eq_traded_key = 0
eq_no_key = []
for ts, d in recs:
    sp = d.get("spot_ANT_nasdaq")
    if not isinstance(sp, dict):
        continue
    n_blk += 1
    b, a = sp.get("bid"), sp.get("ask")
    if b is None or a is None:
        continue
    n_ba += 1
    has_key = "traded" in sp
    if has_key:
        n_ba_traded_key += 1
    if abs(float(b) - float(a)) > 1e-9:
        continue
    n_eq += 1
    if has_key:
        n_eq_traded_key += 1
    else:
        eq_no_key.append((ts, float(b), sorted(sp.keys())))

print("指示价窗口 %s–%s   spot_ANT_nasdaq 块 %d 个" % (LO[11:], HI[11:], n_blk))
print()
print("=== ① bid/ask 都在的块 ===")
print("  %d 个，其中有 `traded` 键的 **%d**（%.3f%%）"
      % (n_ba, n_ba_traded_key, 100.0 * n_ba_traded_key / max(1, n_ba)))
print("  缺 `traded` 键的: **%d**" % (n_ba - n_ba_traded_key))
print()
print("=== ② 其中 bid == ask 的块（判据实际触及的集合）===")
print("  %d 个，其中有 `traded` 键的 **%d**（%.3f%%）"
      % (n_eq, n_eq_traded_key, 100.0 * n_eq_traded_key / max(1, n_eq)))
print("  **bid==ask 而缺 `traded` 键的: %d**" % len(eq_no_key))
print()
if eq_no_key:
    print("=== ③ 那些块（被判据当成了指示价，而无证据说明未成交）===")
    for ts, v, ks in eq_no_key[:10]:
        print("  %sZ  bid==ask=%.4f   该块的键: %s" % (ts[11:], v, ", ".join(ks)))
    print()
    print("  **⇒ 这 %d 条进了 1,523,而它们没有 `traded` 证据。**" % len(eq_no_key))
    print("     占 1,523 的 %.2f%%" % (100.0 * len(eq_no_key) / 1523))
else:
    print("=== ③ 无 ===")
    print("  **bid==ask 的块全部带 `traded` 键 ⇒ 判据没有把「缺键」当「未成交」。**")
    print("  `traded` 组(35.586%)是 `bid`/`ask` 组(31.735%)的超集,")
    print("  所以那个写法在这批数据上恰好无害 —— **但它是恰好,不是设计。**")

print()
print("=== 不论结果，该改的写法 ===")
print("  现在:  if b is None or a is None or sp.get(\"traded\"): continue")
print("  应为:  if b is None or a is None or \"traded\" not in sp \\")
print("             or sp[\"traded\"]: continue")
print("  **把「缺键」判成「不可用」而不是「未成交」** —— 缺键是无证据,不是反证。")
