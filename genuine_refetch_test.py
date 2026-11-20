#!/usr/bin/env python3
"""那 19.1%「真取数但上游没变」是真的一类，还是模型误判?

另一路报竞价窗口 gate 的交叉表(n=1,466):
   逐位相同 ∧ 模拟命中      54.2%   确信回放
   逐位相同 ∧ 模拟未命中    19.1%   「真取数但上游没变」⇒ 本可用于配对
   值变了   ∧ 模拟命中      18.5%   **模型下不可能**
   值变了   ∧ 模拟未命中     8.3%   确信新值
并据此说本路的「逐位相同」判据偏保守,会丢掉那 19.1%。

**但那一类是由模拟定义的,而同一张表证明模拟逐条有 18.5% 不可能发生。**
所以先问一个不依赖模拟的问题:

  一次**真取数**返回的 14–16 个字段(含 bid / ask / 成交量)
  全部逐位不变,在一个活跃市场里有多可能?

可测:在「mark 相同」的时刻里,bid/ask/成交量 也相同的占比。
  若接近 100% ⇒ 「真取数而一字未变」不可信 ⇒ 那 19.1% 多半是模型误判;
  若明显低于 100% ⇒ 存在「mark 没变但别的变了」的真取数 ⇒ 本路判据确实偏保守,
                    而那一类的大小可以**不依赖模拟**地量出来。
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
CACHED = ["gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM"]
CLEAN = ["hl_xyz_ANT", "kraken_PF_ANTXUSD"]
LO, HI = "2026-11-19T14:50:06", "2026-11-19T16:48:21"

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

# 全天变过的字段（见证集）—— 用竞价窗口内变过的，更贴近本窗口
varying = {}
for v in CACHED + CLEAN:
    vals = collections.defaultdict(set)
    for ts, d in rows:
        b = d.get(v)
        if isinstance(b, dict):
            for k, x in b.items():
                if isinstance(x, (int, float, str, bool)) or x is None:
                    vals[k].add(repr(x))
    varying[v] = sorted(k for k, s in vals.items() if len(s) > 1)

print()
print("=== 在「mark 相同」的时刻里，其他见证字段也相同吗 ===")
print("| 场所 | 见证字段 | mark 相同的时刻 | 其中**其他字段全同** | 占比 | 其中至少一个字段变了 |")
print("|---|---|---|---|---|---|")
for v in CACHED + CLEAN:
    wit = [k for k in varying[v] if k != "mark"]
    prev = None
    n_same_mark = 0
    n_all_same = 0
    examples = []
    for ts, d in rows:
        b = d.get(v)
        if not isinstance(b, dict):
            continue
        cur = {k: repr(b.get(k)) for k in varying[v]}
        if prev is not None and cur.get("mark") == prev.get("mark"):
            n_same_mark += 1
            others_same = all(cur.get(k) == prev.get(k) for k in wit)
            if others_same:
                n_all_same += 1
            elif len(examples) < 3:
                diff = [k for k in wit if cur.get(k) != prev.get(k)]
                examples.append((ts, diff[:5]))
        prev = cur
    if n_same_mark == 0:
        print("| %s | %d | 0 | — | — | — |" % (v, len(wit)))
        continue
    print("| %s | %d | %d | **%d** | **%.1f%%** | %d |"
          % (v, len(wit), n_same_mark, n_all_same,
             100.0 * n_all_same / n_same_mark, n_same_mark - n_all_same))
    for ts, diff in examples:
        print("|   例 %sZ |  |  |  |  | 变了: %s |" % (ts[11:], ", ".join(diff)))

print()
print("=== 判读 ===")
print("  对缓存三家:若「mark 相同」的时刻里其他字段也几乎全同(接近 100%),")
print("  则「真取数而 14–16 个字段一字未变」这件事在本窗口几乎不发生 ——")
print("  **那 19.1% 多半是模拟误判,不是一类真实可用的观测。**")
print()
print("  对直取两家:它们应有相当比例「mark 相同但别的变了」——")
print("  那正是「真取数、mark 恰好没变」的样子,可作对照组。")
print("  **若直取源有这种样本而缓存源几乎没有,对照就成立。**")
