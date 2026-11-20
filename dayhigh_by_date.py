#!/usr/bin/env python3
"""按日期分开算 day_high 的运行序列。

初版只打 HH:MM:SS,把日期藏掉了 —— 而 spot_2026-11-19.jsonl 里混着
11-19 与 11-20 两天的记录(跨日 bug,已登记)。于是 90.01→92.56 那一串
(今天的运行最高价)和 114.99→115.10(11-19 的)被排在同一条序列里,
差一步报出一个建立在两天混算上的结论。

**输出里省掉日期,就是把决定比较结果的那个变量省掉了。**
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
FILES = [os.path.join(D, "spot_2026-11-19.jsonl"),
         os.path.expanduser("~/ant-spot-archive/spot_2026-11-19.jsonl"),
         os.path.join(D, "spot_2026-11-20.jsonl"),
         os.path.expanduser("~/ant-spot-archive/spot_2026-11-20.jsonl")]

FIELDS = {
    "nasdaq_info":    ("nasdaq_info", "day_high_usd"),
    "nasdaq_nls":     ("nasdaq_nls", "day_high_rth_usd"),
    "nasdaq_summary": ("nasdaq_summary", "day_high_usd"),
    "cnbc":           ("cnbc", "day_high_usd"),
}

# series[(day, label)] = [(ts, v)]
series = collections.defaultdict(list)
cross = collections.defaultdict(dict)   # cross[(day, ts)][src] = v
seen = set()
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
        ts = d.get("ts")
        if not ts or len(ts) < 19:
            continue
        day = ts[:10]
        for label, (blk, fld) in FIELDS.items():
            b = d.get(blk)
            if isinstance(b, dict) and b.get(fld) not in (None, "", 0.0):
                series[(day, label)].append((ts, float(b[fld])))
        cc = d.get("cross_check")
        if isinstance(cc, dict):
            for src, b in cc.items():
                if not isinstance(b, dict):
                    continue
                for fld in ("day_high_usd", "day_high_rth_usd"):
                    if b.get(fld) not in (None, "", 0.0):
                        cross[(day, ts)][src] = float(b[fld])

for day in sorted({k[0] for k in series}):
    print("══════════════ 记录日 %s ══════════════" % day)
    for label in sorted(l for (dd, l) in series if dd == day):
        s = sorted(series[(day, label)])
        byval = collections.OrderedDict()
        for ts, v in s:
            byval.setdefault(v, [ts, ts])
            byval[v][1] = ts
        print("  %-16s %d 条   %s – %s"
              % (label, len(s), s[0][0][11:19] + "Z", s[-1][0][11:19] + "Z"))
        for v in sorted(byval):
            a, b = byval[v]
            print("       %-9s 首次 %s  末次 %s" % (v, a[11:19] + "Z", b[11:19] + "Z"))
    # 该日的 114.99 / 115.1 关系
    s = sorted(series.get((day, "nasdaq_info"), []))
    t99 = [ts for ts, v in s if abs(v - 114.99) < 1e-9]
    t10 = [ts for ts, v in s if abs(v - 115.1) < 1e-9]
    if t99 and t10:
        print("  → 114.99 末次 %s / 115.10 首次 %s  ⇒ %s"
              % (t99[-1][11:19] + "Z", t10[0][11:19] + "Z",
                 "不重叠（运行最高价上移）" if t99[-1] < t10[0] else "**交错（真源分歧）**"))
    print()

print("══════════════ cross_check 五源一致性（按记录日分开）══════════════")
for day in sorted({k[0] for k in cross}):
    rows = {ts: v for (dd, ts), v in cross.items() if dd == day}
    srcs = sorted({s for v in rows.values() for s in v})
    full = [ts for ts, v in rows.items() if len(v) == len(srcs)]
    bad = [(ts, rows[ts]) for ts in full if len(set(rows[ts].values())) > 1]
    vals = sorted({x for ts in full for x in rows[ts].values()})
    print("  %s: 源 %s / 全源时刻 %d 个 / 不一致 %d 个 / 取值集合 %s"
          % (day, srcs, len(full), len(bad), vals))
    for ts, v in bad[:4]:
        print("      %s  %s" % (ts[11:19] + "Z", v))
