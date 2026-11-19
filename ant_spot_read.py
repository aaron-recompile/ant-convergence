#!/usr/bin/env python3
"""ANT 2026-11-19 现货数据的**规范读法**。任何分析脚本都应经由本模块读数，
不要直接 `json.loads` 原始 jsonl —— 原始文件里有六类已登记的瑕疵，
绕过它们需要知道六条规则，而「知道」靠文档传递是不可靠的。

文件名刻意不含 `collector.py` 子串（`run_mini.sh` 用 pgrep -f 判主采集器存活）。

本模块实现的六条规则，每条都附了它为何存在：

R1  并集三个来源，整行精确去重。
    `data/` 在 git 仓内，`run_mini.sh` 的 `git pull --rebase --autostash` 会销毁
    未提交的追加行（实测本路被吃掉 136 行、7 个窗口）。仓外归档与抢救档补回这些洞。

R2  丢弃 `kind=="official_close"` 且 `official_close_field=="data.previousInfo"` 的记录。
    那 36 条的 `official_close_usd` 是**上一交易日**的收盘参考值（本日为首日，恰等于发行价
    83.0），不是本日收盘价。本日收盘价只认 `official_close_final` / `close_*.json`。

R3  spot 按 `(ts, kind)` 去重。
    18:31:39Z–18:33:4xZ 曾有两个采集进程并写，7 个时刻同秒双条、3 处逆序。

R4  nasdaq_chart 的 bar 必须有 `tz_fix_applied`。
    早期 98 条的 `x` 是把 ET 墙上时间当 UTC 编码的，差 5 小时（EST 18000s）。
    修正后那一路已完整重发，剔除不丢分钟。

R5  bar 必须 `bar_ts % 60 == 0`。
    `yahoo_1m` 返回数组的最后一个元素是**当前未走完的 bar**，时间戳是取数时刻而非
    分钟边界（实测 94 个）。混进来会让同一分钟出现半成品。

R6  **分钟收盘价主序列用 `yahoo_1m`，`nasdaq_chart` 只作互校。**
    实测 `nasdaq_chart` 对**同一个标签分钟**在不同抓取时刻给出不同收盘价：
    277 个分钟里 133 个（48.0%）自相矛盾，同分钟极差中位 $0.1150、最大 $1.0413，
    且在该分钟收盘数小时后仍在变（例：标签 `11:49 AM ET` 的 bar，18:26Z 抓到 111.68，
    21:16Z 抓到 111.67；两次的 `label_src` 与原始 `x` 完全相同，故不是本地换算撞车）。
    `yahoo_1m` 则稳定：253 个分钟里仅 3 个（1.2%）有分歧，极差中位 $0.0050、最大 $0.0300。
    两源重合的 253 个分钟同分钟之差中位 $0.0000、最大 $0.2322 —— 说明 nasdaq 的不稳是
    围绕同一条序列的噪声，不是另一条序列。
    **所以「同一 (src,bar_ts) 取最后抓到的那个」是没有依据的规则，本模块不采用。**
    nasdaq_chart 的多值分钟一律原样带出 `close_candidates` + `close_spread_usd` +
    `unstable=True`，让分析方自己决定，不在读数层偷偷选一个。
"""
import json, os, sys
from collections import defaultdict

REPO    = os.path.expanduser("~/ant-convergence/data")
ARCHIVE = os.path.expanduser("~/ant-spot-archive")
DAY     = "2026-11-19"
ISSUE_PRICE = 83.0

SPOT_SOURCES = [
    os.path.join(REPO,    "spot_%s.jsonl" % DAY),
    os.path.join(ARCHIVE, "spot_%s.jsonl" % DAY),
    os.path.join(ARCHIVE, "recovered_from_autostash_%s.jsonl" % DAY),
]
BAR_SOURCES = [
    os.path.join(REPO,    "minbars_%s.jsonl" % DAY),
    os.path.join(ARCHIVE, "minbars_%s.jsonl" % DAY),
]
CLOSE_SOURCES = [
    os.path.join(REPO,    "close_%s.json" % DAY),
    os.path.join(ARCHIVE, "close_%s.json" % DAY),
]


