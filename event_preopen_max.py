#!/usr/bin/env python3
"""按第六问算「无参数」的盘前最大值 —— 并指出 max 去掉了阈值参数但没去掉字段参数。

另一路把头号那句改成:
  「盘前 50,009 个跨场所观测的最大值 $111.4650(kraken,16:48:18Z),比最后一个指示价低 3.5 分」
无阈值 ⇒ 对 0-vs-53 那个脆弱点免疫,也对 111.50 的身份争议免疫。**这一步是对的。**

**但 max 仍带一个参数:字段选择。** 他六家全用 `mark` 得 111.4650;
本路逐家不同字段(HL 用 `mid`)得 kraken `last` 111.3100。
**同一个「最大值」在两个字段口径下不同 ⇒ 它还不是无参数的。**

真正无参数的版本:**对所有场所 × 所有价格字段取最大**。本脚本算这个。
"""
# ╭───────────────────────────────────────────────────────────────────────────╮
# │ 口径声明（7.56，2026-11-20 加）                                          │
# │                                                                           │
# │ 本脚本用到的永续场所里，**bitget_ANTUSDT / gate_ANT_USDT /               │
# │ kucoin_ANTUSDTM 走 `_throttled` 缓存** —— 命中时返回上一次取数的值。      │
# │ 本路实测 11-19 竞价窗口的冻结平台（同一个 mark 连续不变多久）：          │
# │     缓存三家  中位 18s / p90 20s / 最大 103s / 仅 ~24% 样本在变           │
# │     hl + kraken  中位 5s（= 采样间隔）/ 79–92% 样本在变                   │
# │                                                                           │
# │ ⇒ **任何「同时刻配对」的结论都不能直接用这三家。** 实测后果：            │
# │   15:40–16:30Z 的「P−I 为正 4 次」在剔掉缓存源后变 0；                    │
# │   「最后由正转负 16:13:15Z」是一次缓存刷新，非缓存口径下是 16:41:49Z。    │
# │                                                                           │
# │ ⇒ **阈值穿越类结论不受影响**（已实测）：陈旧报价仍是窗口内真实存在过的   │
# │   报价，不要求同时刻配对。但**计数会随参与场所集合变** ——                │
# │   高于 111.13 的观测数 67（全六家）vs 26（非缓存两家）。                  │
# │                                                                           │
# │ `spot_ANT_nasdaq` **不走缓存**，指示价序列不受此影响。                    │
# ╰───────────────────────────────────────────────────────────────────────────╯
# ╭───────────────────────────────────────────────────────────────────────────╮
# │ 口径声明追加（7.65，2026-11-20）：采纳另一路第 9 节的 R5                 │
# │                                                                           │
# │ **`ant_*.jsonl` 里 `via=coingecko` 的永续块一律不用。**                   │
# │ 成因（另一路查其采集代码）：`binance_via_coingecko()` 里                  │
# │     r = {"last": x.get("last"), "mark": x.get("last"), ...}               │
# │ ⇒ 该路径的 `mark` 是 `last` 的副本，不是任何标记价；且另有一层 5 秒       │
# │   `_cg_last` 缓存，与 `_throttled` 的 15 秒是两层独立节流。               │
# │ 11-19 mini 上 `ant_*` 的币安 14,978 条全是这一路（socks 仅活 41 分钟）。  │
# │                                                                           │
# │ **本路此前未应用此规则**：7.56.7 写的「本路本就按 R5 排除」是错的 ——      │
# │ 本路第 7 节的 R5 是 `bar_ts % 60 == 0`（yahoo 半成品 bar），与币安无关；  │
# │ 我引的是另一路的 R5，而本路既无该规则也无该过滤。                        │
# │ 实测影响：盘前观测 50,710 → **44,744**（剔除 5,966 条，11.76%）。         │
# │ **结论不变**：高于 111.50 仍为 0、最高仍 111.4300（kraken 直取）、        │
# │ 高于 111.13 仍为 **67** 条（那 67 条全不是 coingecko）——只有 n 与占比变。│
# ╰───────────────────────────────────────────────────────────────────────────╯

import io
import json
import os

def _r5_usable(blk):
    """R5（另一路第 9 节）：via=coingecko 的永续块一律不用。见本文件头部口径声明。"""
    return not (isinstance(blk, dict) and blk.get("via") == "coingecko")


D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
PRE_LO, PRE_HI = "2026-11-19T00:00:00", "2026-11-19T16:48:26"   # 7.44 更正：首笔成交落在 (16:48:21Z, 16:48:26Z]；
                                     # 此前用的是 yahoo 分钟 bar 的**标签** 16:48:00Z
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
          "gate_ANT_USDT", "kucoin_ANTUSDTM", "binance_ANTUSDT"]
FIELDS = ["mark", "last", "mid", "index"]
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
FILES = [os.path.join(D, "ant_2026-11-19.jsonl"),
         os.path.join(D, "binance_2026-11-19.jsonl"),
         os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")]
IND_LAST = 111.50      # 最后一个指示价（本路实测 16:48:21Z）

best = {}      # (venue, field) -> (value, ts)
n = {}
seen = set()
for p in FILES:
    if not os.path.exists(p):
        continue
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or any(ln.startswith(x) for x in CONFLICT) or ln in seen:
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if not (PRE_LO <= ts < PRE_HI):
            continue
        for v in VENUES:
            blk = d.get(v)
            if not _r5_usable(blk):   # R5，见头部声明
                continue
            if not isinstance(blk, dict):
                continue
            for f in FIELDS:
                x = blk.get(f)
                if not isinstance(x, (int, float)):
                    continue
                k = (v, f)
                n[k] = n.get(k, 0) + 1
                if k not in best or x > best[k][0]:
                    best[k] = (float(x), ts)

print("盘前窗口 %s – %s（首笔成交之前）" % (PRE_LO[11:], PRE_HI[11:]))
print()
print("=== 每个（场所,字段）的盘前最大值 ===")
print("| 场所 | 字段 | n | 盘前最大 | 时刻 | 距 111.50 |")
print("|---|---|---|---|---|---|")
for (v, f), (x, ts) in sorted(best.items(), key=lambda kv: -kv[1][0]):
    print("| %s | %s | %d | **%.4f** | %sZ | %+.4f |"
          % (v.split("_")[0], f, n[(v, f)], x, ts[11:], x - IND_LAST))

gv, gf = max(best, key=lambda k: best[k][0])
gx, gts = best[(gv, gf)]
print()
print("=== 真正无参数的那个数:全场所 × 全字段的最大 ===")
print("  **%.4f**  （%s 的 %s，%sZ）" % (gx, gv, gf, gts[11:]))
print("  距最后一个指示价 111.50：**%+.4f 美元 = %+.2f 分**" % (gx - IND_LAST, (gx - IND_LAST) * 100))
print()
print("=== 对照:只看某一个字段口径时的最大 ===")
for f in FIELDS:
    sub = {k: v for k, v in best.items() if k[1] == f}
    if not sub:
        continue
    k = max(sub, key=lambda kk: sub[kk][0])
    print("  六家全用 %-6s → %.4f（%s，%sZ）"
          % (f, sub[k][0], k[0].split("_")[0], sub[k][1][11:]))
print()
print("判读:若「六家全用 mark」与「全场所全字段」给出不同的最大值,")
print("      那么 max 虽然去掉了阈值参数,**仍带一个字段参数** ——")
print("      无参数的版本必须对字段也取最大。")
