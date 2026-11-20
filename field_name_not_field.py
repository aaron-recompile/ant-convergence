#!/usr/bin/env python3
"""核两件:五家 <1% 字段的真实交集,以及「同一个字段名在五家是不同的量」。

本路 7.61.5 写了一张「固定排除名单」:funding / funding_8h / funding_apr /
funding_hrs / via / low24h「在每一家都 <1%」。

**而本路自己的 witness_quality.py 输出里,hl 那一行写的是 `funding 87.7%`,
`<1%` 那组是 `via, funding_hrs, prev_day` —— 不含 funding。**
我在同一段打印之后写下了与它相反的规则。

另一路给的机制:`funding_hrs` 在 hl 是 1(每小时结算)、在 gate/bitget/kucoin 是 8,
而 hl 的 `funding` 是连续重算的累计费率、kucoin 的全天一个值。
⇒ 同一个字段名在不同场所是不同的量。

本脚本:① 逐家 <1% 集合与交集;② funding_hrs 取值;③ funding 的不同取值段数。
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
WLO, WHI = "2026-11-19T14:50:06", "2026-11-19T16:48:21"

allrows, seen = [], set()
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
            allrows.append((ts, d))
allrows.sort(key=lambda x: x[0])
win = [(t, d) for t, d in allrows if WLO <= t <= WHI]


def rates(rows, v):
    prev, nch, ntot = None, collections.Counter(), collections.Counter()
    for ts, d in rows:
        b = d.get(v)
        if not isinstance(b, dict):
            continue
        cur = {k: repr(x) for k, x in b.items()
               if isinstance(x, (int, float, str, bool)) or x is None}
        if prev is not None:
            for k in set(cur) & set(prev):
                ntot[k] += 1
                if cur[k] != prev[k]:
                    nch[k] += 1
        prev = cur
    return {k: 100.0 * nch[k] / ntot[k] for k in ntot if ntot[k] > 0}


print("=== ① 竞价窗口内 <1% 的字段，逐家 ===")
low = {}
for v in VENUES:
    r = rates(win, v)
    low[v] = sorted(k for k, x in r.items() if x < 1.0)
    f = r.get("funding")
    print("  %-22s <1%%: %s" % (v, ", ".join(low[v]) or "无"))
    print("      其中 funding 的变动率 = %s"
          % ("%.1f%%" % f if f is not None else "无该字段"))
inter = set(low[VENUES[0]])
for v in VENUES[1:]:
    inter &= set(low[v])
print()
print("  **五家交集 = %s**" % (sorted(inter) or "空"))
print("  本路 7.61.5 报的名单 = funding, funding_8h, funding_apr, funding_hrs, via, low24h")
wrong = [k for k in ("funding", "funding_8h", "funding_apr", "low24h")
         if k not in inter]
print("  **名单里不属于交集的: %s**" % (", ".join(wrong) or "无"))

print()
print("=== ② funding_hrs 的取值（结算间隔）===")
for v in VENUES:
    vals = collections.Counter()
    for ts, d in allrows:
        b = d.get(v)
        if isinstance(b, dict) and b.get("funding_hrs") is not None:
            vals[b["funding_hrs"]] += 1
    print("  %-22s %s" % (v, dict(vals.most_common(4)) or "无该字段"))

print()
print("=== ③ 全天 funding 的不同取值「段数」（连续相同算一段）===")
print("| 场所 | 样本 | 段数 | 不同取值数 | 全天变动率 |")
print("|---|---|---|---|---|")
rall = {v: rates(allrows, v) for v in VENUES}
for v in VENUES:
    prev, segs, vals, n = None, 0, set(), 0
    for ts, d in allrows:
        b = d.get(v)
        if not isinstance(b, dict) or "funding" not in b:
            continue
        cur = repr(b["funding"])
        n += 1
        vals.add(cur)
        if cur != prev:
            segs += 1
        prev = cur
    fr = rall[v].get("funding")
    print("| %s | %d | **%d** | %d | %s |"
          % (v, n, segs, len(vals),
             "%.1f%%" % fr if fr is not None else "—"))

print()
print("=== 判读 ===")
print("  ① 若交集只有 funding_hrs / via 两个,且它们都是入库时自加的字段,")
print("     则「唯一可无条件排除的是自己添的那两个」成立,本路那张名单要撤。")
print("  ③ 若 hl 的 funding 段数达数千而 kucoin 为 1 ——")
print("     **同一个字段名在两家是不同的量**,变动率是该场所资金费机制的性质,")
print("     不是字段的性质。⇒ 规则只能是「就地算」,不能是名单。")
