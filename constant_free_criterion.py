#!/usr/bin/env python3
"""核不含常数的占位价判据，以及 bracket 在它之下还成不成立。

另一路指出:本路新判据 `traded ∧ price != 83.0` **把发行价写死了** ——
正是本路刚在 7.71.1 批评过的 `_spot_nasdaq` 闸门(`abs(px-83.0)<1e-9`)那个毛病。

它给的通用形式:

    占位价  ⇔  price == prev_close  ∧  vol in (None, 0)

不含任何写死的价格、对 src 不敏感。本脚本三件:
  ① 11-19:新判据是否与已知那 70 条逐条重合(召回完整、误报 0)
  ② 11-20 对照日:1,536 个可判块里触发几条(它报 0)
  ③ **bracket 在新判据下是否仍是 (16:48:21Z, 16:48:26Z]**
  ④ 残余敞口:陈旧超过一天的报价不会等于 prev_close —— 本判据抓不到
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")


def load(day):
    files = [os.path.join(D, "ant_%s.jsonl" % day),
             os.path.join(D, "binance_%s.jsonl" % day),
             os.path.join(RESC, "rescued_ant_%s.jsonl" % day)]
    rows, seen = [], set()
    for p in files:
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
            ts = str(d.get("ts_utc") or d.get("ts") or "")[:19]
            sp = d.get("spot_ANT_nasdaq")
            if ts.startswith(day) and isinstance(sp, dict):
                rows.append((ts, sp))
    rows.sort(key=lambda x: x[0])
    return rows


def is_ph_const(sp):
    """旧判据：写死 83.0。"""
    p = sp.get("price")
    return isinstance(p, (int, float)) and abs(float(p) - 83.0) < 1e-9


def is_ph_rel(sp):
    """新判据：price == prev_close ∧ vol in (None, 0)。不含常数。"""
    p, pc = sp.get("price"), sp.get("prev_close")
    if not isinstance(p, (int, float)) or not isinstance(pc, (int, float)):
        return False
    if abs(float(p) - float(pc)) > 1e-9:
        return False
    v = sp.get("vol")
    return v in (None, 0) or v == 0.0


for day in ("2026-11-19", "2026-11-20"):
    rows = load(day)
    if not rows:
        print("%s: 无数据" % day)
        continue
    judge = [(t, s) for t, s in rows
             if isinstance(s.get("price"), (int, float))
             and isinstance(s.get("prev_close"), (int, float))]
    rel = [(t, s) for t, s in rows if is_ph_rel(s)]
    const = [(t, s) for t, s in rows if is_ph_const(s)]
    eqpc = [(t, s) for t, s in judge
            if abs(float(s["price"]) - float(s["prev_close"])) <= 1e-9]
    print("══════ %s ══════" % day)
    print("  spot 块 %d / price 与 prev_close 都有的 %d" % (len(rows), len(judge)))
    print("  price == prev_close          : **%d**" % len(eqpc))
    print("  其中 traded=True             : %d" % sum(1 for _, s in eqpc if s.get("traded")))
    print("  带非零成交量而 price==prev_close: %d"
          % sum(1 for _, s in eqpc if s.get("vol") not in (None, 0) and s.get("vol") != 0.0))
    print("  **新判据（关系式）命中**       : **%d**" % len(rel))
    print("  旧判据（写死 83.0）命中        : %d" % len(const))
    only_rel = [t for t, _ in rel if not any(t == t2 and s2 is _ for t2, s2 in const)]
    sr = collections.Counter(s.get("src") or "(无)" for _, s in rel)
    print("  新判据命中的 src 分布          : %s" % (dict(sr) or "—"))
    same = len(rel) == len(const) and all(
        is_ph_const(s) for _, s in rel) and all(is_ph_rel(s) for _, s in const)
    print("  **两判据是否逐条重合           : %s**"
          % ("是（召回完整、误报 0）" if same else "**否 —— 要逐条看**"))
    if not same:
        a = [(t, s.get("price"), s.get("prev_close"), s.get("src"))
             for t, s in const if not is_ph_rel(s)]
        b = [(t, s.get("price"), s.get("prev_close"), s.get("src"))
             for t, s in rel if not is_ph_const(s)]
        print("     只被旧判据抓到: %s" % (a[:4] or "无"))
        print("     只被新判据抓到: %s" % (b[:4] or "无"))
    print()

print("══════ ③ bracket 在新判据下 ══════")
rows = load("2026-11-19")
for label, fn in (("旧判据 traded ∧ price≠83.0", is_ph_const),
                  ("**新判据 traded ∧ ¬(price==prev_close ∧ vol==0)**", is_ph_rel)):
    seq = [(t, bool(s.get("traded"))) for t, s in rows if not fn(s)]
    lf = ft = None
    for t, tr in seq:
        if tr and ft is None and lf is not None:
            ft = t
        if not tr and ft is None:
            lf = t
    ok = lf and ft and lf[11:] == "16:48:21" and ft[11:] == "16:48:26"
    print("  %-52s (%sZ, %sZ]   与 7.44 一致: %s"
          % (label, lf[11:] if lf else "—", ft[11:] if ft else "—",
             "**是**" if ok else "否"))

print()
print("══════ ④ 残余敞口 ══════")
print("  新判据抓的是「等于前一日收盘」。**陈旧超过一天的报价不等于 prev_close**,")
print("  本判据抓不到 —— 而 11-19 那条 cnbc 自报 last_timedate=11/18(正好一天),")
print("  所以它被抓到了。**这是实测的缺席,不是结构上的保证。**")
