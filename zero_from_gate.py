#!/usr/bin/env python3
"""核「0 条」是不是闸门造出来的，以及那道闸门能不能被穿过。

另一路查出 `_spot_nasdaq` 有占位价闸门:

    px=_f(p.get("lastSalePrice"))
    if px is not None and _f(p.get("volume")) in (None,0) and abs(px-83.0)<1e-9:
        px=None
    return {"price":px, ..., "traded":px is not None}

⇒ **「src=nasdaq 占位价 0 条」是「闸门在工作」的证据,不是「端点不这么干」的证据。**
⇒ **本路 7.69.1 据那个 0 断言「README 把源写错了」—— 那一步要收窄。**

它的判别入口值得抄下来:**「0 条」这个观测,在「没发生」和「被挡住」两种世界里完全一样。**

本脚本四件:
  ① 自己读 collector.py 里 _spot_nasdaq 的那道闸门
  ② src=nasdaq ∧ price=None 的块数与它们的 vol —— 闸门开火次数的上界
  ③ 闸门能不能被穿过:有没有 price==83.0 而 volume 非零的记录(任何源)
  ④ nasdaq 块里 traded=True 而 last_trade_ts 非 Nov 19 的 —— 另一路报 0
"""
import collections
import io
import json
import os
import re

HERE = os.path.expanduser("~/ant-convergence")
D = os.path.join(HERE, "data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

print("════════ ① 自己读那道闸门 ════════")
col = os.path.join(HERE, "collector.py")
src = io.open(col, encoding="utf-8", errors="replace").read()
lines = src.split("\n")
i = next((k for k, l in enumerate(lines) if "def _spot_nasdaq" in l), None)
if i is None:
    print("  未找到 _spot_nasdaq")
else:
    for k in range(i, min(i + 30, len(lines))):
        l = lines[k]
        mark = ""
        if "83.0" in l or "volume" in l and "None" in l:
            mark = "   **← 闸门**"
        print("  L%-5d %s%s" % (k + 1, l.rstrip()[:96], mark))
        if "return {" in l:
            break

FILES = [(os.path.join(D, "ant_2026-11-19.jsonl"), "ant_"),
         (os.path.join(D, "binance_2026-11-19.jsonl"), "binance_"),
         (os.path.join(RESC, "rescued_ant_2026-11-19.jsonl"), "rescue")]
rows, seen = [], set()
for p, tag in FILES:
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
        sp = d.get("spot_ANT_nasdaq")
        if ts.startswith("2026-11-19") and isinstance(sp, dict):
            rows.append((ts, tag, sp))
rows.sort(key=lambda x: x[0])

print()
print("════════ ② 闸门开火次数的上界 ════════")
cand = [(ts, sp) for ts, _, sp in rows
        if sp.get("src") == "nasdaq" and sp.get("price") is None]
print("  src=nasdaq ∧ price=None : **%d** 个（另一路报 3,322）" % len(cand))
vols = collections.Counter()
for ts, sp in cand:
    v = sp.get("vol")
    vols["vol=0/None" if (v in (None, 0) or v == 0.0) else "vol 非零"] += 1
print("  其中 vol 分布: %s" % dict(vols))
if cand:
    print("  时间范围: %sZ – %sZ" % (cand[0][0][11:], cand[-1][0][11:]))
print()
print("  **⇒ 开火次数上界 %d、下界 0,真值不可知** —— 原值被 px=None 丢弃,没有留痕。"
      % len(cand))

print()
print("════════ ③ 闸门能不能被穿过:price==83.0 而 volume 非零 ════════")
thru = []
for ts, tag, sp in rows:
    p = sp.get("price")
    if isinstance(p, (int, float)) and abs(float(p) - 83.0) < 1e-9:
        v = sp.get("vol")
        if v not in (None, 0) and v != 0.0:
            thru.append((ts, tag, sp.get("src"), v))
print("  price==83.0 且 vol 非零: **%d** 条" % len(thru))
for ts, tag, s, v in thru[:6]:
    print("     %sZ [%s] src=%s vol=%s" % (ts[11:], tag, s, v))
if not thru:
    print("  **11-19 未发生 ⇒ 与另一路一致。但条件含 `volume in (None,0)`,")
    print("    所以带非零成交量的占位价**结构上可以穿过** —— 这是一条未触发的敞口。**")

print()
print("════════ ④ nasdaq 块 traded=True 而 last_trade_ts 非 Nov 19 ════════")
bad = []
for ts, tag, sp in rows:
    if sp.get("src") != "nasdaq" or not sp.get("traded"):
        continue
    v = sp.get("last_trade_ts")
    if not v:
        continue
    if not re.search(r"Nov\s+19", str(v)):
        bad.append((ts, tag, v))
print("  命中: **%d** 条（另一路报 0）" % len(bad))
for ts, tag, v in bad[:5]:
    print("     %sZ [%s] %r" % (ts[11:], tag, v))

print()
print("════════ 判读 ════════")
print("  ② 若上界远大于 0 ⇒ 本路 7.69.1 那句「源写错了」要收窄为")
print("     「前半句(端点行为)对,后半句的 45 条指落盘记录」。")
print("  ③ 若为 0 ⇒ 敞口存在但未触发,该登记为「未触发的敞口」而不是「不存在」。")
print("  **而这两条合起来就是另一路那句:凡结论依赖某个计数为 0,")
print("    必须问那个 0 是不是某道闸门造出来的。**")
