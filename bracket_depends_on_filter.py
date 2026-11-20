#!/usr/bin/env python3
"""核两件:那条 yahoo 记录是不是首笔、以及本路 5 秒 bracket 依赖哪一步过滤。

另一路指出:
  (a) 那条 yahoo @16:48:26Z 的 day_low = 111.44 < 111.50、vol 已 8,225 万
      ⇒ 到那一采样为止已有低于 111.50 的成交 ⇒ 那个 price=111.5 **不是首笔**;
  (b) **traded 首次为 True 在 14:37:50Z(yahoo, price=83.0)**,比首笔早两小时
      —— 就是那 69 条 yahoo 占位价。
      ⇒ 本路 7.44 的 (16:48:21Z, 16:48:26Z] **隐含依赖「占位价已剔除」**,
         而那一步没写进判据。照 `traded` 裸跑会得到 14:37:50Z。

本脚本:
  ① 那条 yahoo 记录全文
  ② 逐 src 的最早 traded=True，分「不过滤」与「剔占位价」两种
  ③ 在剔占位价的口径下重算 bracket，确认 (16:48:21Z, 16:48:26Z] 成立
  ④ 不剔占位价时 bracket 会变成什么 —— 把后果量出来
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
FILES = [(os.path.join(D, "ant_2026-11-19.jsonl"), "ant_"),
         (os.path.join(D, "binance_2026-11-19.jsonl"), "binance_"),
         (os.path.join(RESC, "rescued_ant_2026-11-19.jsonl"), "rescue")]

rows, seen = [], set()
for p, tag in FILES:
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
        sp = d.get("spot_ANT_nasdaq")
        if ts.startswith("2026-11-19") and isinstance(sp, dict):
            rows.append((ts, tag, sp))
rows.sort(key=lambda x: x[0])
print("全天 spot 块 %d 个" % len(rows))

print()
print("=== ① 那条 yahoo @16:48:26Z 全文 ===")
for ts, tag, sp in rows:
    if ts == "2026-11-19T16:48:26" and sp.get("src") == "yahoo":
        print("  [%s] %s" % (tag, json.dumps(sp, ensure_ascii=False, sort_keys=True)))
        dl = sp.get("day_low")
        print("  day_low = %s   price = %s   vol = %s" % (dl, sp.get("price"), sp.get("vol")))
        if isinstance(dl, (int, float)):
            print("  **day_low %.2f %s 111.50 ⇒ %s**"
                  % (dl, "<" if dl < 111.5 else ">=",
                     "到该采样为止已有低于 111.50 的成交 ⇒ 那不是首笔"
                     if dl < 111.5 else "不排除它是首笔"))


def is_ph(sp):
    p = sp.get("price")
    return isinstance(p, (int, float)) and abs(float(p) - 83.0) < 1e-9


print()
print("=== ② 逐 src 的最早 traded=True ===")
print("| src | 不过滤 | price | **剔占位价(price≠83.0)** | price |")
print("|---|---|---|---|---|")
for s in ("yahoo", "cnbc", "nasdaq", None):
    sel = [(ts, sp) for ts, _, sp in rows
           if (sp.get("src") == s if s else sp.get("src") is None) and sp.get("traded")]
    if not sel:
        continue
    a = sel[0]
    b = [(ts, sp) for ts, sp in sel if not is_ph(sp)]
    print("| %s | %sZ | %s | %s | %s |"
          % (s or "(无 src)", a[0][11:], a[1].get("price"),
             (b[0][0][11:] + "Z") if b else "—",
             b[0][1].get("price") if b else "—"))
allt = [(ts, sp) for ts, _, sp in rows if sp.get("traded")]
allf = [(ts, sp) for ts, sp in allt if not is_ph(sp)]
print()
print("  **并集最早 traded=True:不过滤 %sZ (price=%s) / 剔占位价 %sZ (price=%s)**"
      % (allt[0][0][11:], allt[0][1].get("price"),
         allf[0][0][11:], allf[0][1].get("price")))

print()
print("=== ③ 剔占位价口径下的 bracket ===")
seq = [(ts, bool(sp.get("traded"))) for ts, _, sp in rows if not is_ph(sp)]
last_f = first_t = None
for ts, tr in seq:
    if tr and first_t is None and last_f is not None:
        first_t = ts
    if not tr and first_t is None:
        last_f = ts
print("  最后一个 traded=False : %sZ" % (last_f[11:] if last_f else "—"))
print("  其后首个 traded=True  : %sZ" % (first_t[11:] if first_t else "—"))
ok = last_f and first_t and last_f[11:] == "16:48:21" and first_t[11:] == "16:48:26"
print("  **与 7.44 的 (16:48:21Z, 16:48:26Z] 一致: %s**" % ("是" if ok else "否"))

print()
print("=== ④ 不剔占位价时 bracket 会变成什么 ===")
seq2 = [(ts, bool(sp.get("traded"))) for ts, _, sp in rows]
lf = ft = None
for ts, tr in seq2:
    if tr and ft is None and lf is not None:
        ft = ts
    if not tr and ft is None:
        lf = ts
print("  最后一个 False %sZ → 首个 True %sZ" % (lf[11:] if lf else "—", ft[11:] if ft else "—"))
print("  **⇒ 裸跑 `traded` 得到的区间与 7.44 相差: %s**"
      % ("巨大（早两小时以上）" if ft and ft[11:13] < "16" else "需看"))
print()
print("=== 判读 ===")
print("  若 ③ 成立而 ④ 给出早得多的时刻 ⇒ 本路 7.44 的 bracket **依赖一步未写进判据的过滤**,")
print("  **必须把判据写成 `traded ∧ price≠83.0`(或 placeholder=false),否则不可复算。**")
