#!/usr/bin/env python3
"""核左沿 14:50:06Z 的「此前没有指示价」从哪一刻起才成立。

另一路指出:
  - `src` 是形状判别器,`bid`/`ask` 只出现在 `src=nasdaq`;
  - `src` 当天约 14:34Z 才上线,之前是第五种形状(无 bid 键、无 traded);
  - 14:34–14:50:06 有 298 个 src=nasdaq 块、带 bid 键但全为 null
    ⇒ 那 16 分钟确实没有指示价,左沿是市场定的;
  - **而 14:30–14:34Z 约 4 分钟本路没有这个能力 ⇒ 不能断言。**

指示价序列是本路的交付物,这条限定该本路自己验。
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
SRCS = [(os.path.join(D, "ant_2026-11-19.jsonl"), "ant_(mini)"),
        (os.path.join(D, "binance_2026-11-19.jsonl"), "binance_(MacBook)"),
        (os.path.join(RESC, "rescued_ant_2026-11-19.jsonl"), "抢救档")]

rows, seen = [], set()
for p, tag in SRCS:
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
        if ts.startswith("2026-11-19"):
            rows.append((ts, d, tag))
rows.sort(key=lambda x: x[0])

blocks = [(ts, d["spot_ANT_nasdaq"], tag) for ts, d, tag in rows
          if isinstance(d.get("spot_ANT_nasdaq"), dict)]
print("全天 spot_ANT_nasdaq 块 %d 个" % len(blocks))

print()
print("=== ① src 的分布，以及 bid/ask 是否只在 src=nasdaq ===")
by_src = collections.Counter()
shapes = collections.defaultdict(set)
ba_by_src = collections.Counter()
for ts, sp, tag in blocks:
    s = sp.get("src") or "(无 src 键)"
    by_src[s] += 1
    shapes[s].add(tuple(sorted(sp.keys())))
    if "bid" in sp:
        ba_by_src[s] += 1
print("  | src | 块数 | 键集合种数 | 带 bid 键 |")
print("  |---|---|---|---|")
for s, n in by_src.most_common():
    print("  | %s | %d | %d | %d |" % (s, n, len(shapes[s]), ba_by_src[s]))
only_nasdaq = all(s == "nasdaq" for s in ba_by_src if ba_by_src[s] > 0)
print("  **bid 键只在 src=nasdaq: %s**" % ("是" if only_nasdaq else "否"))

print()
print("=== ② src 是什么时候上线的（按来源文件分开）===")
print("  | 来源 | 无 src 的时间范围 | src=nasdaq 的起始 |")
print("  |---|---|---|")
for _, tag in SRCS:
    nos = [ts for ts, sp, t in blocks if t == tag and not sp.get("src")]
    nas = [ts for ts, sp, t in blocks if t == tag and sp.get("src") == "nasdaq"]
    print("  | %s | %s（%d 条） | %s（%d 条） |"
          % (tag,
             ("%s → %s" % (nos[0][11:], nos[-1][11:])) if nos else "—",
             len(nos),
             (nas[0][11:]) if nas else "—", len(nas)))

print()
print("=== ③ 无 src 那个形状长什么样 ===")
sh = shapes.get("(无 src 键)", set())
for t in sorted(sh):
    print("  %s" % ", ".join(t))
    print("      有 bid 键: %s / 有 traded 键: %s"
          % ("bid" in t, "traded" in t))

print()
print("=== ④ 左沿之前:能力 vs 市场 ===")
SEG = [("14:30:00–14:34:27（src 上线前）", "14:30:00", "14:34:27"),
       ("14:34:28–14:50:05（src 已上线，左沿之前）", "14:34:28", "14:50:05"),
       ("14:50:06–16:48:21（指示价窗口）", "14:50:06", "16:48:21")]
print("  | 时段 | 块 | src=nasdaq | 带 bid 键 | **bid 非空** | 判读 |")
print("  |---|---|---|---|---|---|")
for lab, lo, hi in SEG:
    seg = [(ts, sp) for ts, sp, _ in blocks
           if "2026-11-19T" + lo <= ts <= "2026-11-19T" + hi]
    nas = [sp for _, sp in seg if sp.get("src") == "nasdaq"]
    hb = [sp for sp in nas if "bid" in sp]
    nb = [sp for sp in hb if sp.get("bid") is not None]
    if not seg:
        verdict = "无块"
    elif not hb:
        verdict = "**无捕获能力 ⇒ 不能断言**"
    elif not nb:
        verdict = "**有能力、全为 null ⇒ 确实没有指示价**"
    else:
        verdict = "有指示价"
    print("  | %s | %d | %d | %d | **%d** | %s |"
          % (lab, len(seg), len(nas), len(hb), len(nb), verdict))

print()
print("=== 判读 ===")
print("  若「src 上线前」那一段带 bid 键为 0 ⇒ 本路在那几分钟没有捕获能力,")
print("  **「14:50:06Z 之前没有指示价」只对 src 上线之后成立。**")
print("  左沿该写成「首次观测 14:50:06Z」,并注明此前的断言从哪一刻起有效。")
