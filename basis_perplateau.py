#!/usr/bin/env python3
"""按「逐平台判」重算基差符号序列 —— 这才是该用的口径。

本路 7.56 建议「按非缓存口径报」。另一路指出那会**同时扔掉全天 96% 可用的
gate 和 100% 可用的 bitget** —— 因为全天看 bitget 整字典全冻 0%、gate 4%,
它们的长平台通常是上游 mark 真没变,不是回放。

而本路独立核实:16:12:59–16:13:12 那个平台上,gate / bitget / kucoin
**整字典全冻**(见证字段分别 0/14、0/16、0/8 在动),hl / kraken 活着。
**所以两条都对:不该按场所剔,而这个平台确实是回放。**

正确口径:**逐时刻、逐场所判** —— 某场所在某时刻若整字典相对上一条全冻,
则该时刻该场所的报价不参与同时刻配对;否则参与。

见证字段必须全天真的变过,否则常量字段会把「全冻」判成真
(另一路第一版恒真的来源)。
"""
import collections
import io
import json
import os
import statistics

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
VENUES = ["hl_xyz_ANT", "kraken_PF_ANTXUSD",
          "gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"]
LO, HI = "2026-11-19T14:30:00", "2026-11-19T16:48:26"
WIN_LO, WIN_HI = "2026-11-19T15:40:00", "2026-11-19T16:30:00"

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

# ① 全天真的变过的见证字段
vals = {v: collections.defaultdict(set) for v in VENUES}
for ts, d in rows:
    for v in VENUES:
        b = d.get(v)
        if isinstance(b, dict):
            for k, x in b.items():
                if isinstance(x, (int, float, str, bool)) or x is None:
                    vals[v][k].add(repr(x))
WITNESS = {v: sorted(k for k, s in vals[v].items() if len(s) > 1) for v in VENUES}
for v in VENUES:
    print("  %-22s 见证字段 %d 个" % (v, len(WITNESS[v])))

# ② 逐时刻判每个场所是否「整字典相对上一条全冻」
frozen_at = []          # list of (ts, set(frozen venues))
prev = {}
nfroz = collections.Counter()
ntot = collections.Counter()
for ts, d in rows:
    fr = set()
    for v in VENUES:
        b = d.get(v)
        if not isinstance(b, dict):
            continue
        ntot[v] += 1
        sig = tuple(repr(b.get(k)) for k in WITNESS[v])
        if v in prev and prev[v] == sig:
            fr.add(v)
            nfroz[v] += 1
        prev[v] = sig
    frozen_at.append((ts, d, fr))

print()
print("=== 逐时刻「整字典全冻」占比（竞价日全天）===")
print("| 场所 | 样本 | 全冻时刻 | 占比 |")
print("|---|---|---|---|")
for v in VENUES:
    print("| %s | %d | %d | %.1f%% |"
          % (v, ntot[v], nfroz[v], 100.0 * nfroz[v] / max(1, ntot[v])))

# ③ 三种口径下的基差序列
def series(mode):
    out = []
    for ts, d, fr in frozen_at:
        if not (LO <= ts <= HI):
            continue
        sp = d.get("spot_ANT_nasdaq") or {}
        b, a = sp.get("bid"), sp.get("ask")
        if b is None or a is None or sp.get("traded"):
            continue
        if abs(float(b) - float(a)) > 1e-9:
            continue
        use = []
        for v in VENUES:
            blk = d.get(v)
            if not isinstance(blk, dict):
                continue
            m = blk.get("mark")
            if not isinstance(m, (int, float)):
                continue
            if mode == "all5":
                use.append(float(m))
            elif mode == "clean2":
                if v in ("hl_xyz_ANT", "kraken_PF_ANTXUSD"):
                    use.append(float(m))
            elif mode == "perplateau":
                if v not in fr:
                    use.append(float(m))
        if not use:
            continue
        if mode == "all5" and len(use) < 3:
            continue
        pm = statistics.median(use)
        out.append((ts, float(b), pm, pm - float(b), len(use)))
    return out


print()
print("| 口径 | 配对 | 窗口内为正 | 最长连负 | 最后由正转负 | P−I 中位 | 场所数中位 |")
print("|---|---|---|---|---|---|---|")
for mode, label in (("all5", "全五家（≥3，7.x 原口径）"),
                    ("clean2", "只用非缓存两家（7.56 的建议）"),
                    ("perplateau", "**逐平台判（本条的口径）**")):
    s = series(mode)
    if not s:
        print("| %s | 0 | — | — | — | — | — |" % label)
        continue
    win = [x for x in s if WIN_LO <= x[0] <= WIN_HI]
    wpos = sum(1 for x in win if x[3] > 0)
    best = cur = 0
    for x in s:
        cur = cur + 1 if x[3] < 0 else 0
        best = max(best, cur)
    flip = None
    for i in range(1, len(s)):
        if s[i - 1][3] > 0 and s[i][3] < 0:
            flip = s[i][0]
    print("| %s | %d | **%d** | %d | **%s** | %.4f | %.1f |"
          % (label, len(s), wpos, best,
             (flip[11:] + "Z") if flip else "无",
             statistics.median([x[3] for x in s]),
             statistics.median([x[4] for x in s])))

print()
print("=== 那 4 个时刻在逐平台口径下怎么处理的 ===")
pp = {x[0]: x for x in series("perplateau")}
for ts in ("2026-11-19T16:12:59", "2026-11-19T16:13:03",
           "2026-11-19T16:13:07", "2026-11-19T16:13:12"):
    fr = next((f for t, d, f in frozen_at if t == ts), None)
    x = pp.get(ts)
    print("  %sZ  剔除的场所: %s   保留 %s 家  P−I = %s"
          % (ts[11:], sorted(fr) if fr else "—",
             x[4] if x else "—", ("%+.4f" % x[3]) if x else "该时刻无配对"))

print()
print("=== 判读 ===")
print("  逐平台口径既不丢掉 gate/bitget 全天可用的那 96–100%,")
print("  也不把回放时刻当同时刻观测 —— **它是该用的那个口径**。")
print("  若它给出的「最后由正转负」与非缓存两家口径一致,则两条路径互证;")
print("  若不一致,差在哪些时刻上要能逐条列出。")
