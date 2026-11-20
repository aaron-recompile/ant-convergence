#!/usr/bin/env python3
"""核那 6 条的字段签名，并普查:本路消费的块里还有没有别的静默半成品模式。

另一路定位:那 6 条全是 binance_ANTUSDT,`mark`/`index`/`funding` 三个一起缺,
成因是 `binance()` 里 `if p: r.update({...})` —— ticker 成功而 premiumIndex 失败时,
闸门让三个键直接不出现,外层 try 没抛异常,所以记录里也没有 `_err`。
(本路早先读 collector.py 第 130–137 行时见过那段代码,与此一致。)

**而对本路有后果的问题是另一个:本路消费的那些块里还有没有别的静默半成品模式?**
一个块缺了某些键而别的键在,会让按键计数的任何结论静默偏移 ——
而它不以错误的形式出现,只以「这个键少了几条」的形式出现。

本脚本:
  ① 核那 6 条的字段签名
  ② 核「mark 与 index 从不单独缺失」
  ③ 普查五家永续 + 现货块:每个键的出现率,并列出「同一块里成组缺失」的模式
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
PRE_LO, PRE_HI = "2026-11-19T00:00:00", "2026-11-19T16:48:26"
BLOCKS = ["hl_xyz_ANT", "kraken_PF_ANTXUSD", "bitget_ANTUSDT",
          "gate_ANT_USDT", "kucoin_ANTUSDTM", "binance_ANTUSDT",
          "spot_ANT_nasdaq"]
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
print("盘前记录 %d 条（已按 via 剔 coingecko 的逻辑在下面逐块应用）" % len(recs))

print()
print("=== ① 那 6 条「有 last 无 mark」的字段签名 ===")
six = []
for ts, d in recs:
    for v in BLOCKS:
        b = d.get(v)
        if not isinstance(b, dict) or b.get("via") == "coingecko":
            continue
        if b.get("last") is not None and b.get("mark") is None:
            six.append((ts, v, sorted(k for k, x in b.items() if x is not None)))
print("  共 %d 条" % len(six))
sigs = collections.Counter((v, tuple(ks)) for _, v, ks in six)
for (v, ks), n in sigs.most_common():
    print("  %s ×%d  有值字段: %s" % (v, n, ", ".join(ks)))
    for miss in ("mark", "index", "funding"):
        print("      %s 缺: %s" % (miss, "是" if miss not in ks else "**否**"))
    break
print("  时刻: %s" % ", ".join(t[11:] + "Z" for t, _, _ in six))

print()
print("=== ② mark 与 index 是否从不单独缺失 ===")
only_one = []
for ts, d in recs:
    for v in BLOCKS:
        b = d.get(v)
        if not isinstance(b, dict) or b.get("via") == "coingecko":
            continue
        hm = b.get("mark") is not None
        hi = b.get("index") is not None
        if hm != hi:
            only_one.append((ts, v, hm, hi))
print("  只有其中一个的块: **%d**（另一路报 0）" % len(only_one))
for ts, v, hm, hi in only_one[:5]:
    print("     %sZ %s  mark=%s index=%s" % (ts[11:], v, hm, hi))

print()
print("=== ③ 普查:每个块各键的出现率，找成组缺失 ===")
for v in BLOCKS:
    cnt = collections.Counter()
    tot = 0
    for ts, d in recs:
        b = d.get(v)
        if not isinstance(b, dict) or b.get("via") == "coingecko":
            continue
        tot += 1
        for k, x in b.items():
            if x is not None:
                cnt[k] += 1
    if not tot:
        continue
    # 出现率不是 100% 也不是 0% 的键 —— 那些是可能的半成品信号
    partial = sorted(((k, 100.0 * n / tot) for k, n in cnt.items()
                      if 0 < n < tot), key=lambda kv: kv[1])
    print("  %-20s 块 %d 个" % (v, tot))
    if not partial:
        print("      所有键 100%% 出现 —— 无半成品信号")
        continue
    for k, r in partial:
        flag = "  **← 成组?**" if r > 99.9 else ""
        print("      %-22s %.3f%% (%d/%d)%s" % (k, r, cnt[k], tot, flag))

print()
print("=== 判读 ===")
print("  ③ 里出现率相同的若干键 = 同一次调用的产物 ⇒ 成组缺失 ⇒ 静默半成品。")
print("  **它不以错误的形式出现,只以「这个键少了几条」的形式出现** ——")
print("  而按键计数的任何结论都会被它静默偏移。")
