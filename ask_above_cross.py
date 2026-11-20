#!/usr/bin/env python3
"""核那个 111.5300 的卖价:它是真的高于 111.50 吗，有多少条，是哪一侧?

本路 headline_zero_audit 的无字段参数版查出:盘前最高价格类字段是
**kraken_PF_ANTXUSD / ask = 111.5300 @16:48:09Z** —— **高于 111.50**。

若成立,则头号结论「盘前无一高于 111.50」**对成交/标记/指数口径成立,
对卖价一侧不成立** —— 有人在撮合价之上挂过卖单。那是个不同的陈述,
而且比「没有成交高过」更有意思。

同时修掉本路脚本的那个 bug:SKIP 名单漏了 `last_traded`(epoch 字段)。

本脚本:
  ① 那条记录全文
  ② 逐字段:盘前有多少条 > 111.50，分别是什么字段
  ③ bid 一侧有没有超过
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
          "gate_ANT_USDT", "kucoin_ANTUSDTM", "binance_ANTUSDT",
          "hl_para_ANTH"]
# 只认价格类字段：显式白名单，不再用子串排除（上一版漏了 last_traded）
PRICE_KEYS = {"mark", "last", "mid", "index", "bid", "ask",
              "high24h", "low24h", "open24h", "prev_day", "prev_close",
              "mark_price", "last_price", "vwap24h"}
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

print("=== ① 16:48:09Z 的 kraken 块全文 ===")
for ts, d in recs:
    if ts == "2026-11-19T16:48:09":
        b = d.get("kraken_PF_ANTXUSD")
        if isinstance(b, dict):
            print("  " + json.dumps(b, ensure_ascii=False, sort_keys=True)[:420])
            print("  bid=%s  ask=%s  mark=%s  index=%s  last=%s"
                  % (b.get("bid"), b.get("ask"), b.get("mark"),
                     b.get("index"), b.get("last")))
            break

print()
print("=== ② 盘前逐字段:有多少条 > 111.50（白名单字段，剔 coingecko）===")
over = collections.Counter()
tot = collections.Counter()
examples = collections.defaultdict(list)
for ts, d in recs:
    for v in VENUES:
        b = d.get(v)
        if not isinstance(b, dict) or b.get("via") == "coingecko":
            continue
        for k in PRICE_KEYS:
            x = b.get(k)
            if isinstance(x, (int, float)) and not isinstance(x, bool):
                tot[(v, k)] += 1
                if float(x) > 111.5:
                    over[(v, k)] += 1
                    if len(examples[(v, k)]) < 3:
                        examples[(v, k)].append((ts, float(x)))
print("  | 场所/字段 | 观测 | **> 111.50** | 例 |")
print("  |---|---|---|---|")
any_over = False
for key in sorted(tot, key=lambda k: -over[k]):
    if over[key] == 0:
        continue
    any_over = True
    v, k = key
    print("  | %s / **%s** | %d | **%d** | %s |"
          % (v, k, tot[key], over[key],
             ", ".join("%.4f@%sZ" % (x, t[11:]) for t, x in examples[key])))
if not any_over:
    print("  | 无任何字段超过 | | **0** | |")

print()
print("=== ③ 成交/标记/指数口径 vs 盘口口径 ===")
TRADE_LIKE = ("mark", "last", "mid", "index")
BOOK = ("bid", "ask")
for label, keys in (("成交/标记/指数(mark/last/mid/index)", TRADE_LIKE),
                    ("盘口(bid/ask)", BOOK)):
    n = sum(tot[(v, k)] for v in VENUES for k in keys if (v, k) in tot)
    o = sum(over[(v, k)] for v in VENUES for k in keys if (v, k) in over)
    mx = -1
    arg = None
    for ts, d in recs:
        for v in VENUES:
            b = d.get(v)
            if not isinstance(b, dict) or b.get("via") == "coingecko":
                continue
            for k in keys:
                x = b.get(k)
                if isinstance(x, (int, float)) and not isinstance(x, bool) and float(x) > mx:
                    mx, arg = float(x), (ts, v, k)
    print("  %-38s n=%-7d >111.50 = **%d**   最高 %.4f (%s/%s @%sZ)"
          % (label, n, o, mx, arg[1], arg[2], arg[0][11:]))

print()
print("=== 判读 ===")
print("  若「成交/标记/指数」口径为 0 而「盘口」口径非 0 ⇒")
print("  **头号结论要加口径:无一成交/标记/指数高于 111.50;而卖价一侧有。**")
print("  那是个不同且更有意思的陈述:有人在撮合价之上挂过卖单,但没人在那里成交。")
