#!/usr/bin/env python3
"""按变动率筛见证字段，重验 7.58 那 4 个时刻。

另一路指出本路 7.60 的对照组退化:hl 的 vol24h_usd / oi_contracts 变动率 100.0%、
kraken 的 index 100.0% ⇒「全字段一字未变」在那两家结构上不可能 ⇒ 0/425 恒假。
那是它 52% 恒真的镜像。**本路 7.60 的结论因此不成立,必须撤。**

**但同一个病对本路 7.58 的方向相反而且更要紧:**
对缓存源,把**低变动率**字段放进「全部不变」的合取里,会让判据**更容易成立** ——
所以 7.58 报的「gate 0/14、bitget 0/16、kucoin 0/8 字段在动」可能是被注水的。

本脚本:
  ① 逐场所逐字段算竞价窗口变动率
  ② 只用**高变动率**字段(缓存源接近其最大值的那些)重验那 4 个时刻
  ③ 给本路此前几张表补上见证字段的变动率
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
CACHED = {"gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"}
LO, HI = "2026-11-19T14:50:06", "2026-11-19T16:48:21"
PLAT_LO, PLAT_HI = "2026-11-19T16:12:59", "2026-11-19T16:13:12"

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
        if LO <= ts <= HI:
            rows.append((ts, d))
rows.sort(key=lambda x: x[0])
print("竞价窗口 %s–%s，记录 %d 条" % (LO[11:], HI[11:], len(rows)))

# ① 逐字段变动率
rate = {}
for v in VENUES:
    prev, nch, ntot = None, collections.Counter(), collections.Counter()
    keys = set()
    for ts, d in rows:
        b = d.get(v)
        if not isinstance(b, dict):
            continue
        cur = {k: repr(x) for k, x in b.items()
               if isinstance(x, (int, float, str, bool)) or x is None}
        keys |= set(cur)
        if prev is not None:
            for k in keys:
                if k in cur and k in prev:
                    ntot[k] += 1
                    if cur[k] != prev[k]:
                        nch[k] += 1
        prev = cur
    rate[v] = {k: 100.0 * nch[k] / ntot[k] for k in ntot if ntot[k] > 0}

print()
print("=== ① 各场所字段变动率（降序，前 6）===")
for v in VENUES:
    top = sorted(rate[v].items(), key=lambda kv: -kv[1])[:6]
    tag = "〔缓存〕" if v in CACHED else "〔直取〕"
    print("  %-22s%s %s" % (v, tag,
                            ", ".join("%s %.1f%%" % (k, r) for k, r in top)))
    z = [k for k, r in rate[v].items() if r < 1.0]
    print("      变动率 <1%% 的字段（当见证几乎无力）: %s" % (", ".join(z) or "无"))

print()
print("=== ② 只用高变动率字段重验那 4 个时刻 ===")
seg = [(ts, d) for ts, d in rows if PLAT_LO <= ts <= PLAT_HI]
print("  平台 %s–%s，记录 %d 条" % (PLAT_LO[11:], PLAT_HI[11:], len(seg)))
print()
print("| 场所 | 阈值 | 入选见证字段 | 动了 | 冻住 | 结论 |")
print("|---|---|---|---|---|---|")
for v in VENUES:
    mx = max(rate[v].values()) if rate[v] else 0
    # 缓存源最大变动率约 26.7%：取其 80% 作阈值，确保只用「本该经常变」的字段
    thr = 0.8 * mx
    wit = sorted(k for k, r in rate[v].items() if r >= thr)
    obs = [d.get(v) for ts, d in seg if isinstance(d.get(v), dict)]
    if len(obs) < 2 or not wit:
        print("| %s | — | — | — | — | 样本/字段不足 |" % v)
        continue
    moved = [k for k in wit
             if len({repr(b.get(k)) for b in obs}) > 1]
    frozen = [k for k in wit if k not in moved]
    verdict = ("**全冻 ⇒ 回放**" if not moved
               else "有字段在动 ⇒ 非回放")
    print("| %s%s | ≥%.1f%% | %d (%s) | %d | %d | %s |"
          % (v, "〔缓存〕" if v in CACHED else "〔直取〕", thr,
             len(wit), ",".join(wit[:4]) + ("…" if len(wit) > 4 else ""),
             len(moved), len(frozen), verdict))

print()
print("=== ③ 给 7.58 那张表补变动率 ===")
print("| 场所 | 7.58 报的见证字段数 | 其中变动率 ≥20% | 10–20% | <10% | <1% |")
print("|---|---|---|---|---|---|")
for v in VENUES:
    r = rate[v]
    allw = [k for k, x in r.items() if True]
    hi20 = sum(1 for k in allw if r[k] >= 20)
    m = sum(1 for k in allw if 10 <= r[k] < 20)
    lo10 = sum(1 for k in allw if 1 <= r[k] < 10)
    lo1 = sum(1 for k in allw if r[k] < 1)
    print("| %s | %d | **%d** | %d | %d | **%d** |"
          % (v, len(allw), hi20, m, lo10, lo1))

print()
print("=== 判读 ===")
print("  ② 若缓存三家在**高变动率字段**上仍然全冻 ⇒ 7.58 的回放结论不是注水的;")
print("     若有高变动率字段在动 ⇒ 7.58 的「0/14、0/16、0/8」被低变动率字段注了水,")
print("     那 4 个时刻的回放判定要重做。")
print("  ③ 「12 个字段全冻」与「7 个字段全冻」不是同一强度 —— 要带变动率看。")
