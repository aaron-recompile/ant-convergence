#!/usr/bin/env python3
"""独立算第三遍「盘前永续从未高过撮合价」,并做阈值敏感性。

另一路报:盘前 7,837 个观测里 0 个高于 111.50,中位偏离 −7.07%…−7.09%,
六家无一例外 0%,且与 index 喂价构造无关。

**本路要加的一件:那个 0% 挂在阈值 111.50 上,而 111.50 的出处是「最后一个指示价」。**
本路 7.9 已登记:公开端点不区分 NOCP 与最后一笔合并成交价,
**「实现清算价」这个数本路无法从数据确立** —— 我当时就提醒过他别把它写成结论。
所以这里做阈值敏感性:在几个有据可查的候选阈值下,那个 0% 还成立吗?

候选阈值(每个都注明出处):
  111.50  最后一个指示价（本路 event_source_union 实测，16:48:21Z）
  111.13  yahoo 首个真实分钟 bar 的收盘（本路 7.17 实测，16:48:00Z）
  97.17   当日官方收盘价（本路 7.9 定稿，三源一致）
  115.10  当日最高价（nasdaq info keyStats 实测）

并集含 binance 文件(它也带永续)与抢救档 —— 按 7.39 那条,不按文件名猜内容。
冲突标记逐行跳过。
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
import io
import json
import os
import statistics

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
PRE_LO, PRE_HI = "2026-11-19T00:00:00", "2026-11-19T16:48:00"   # 盘前 = 首笔成交之前
PERPS = {
    "hl_xyz_ANT": "mid",
    "kraken_PF_ANTXUSD": "last",
    "bitget_ANTUSDT": "last",
    "gate_ANT_USDT": "last",
    "kucoin_ANTUSDTM": "last",
    "binance_ANTUSDT": "last",
}
THRESHOLDS = [
    (111.50, "最后一个指示价（16:48:21Z，本路实测）"),
    (111.13, "yahoo 首个真实分钟收盘（16:48:00Z，7.17）"),
    (115.10, "当日最高价（nasdaq keyStats）"),
    (97.17, "当日官方收盘价（7.9 定稿，三源一致）"),
]
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")

FILES = [os.path.join(D, "ant_2026-11-19.jsonl"),
         os.path.join(D, "binance_2026-11-19.jsonl"),
         os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")]

obs = {v: [] for v in PERPS}
seen = set()
nmark = 0
for p in FILES:
    if not os.path.exists(p):
        continue
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        if any(ln.startswith(x) for x in CONFLICT):
            nmark += 1
            continue
        if ln in seen:
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts_utc") or "")[:19]
        if not (PRE_LO <= ts < PRE_HI):
            continue
        for v, f in PERPS.items():
            blk = d.get(v)
            if not isinstance(blk, dict):
                continue
            x = blk.get(f)
            if x is None:
                x = blk.get("mark")
            if isinstance(x, (int, float)):
                obs[v].append((ts, float(x)))

print("盘前窗口 %s – %s（首笔成交 16:48:00Z 之前）；跳过冲突标记 %d 行"
      % (PRE_LO[11:], PRE_HI[11:], nmark))
print("并集含 ant / binance / 抢救档 —— 按 7.39，不按文件名猜内容")
print()
print("=== ① 逐场所观测数与盘前最高 ===")
print("| 场所 | 字段 | n | 盘前最高 |")
print("|---|---|---|---|")
tot = 0
for v, f in PERPS.items():
    if not obs[v]:
        print("| %s | %s | 0 | — |" % (v, f))
        continue
    tot += len(obs[v])
    print("| %s | %s | %d | %.4f |"
          % (v, f, len(obs[v]), max(x for _, x in obs[v])))
print("| **合计** | | **%d** | |" % tot)
print("  （另一路报 7,837；两边口径差见下）")

print()
print("=== ② 阈值敏感性:那个 0% 在哪些阈值下成立 ===")
print("| 阈值 | 出处 | 高于它的观测数 | 占比 |")
print("|---|---|---|---|")
allv = [x for v in PERPS for _, x in obs[v]]
for th, src in THRESHOLDS:
    k = sum(1 for x in allv if x > th)
    print("| **%.2f** | %s | **%d** | %.2f%% |"
          % (th, src, k, 100.0 * k / len(allv) if allv else 0))

print()
print("=== ③ 中位偏离（相对各阈值）===")
med = statistics.median(allv)
print("  盘前永续中位 = %.4f" % med)
for th, src in THRESHOLDS:
    print("  相对 %.2f：%+.2f%%   （%s）" % (th, 100.0 * (med / th - 1), src))

print()
print("=== ④ 本路的提醒(7.9 已登记) ===")
print("  「实现清算价」本路无法从数据确立：公开端点不区分 NOCP 与最后一笔合并成交价，")
print("  historical 端点当时 totalRecords=0。111.50 的身份是**最后一个指示价**，")
print("  不是独立确立的撮合价。**头号数字若写成「从未高过撮合价」，")
print("  它依赖的是一个本路标注为未确立的量。**")
print("  若改写成「从未高过最后一个指示价 111.50」—— 那是可独立复核的。")
