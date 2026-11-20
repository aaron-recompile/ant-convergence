#!/usr/bin/env python3
"""界定本路对 115.10 到底能担保什么 —— 另一路要把它写成「你担保」。

必须分清三种东西:
  ① 本路**观测到的**价格(采样序列的最大值)
  ② 本路**读到的**厂商 day_high 字段(报告出来的统计量,不是观测)
  ③ 场所自己的日终记录(historical 日行)

本路采集 18:24:43Z 才部署,比 16:49 那段高位晚一小时三十五分 ——
**本路从未观测到一笔 115.10。** 所以 ① 给不出 115.10,只有 ②③ 能。
而 ②③ 的独立性是另一件事:五个端点一致 ≠ 五个独立测量。
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
A = os.path.expanduser("~/ant-spot-archive")
FILES = [os.path.join(D, "spot_2026-11-19.jsonl"),
         os.path.join(A, "spot_2026-11-19.jsonl"),
         os.path.join(A, "recovered_from_autostash_2026-11-19.jsonl"),
         os.path.join(A, "recovered_from_stash_pass2_2026-11-19.jsonl")]

seen = set()
rows = []
for p in FILES:
    if not os.path.exists(p):
        continue
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln or ln in seen:
            continue
        seen.add(ln)
        try:
            d = json.loads(ln)
        except Exception:
            continue
        ts = str(d.get("ts") or "")
        if not ts.startswith("2026-11-19"):
            continue
        rows.append((ts, d))
rows.sort(key=lambda x: x[0])

print("=== ① 本路观测到的价格(采样序列),11-19 当天 ===")
obs = []
for ts, d in rows:
    b = d.get("best") or {}
    v = b.get("price_usd")
    if isinstance(v, (int, float)):
        obs.append((ts, float(v)))
    for src in ("nasdaq_info", "cnbc", "yahoo"):
        blk = d.get(src)
        if isinstance(blk, dict) and isinstance(blk.get("price_usd"), (int, float)):
            obs.append((ts, float(blk["price_usd"])))
if obs:
    mx = max(v for _, v in obs)
    at = min(t for t, v in obs if v == mx)
    print("  观测条数 %d，覆盖 %s – %s" % (len(obs), obs[0][0][11:19] + "Z",
                                      obs[-1][0][11:19] + "Z"))
    print("  **本路观测到的最高价 = %.4f @ %sZ**" % (mx, at[11:19]))
    print("  有没有观测到 ≥115.00 的价格:", any(v >= 115.0 for _, v in obs))
    print("  有没有观测到 ≥114.00 的价格:", any(v >= 114.0 for _, v in obs))
    print("  ⇒ 本路部署于 18:24:43Z，而高位发生在 16:49 前后 ——")
    print("     **①(观测)给不出 115.10，也给不出 114.853。**")

print()
print("=== ② 本路读到的厂商 day_high 字段 ===")
fields = {
    "nasdaq_info": "day_high_usd",
    "nasdaq_summary": "day_high_usd",
    "nasdaq_nls": "day_high_rth_usd",
    "cnbc": "day_high_usd",
}
per = collections.defaultdict(collections.Counter)
cross_rows = collections.defaultdict(dict)
for ts, d in rows:
    for src, f in fields.items():
        blk = d.get(src)
        if isinstance(blk, dict) and isinstance(blk.get(f), (int, float)) and blk[f]:
            per[src][blk[f]] += 1
    cc = d.get("cross_check")
    if isinstance(cc, dict):
        for src, blk in cc.items():
            if not isinstance(blk, dict):
                continue
            for f in ("day_high_usd", "day_high_rth_usd"):
                if isinstance(blk.get(f), (int, float)) and blk[f]:
                    cross_rows[ts][src] = blk[f]
for src in sorted(per):
    print("  %-16s %s" % (src, dict(per[src].most_common(4))))

print()
print("=== cross_check 块:时刻与一致性 ===")
ts_full = sorted(cross_rows)
if ts_full:
    srcs = sorted({s for v in cross_rows.values() for s in v})
    full = [t for t in ts_full if len(cross_rows[t]) == len(srcs)]
    print("  源: %s" % srcs)
    print("  全源时刻 %d 个，范围 %sZ – %sZ"
          % (len(full), full[0][11:19], full[-1][11:19]))
    bad = [t for t in full if len(set(cross_rows[t].values())) > 1]
    vals = sorted({x for t in full for x in cross_rows[t].values()})
    print("  取值集合 %s / 不一致时刻 %d 个" % (vals, len(bad)))
    print("  **注意这些时刻全在收盘之后** —— 它们是收盘后各端点报出的日内最高价统计量，")
    print("     不是对那一刻价格的观测。")

print()
print("=== ③ 场所自己的日终记录 ===")
print("  historical 11/19/2026 行: open 111.50 / high 115.10 / low 92.72 /")
print("  close 97.17 / vol 857,312,300（两个不同窗口查询一致，本路 7.49.6 实测）")

print()
print("════════ 本路能担保的，与不能担保的 ════════")
print("  **能担保:**")
print("    (a) 本路读到的四个厂商 day_high 字段，在收盘后全部报 115.10；")
print("        cross_check 块 36 个全源时刻、5 个端点、不一致 0 个。")
print("    (b) Nasdaq 自己的日终日线(historical)报 high = 115.10，")
print("        且同一行的 open/low/close 与本路独立定稿的数全部对上。")
print("    (c) 因此 114.853 < 115.10 ⇒ 真实最高价那一刻未被任何一侧采样到。")
print()
print("  **不能担保:**")
print("    (d) 本路**没有观测到任何一笔 115.10** —— 部署于 18:24:43Z，高位已过。")
print("        115.10 是「厂商报告的统计量 + 场所日终记录」，不是本路的观测。")
print("    (e) **五个端点一致 ≠ 五个独立测量。** cnbc/yahoo 是否最终取自同一条")
print("        合并行情带，本路无法确立 —— 「五源一致」这个说法会高估独立性。")
print("        真正的权威出处只有一个: Nasdaq 自己的日终记录(上市场所本身)。")
print()
print("  ⇒ 建议文档写法:**当日最高价 115.10，出处 Nasdaq 日终日线记录**")
print("     (另有四个零售端点的 day_high 字段一致，但独立性未确立)。")
print("     不要写「五源一致」，那是端点数不是独立测量数。")
