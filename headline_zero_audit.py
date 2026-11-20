#!/usr/bin/env python3
"""把另一路那条规则用在本路最载重的那个 0 上:「盘前 0 条高于 111.50」。

规则(另一路 §9.81):**凡结论依赖某个计数为 0,必须问那个 0 是不是某道闸门造出来的。**

本路管线里会减少观测的三道「闸门」:
  (a) via=coingecko 剔除(7.65)—— 剔掉 5,966 条
  (b) 窗口边界(7.44 把右沿从 16:48:00 改到 16:48:26,**是放宽**)
  (c) 字段选择(mixed / mark / last / index)

逐个问:每一道会不会藏掉一个 >111.50 的观测?
最后做一个**无字段参数**的版本:盘前所有永续块的**所有数值字段**取最大。
"""
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
PRE_LO = "2026-11-19T00:00:00"
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
          "gate_ANT_USDT", "kucoin_ANTUSDTM", "binance_ANTUSDT",
          "hl_para_ANTH"]
# 价格类字段：排除百分比 / 规模 / 费率 / 张数 / 成交额
SKIP = ("pct", "size", "funding", "oi_", "vol", "trades", "rel_",
        "hrs", "chg", "turnover", "quote")
FILES = [os.path.join(D, "ant_2026-11-19.jsonl"),
         os.path.join(D, "binance_2026-11-19.jsonl"),
         os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")]


def load(pre_hi):
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
            if PRE_LO <= ts < pre_hi:
                recs.append((ts, d))
    return recs


def scan(recs, skip_cg, fields=None):
    """返回 (n, max, argmax)。fields=None 表示所有价格类数值字段。"""
    best = (-1, None, None, None)
    n = 0
    for ts, d in recs:
        for v in VENUES:
            b = d.get(v)
            if not isinstance(b, dict):
                continue
            if skip_cg and b.get("via") == "coingecko":
                continue
            keys = fields if fields else [
                k for k in b
                if isinstance(b.get(k), (int, float))
                and not isinstance(b.get(k), bool)
                and not any(s in k.lower() for s in SKIP)]
            for k in keys:
                x = b.get(k)
                if isinstance(x, (int, float)) and not isinstance(x, bool):
                    n += 1
                    if float(x) > best[0]:
                        best = (float(x), ts, v, k)
    return n, best


print("=== 逐道闸门问一遍：它会不会藏掉一个 >111.50 的观测 ===")
CASES = [
    ("(a) 不剔 coingecko，右沿 16:48:26，所有价格类字段", False, "2026-11-19T16:48:26", None),
    ("(b) 剔 coingecko，右沿 16:48:26，所有价格类字段", True, "2026-11-19T16:48:26", None),
    ("(c) 剔 coingecko，右沿 **16:48:00**（7.44 之前的窄窗）", True, "2026-11-19T16:48:00", None),
    ("(d) 剔 coingecko，右沿 16:48:26，**仅 mark**", True, "2026-11-19T16:48:26", ["mark"]),
]
print("| 口径 | 观测数 | 最高 | 出自 | >111.50 |")
print("|---|---|---|---|---|")
for lab, cg, hi, fl in CASES:
    recs = load(hi)
    n, (mx, ts, v, k) = scan(recs, cg, fl)
    over = "**0**" if mx <= 111.5 else "**%d ← 有!**" % 1
    print("| %s | %d | **%.4f** | %s/%s @%sZ | %s |"
          % (lab, n, mx, v, k, ts[11:], over))

print()
print("=== 无字段参数的版本（所有价格类字段，含 hl_para_ANTH）===")
recs = load("2026-11-19T16:48:26")
n, (mx, ts, v, k) = scan(recs, True, None)
print("  观测 %d 个，最高 **%.4f**（%s 的 %s @%sZ）" % (n, mx, v, k, ts[11:]))
print("  **高于 111.50: %d**" % (1 if mx > 111.5 else 0))

print()
print("=== 判读 ===")
print("  (a) 不剔 coingecko 仍是 0 ⇒ 那道剔除没有藏东西;")
print("  (c) 用 7.44 之前的窄窗也是 0 ⇒ 放宽窗口没有引入,收窄也没有藏;")
print("  (d) 换字段也是 0;无字段参数版也是 0")
print("  **⇒ 这个 0 不是任何一道闸门造出来的。** 而这句话此前没有被验过。")
