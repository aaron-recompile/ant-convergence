#!/usr/bin/env python3
"""结清三件:322 / 57 两个计数、以及 kucoin 74.0 还是 74.1。

另一路追了本路那句「同一量级,不追」,查出:
  - funding 段数差 225 = 抢救档(322 条,单独 228 段,3 段接边并掉)
  - 重复率差 0.2pp = 同一批 322 条里落在竞价窗口的 57 条
  - 归档件 b8 含 rescued/rescued_ant_2026-11-19.jsonl 且 README 要求读者自做并集
    ⇒ 并集口径(n=1,523)才是权威基准,本路那组数该发表

它请本路按 73.5 / 73.5 / **74.1** (n=1,523) 定稿,而本路此前测的是 74.0。
**要定稿就先把这 0.1pp 结清** —— 带分子分母一起打,不只打百分比。
"""
import collections
import io
import json
import os

D = os.path.expanduser("~/ant-convergence/data")
RESC = os.path.expanduser("~/ant-rescue")
CONFLICT = ("<<<<<<<", "=======", ">>>>>>>", "|||||||")
VENUES = ["gate_ANT_USDT", "bitget_ANTUSDT", "kucoin_ANTUSDTM",
          "hl_xyz_ANT", "kraken_PF_ANTXUSD"]
WLO, WHI = "2026-11-19T14:50:06", "2026-11-19T16:48:21"
ANT = os.path.join(D, "ant_2026-11-19.jsonl")
RES = os.path.join(RESC, "rescued_ant_2026-11-19.jsonl")


def load(paths):
    out, seen = [], set()
    for p in paths:
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
                out.append((ts, d))
    out.sort(key=lambda x: x[0])
    return out


ant_only = load([ANT])
both = load([ANT, RES])
res_only = load([RES])

print("=== ① 抢救档的 322 条是否全部不在 ant_ 里 ===")
ant_ts = collections.Counter(t for t, _ in ant_only)
res_ts = [t for t, _ in res_only]
print("  抢救档记录数: %d" % len(res_only))
print("  其 ts_utc 也出现在 ant_ 里的: %d" % sum(1 for t in res_ts if t in ant_ts))
print("  时间范围: %sZ – %sZ" % (res_ts[0][11:], res_ts[-1][11:]) if res_ts else "—")
in_win = [t for t in res_ts if WLO <= t <= WHI]
print("  **落在竞价窗口 %s–%s 的: %d 条**" % (WLO[11:], WHI[11:], len(in_win)))

print()
print("=== ② 竞价窗口记录数 ===")
for lab, rows in (("仅 ant_", ant_only), ("**ant_ + 抢救档**", both)):
    w = [1 for t, _ in rows if WLO <= t <= WHI]
    print("  %-18s %d 条" % (lab, len(w)))

print()
print("=== ③ 重复率，分子分母一起打 ===")


def rate(rows, v):
    # 见证字段：本窗口内变过的
    w = [(t, d) for t, d in rows if WLO <= t <= WHI]
    vals = collections.defaultdict(set)
    for t, d in w:
        b = d.get(v)
        if isinstance(b, dict):
            for k, x in b.items():
                if isinstance(x, (int, float, str, bool)) or x is None:
                    vals[k].add(repr(x))
    wit = sorted(k for k, s in vals.items() if len(s) > 1)
    prev, nf, nt = None, 0, 0
    for t, d in w:
        b = d.get(v)
        if not isinstance(b, dict):
            continue
        sig = tuple(repr(b.get(k)) for k in wit)
        nt += 1
        if prev is not None and prev == sig:
            nf += 1
        prev = sig
    return nf, nt, len(wit)


print("| 场所 | 仅 ant_ | **ant_ + 抢救档** | 另一路报(仅 ant_) | 另一路请我定稿的 |")
print("|---|---|---|---|---|")
PEER_ONLY = {"gate_ANT_USDT": "73.3%", "bitget_ANTUSDT": "73.3%",
             "kucoin_ANTUSDTM": "73.8%", "hl_xyz_ANT": "—",
             "kraken_PF_ANTXUSD": "—"}
PEER_FINAL = {"gate_ANT_USDT": "73.5%", "bitget_ANTUSDT": "73.5%",
              "kucoin_ANTUSDTM": "**74.1%**", "hl_xyz_ANT": "—",
              "kraken_PF_ANTXUSD": "—"}
for v in VENUES:
    a_nf, a_nt, a_w = rate(ant_only, v)
    b_nf, b_nt, b_w = rate(both, v)
    print("| %s | %d/%d = %.2f%% (见证 %d) | **%d/%d = %.2f%%** (见证 %d) | %s | %s |"
          % (v, a_nf, a_nt, 100.0 * a_nf / max(1, a_nt), a_w,
             b_nf, b_nt, 100.0 * b_nf / max(1, b_nt), b_w,
             PEER_ONLY[v], PEER_FINAL[v]))

print()
print("=== ④ 归档件 b8 里有没有抢救档 ===")
import zipfile
Z = os.path.expanduser("~/ant_listing_day_2026-11-19_v1-b8.zip")
if os.path.exists(Z):
    z = zipfile.ZipFile(Z)
    hit = [n for n in z.namelist() if "rescued_ant" in n]
    print("  %s" % (hit or "**不在包里**"))
    for n in hit:
        print("    %s  %d 字节" % (n, z.getinfo(n).file_size))
        same = z.read(n) == io.open(RES, "rb").read()
        print("    与 ~/ant-rescue/ 那份逐字节相同: %s" % same)
else:
    print("  包不在 %s" % Z)

print()
print("=== 判读 ===")
print("  若 kucoin 并集口径算出 74.1% ⇒ 采纳另一路的数;")
print("  若算出 74.0% ⇒ 0.1pp 仍未结清,要把分子分母并排看是谁的四舍五入。")