def _union(paths):
    """R1：并集 + 整行精确去重。返回 (records, stats)。"""
    seen, out = set(), []
    stats = {"files": {}, "dupe_lines": 0, "unparsable": 0}
    for p in paths:
        n_new = n_dup = n_bad = 0
        if not os.path.exists(p):
            stats["files"][p] = "缺失"
            continue
        for ln in open(p, errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            if ln in seen:
                n_dup += 1
                continue
            seen.add(ln)
            try:
                out.append(json.loads(ln))
                n_new += 1
            except Exception:
                n_bad += 1
        stats["files"][p] = "新增 %d / 重复 %d / 不可解析 %d" % (n_new, n_dup, n_bad)
        stats["dupe_lines"] += n_dup
        stats["unparsable"] += n_bad
    return out, stats


def load_spot(verbose=False):
    """快照序列。应用 R1 / R2 / R3。返回 (records, report)。"""
    recs, stats = _union(SPOT_SOURCES)
    rep = dict(stats)
    rep["raw"] = len(recs)

    # R2
    bad_oc = [r for r in recs
              if r.get("kind") == "official_close"
              and r.get("official_close_field") == "data.previousInfo"]
    recs = [r for r in recs if r not in bad_oc] if len(bad_oc) < 200 else \
           [r for r in recs if not (r.get("kind") == "official_close"
                                    and r.get("official_close_field") == "data.previousInfo")]
    rep["R2_dropped_prevclose_records"] = len(bad_oc)

    # R3
    by_key, dropped = {}, 0
    for r in recs:
        k = (r.get("ts"), r.get("kind"))
        if k in by_key:
            dropped += 1
            continue
        by_key[k] = r
    recs = list(by_key.values())
    rep["R3_dropped_dup_ts_kind"] = dropped

    recs.sort(key=lambda r: (r.get("t_epoch") or 0))
    rep["kept"] = len(recs)
    if verbose:
        _dump(rep, "load_spot")
    return recs, rep


def load_bars(primary="yahoo_1m", verbose=False):
    """分钟线。应用 R1 / R4 / R5 / R6。

    返回 (bars, report)。bars 是按 bar_ts 排序的 dict 列表：
      {bar_ts, src, close_usd, close_candidates, close_spread_usd, unstable, n_fetches}
    `close_usd` 只在 unstable=False 时是单一可信值；unstable=True 时它为 None，
    真正的候选在 `close_candidates` 里 —— **刻意不替分析方选**（见 R6）。
    """
    recs, stats = _union(BAR_SOURCES)
    rep = dict(stats)
    rep["raw"] = len(recs)

    kept, d4, d5 = [], 0, 0
    for r in recs:
        if r.get("src") == "nasdaq_chart" and not r.get("tz_fix_applied"):
            d4 += 1                                     # R4
            continue
        bt = r.get("bar_ts")
        if bt is None or bt % 60:
            d5 += 1                                     # R5
            continue
        kept.append(r)
    rep["R4_dropped_untz_fixed"] = d4
    rep["R5_dropped_offgrid_bar"] = d5

    grp = defaultdict(list)
    for r in kept:
        grp[(r.get("src"), r["bar_ts"])].append(r)

    out, n_unstable = [], defaultdict(int)
    for (src, bt), v in grp.items():
        cands = sorted({c for c in (x.get("close_usd") for x in v) if c is not None})
        single = len(cands) == 1
        if not single:
            n_unstable[src] += 1
        out.append({
            "bar_ts": bt, "src": src,
            "close_usd": cands[0] if single else None,
            "close_candidates": cands,
            "close_spread_usd": (round(cands[-1] - cands[0], 6) if len(cands) > 1 else 0.0),
            "unstable": not single,
            "n_fetches": len(v),
            "vol_shares": next((x.get("vol_shares") for x in v
                                if x.get("vol_shares") is not None), None),
        })
    out.sort(key=lambda b: (b["src"], b["bar_ts"]))
    rep["unstable_minutes_by_src"] = dict(n_unstable)
    rep["minutes_by_src"] = {s: sum(1 for b in out if b["src"] == s)
                             for s in {b["src"] for b in out}}
    rep["R6_primary_src"] = primary
    rep["kept"] = len(out)
    if verbose:
        _dump(rep, "load_bars")
    return out, rep


def minute_close_series(verbose=False):
    """R6 的落地：返回 {bar_ts: close_usd} 主序列（yahoo_1m），
    外加 nasdaq_chart 的互校结果。主序列里不含 unstable 的分钟。"""
    bars, rep = load_bars(verbose=verbose)
    prim = {b["bar_ts"]: b["close_usd"] for b in bars
            if b["src"] == "yahoo_1m" and not b["unstable"]}
    xchk = {b["bar_ts"]: b for b in bars if b["src"] == "nasdaq_chart"}
    # 互校的正确做法：nasdaq 多值时不能挑一个来比（挑哪个都是 R6 禁止的「偷偷选」）。
    # 改问「yahoo 的值是否落在 nasdaq 的候选区间内」：落在区间内记距离 0，
    # 否则记到最近候选的距离。这样互校结果不依赖我们对候选的任意取舍。
    dist = []
    for t in sorted(set(prim) & set(xchk)):
        cands = xchk[t]["close_candidates"]
        if not cands:
            continue
        v = prim[t]
        if cands[0] <= v <= cands[-1]:
            dist.append(0.0)
        else:
            dist.append(min(abs(v - c) for c in cands))
    rep["xcheck_overlap_minutes"] = len(dist)
    rep["xcheck_max_dist_to_band_usd"] = round(max(dist), 4) if dist else None
    rep["xcheck_minutes_inside_band"] = sum(1 for d in dist if d == 0.0)
    return prim, xchk, rep


def official_close():
    """本日官方收盘价。只认 close_*.json，并重验它不是发行价。"""
    for p in CLOSE_SOURCES:
        if not os.path.exists(p):
            continue
        d = json.load(open(p))
        v = d.get("official_close_usd")
        if v is None or abs(v - ISSUE_PRICE) < 1e-9 or not d.get("finalized"):
            continue
        return {"official_close_usd": v, "from_file": p,
                "path": d["sources"]["nasdaq_info_secondaryData"]["path"],
                "field": d["sources"]["nasdaq_info_secondaryData"]["field"],
                "stamp_src": d.get("regular_close_stamp_src"),
                "cross_check_unanimous": d.get("cross_check_unanimous"),
                "caveat": d.get("caveat")}
    return None


def _dump(rep, tag):
    print("--- %s ---" % tag)
    for k, v in rep.items():
        if k == "files":
            for p, s in v.items():
                print("    %-58s %s" % (os.path.basename(p), s))
        else:
            print("  %-32s %s" % (k, v))


def selftest():
    """自测：六条规则必须各自在真实数据上**生效且可见**。
    任何一条「没命中」都说明数据或代码变了，必须停下来看，不能当通过。"""
    ok = True

    def chk(name, cond, detail):
        nonlocal ok
        print("  [%s] %-44s %s" % ("PASS" if cond else "FAIL", name, detail))
        ok = ok and cond

    print("== selftest ==")
    spot, sr = load_spot()
    chk("R1 并集补回了仓内缺失的行",
        sr["raw"] > 0 and any("新增" in s and not s.startswith("新增 0 ")
                              for p, s in sr["files"].items() if "ant-spot-archive" in p),
        "归档确有仓内没有的行")
    chk("R2 丢弃 previousInfo 伪收盘价", sr["R2_dropped_prevclose_records"] >= 33,
        "丢 %d 条（已登记 36 条）" % sr["R2_dropped_prevclose_records"])
    chk("R3 并写窗口的重复已去掉", sr["R3_dropped_dup_ts_kind"] >= 7,
        "去 %d 条（已登记 7 个同秒双条）" % sr["R3_dropped_dup_ts_kind"])
    chk("R2 后不残留 83.0 冒充收盘价",
        not [r for r in spot if r.get("kind") == "official_close"
             and r.get("official_close_usd") == ISSUE_PRICE],
        "无残留")

    bars, br = load_bars()
    chk("R4 丢弃未修时区的 nasdaq bar", br["R4_dropped_untz_fixed"] >= 90,
        "丢 %d 条（已登记 98 条）" % br["R4_dropped_untz_fixed"])
    chk("R5 丢弃非整分钟的半成品 bar", br["R5_dropped_offgrid_bar"] >= 90,
        "丢 %d 条（实测 94 个 yahoo 半成品）" % br["R5_dropped_offgrid_bar"])
    nu = br["unstable_minutes_by_src"]
    chk("R6 nasdaq_chart 的不稳定被标出而非被选掉",
        nu.get("nasdaq_chart", 0) >= 100,
        "标出 %d 个自相矛盾分钟" % nu.get("nasdaq_chart", 0))
    chk("R6 yahoo_1m 明显更稳",
        nu.get("yahoo_1m", 999) < nu.get("nasdaq_chart", 0) / 10,
        "yahoo %d 个 vs nasdaq %d 个" % (nu.get("yahoo_1m", -1), nu.get("nasdaq_chart", -1)))

    prim, xchk, mr = minute_close_series()
    chk("主序列非空，且与互校源的候选区间不冲突",
        len(prim) > 200 and (mr["xcheck_max_dist_to_band_usd"] or 9) < 0.35,
        "%d 分钟, %d 个落在 nasdaq 候选区间内, 最大越界 $%s"
        % (len(prim), mr["xcheck_minutes_inside_band"], mr["xcheck_max_dist_to_band_usd"]))

    oc = official_close()
    chk("官方收盘价可读且不是发行价",
        oc is not None and abs(oc["official_close_usd"] - ISSUE_PRICE) > 1e-9,
        "$%s via %s" % (oc and oc["official_close_usd"], oc and oc["field"]))

    print("== %s ==" % ("ALL PASS" if ok else "有 FAIL，不要用这份数据直接出结论"))
    return ok


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    load_spot(verbose=True)
    load_bars(verbose=True)
    print()
    print("official_close:", json.dumps(official_close(), ensure_ascii=False, indent=1))
