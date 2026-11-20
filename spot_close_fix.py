#!/usr/bin/env python3
"""独立定稿今天的官方收盘价。不 import ant_spot、不碰在跑的进程。

为什么需要它：ant_spot.py 原先取 `extended-trading?markettype=post` 的
`data.previousInfo`，盘前实测返回 " Market Close: $83.0"，我以为 16:00 ET 后它会变成本日
官方收盘价。实测没有 —— 21:09Z 仍是 $83.0，那是**上一交易日**的收盘参考值（本日是上市首日，
所以等于发行价）。代码里显式排除 83.0 的闸门因此一直没放行，没把发行价误当收盘价定稿。

正确路径：盘后 `/api/quote/ANT/info` 的 `data.secondaryData` 持有正常时段收盘价，
`lastTradeTimestamp` 写 "Closed at ... 4:00 PM ET"、`isRealTime: false`。
"""
import io
import json, os, time, urllib.request

UA = "ant-research"
DATA = os.path.expanduser("~/ant-convergence/data")

# **日期由 ant_spot.py 推导，不再写死。** 2026-11-20 的教训（数据说明 7.33/7.34）：
# 写死的日期常量在跨日那一刻失效，而失效时产出的东西看起来完全正常。
# 本脚本若在 Nov 20 被运行，初版会把 Nov 20 的收盘价写进 close_2026-11-19.json
# 并打上 trading_day="2026-11-19" —— 一个会直接污染收盘价这个最关键数字的错。
# 用 --day 可覆盖（重跑历史时必须能钉住某一天）。
import sys as _sys
sys_path_added = os.path.expanduser("~/ant-convergence")
if sys_path_added not in _sys.path:
    _sys.path.insert(0, sys_path_added)
if "--day" in _sys.argv:
    DAY = _sys.argv[_sys.argv.index("--day") + 1]
else:
    import ant_spot as _S          # 只为复用它的推导，不启动任何循环
    DAY = _S.TRADING_DAY

SPOT = os.path.join(DATA, "spot_%s.jsonl" % DAY)
CLOSE = os.path.join(DATA, "close_%s.json" % DAY)
ISSUE_PRICE = 83.0
# 同理不写死；若 --day 覆盖了日期，这个值由 ant_spot 的推导给出
REGULAR_CLOSE = None


def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"})
    t0 = time.time()
    raw = urllib.request.urlopen(r, timeout=25).read().decode()
    return json.loads(raw), int((time.time() - t0) * 1000)


def money(s):
    if s is None:
        return None
    s = str(s).replace("$", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _day_shift(day, n):
    """YYYY-MM-DD 加减 n 天。"""
    import datetime
    d = datetime.date.fromisoformat(day) + datetime.timedelta(days=n)
    return d.isoformat()


def _stamp_day(stamp):
    """从 "Closed at Nov 20, 2026 4:00 PM ET" 取出 YYYY-MM-DD;取不到返回 None。"""
    import re
    if not stamp:
        return None
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})", str(stamp))
    if not m:
        return None
    mon = _MONTHS.get(m.group(1))
    if not mon:
        return None
    return "%s-%02d-%02d" % (m.group(3), mon, int(m.group(2)))


def _current_trading_day():
    """当前 ET 交易日 —— 复用 ant_spot 的推导,不启动任何循环。"""
    try:
        import ant_spot as _S2
        return _S2.derive_trading_day()
    except Exception:
        return None


def _supersedes_note():
    """本条取代了当日哪些 kind=official_close 记录 —— 由实测派生。

    初版写死「那些记的是 data.previousInfo=83.0，即上一交易日」——
    那只对 2026-11-19 成立。2026-11-20 起 ant_spot.py 的 official_close()
    已改取 data.secondaryData，当日那些记录记的不是 previousInfo。
    """
    n_total = n_dep = n_sec = 0
    try:
        for ln in io.open(SPOT, errors="replace"):
            ln = ln.strip()
            if not ln:
                continue
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("kind") != "official_close":
                continue
            n_total += 1
            f = str(r.get("official_close_field") or "")
            if "previousInfo" in f or r.get("deprecated_previousInfo_raw") is not None:
                n_dep += 1
            if "secondaryData" in f:
                n_sec += 1
    except Exception as e:
        return "无法统计当日 kind=official_close 记录: %r" % e
    if n_total == 0:
        return "当日无 kind=official_close 记录可取代。"
    return ("取代当日 %d 条 kind=official_close（其中 %d 条取自 "
            "data.secondaryData、%d 条涉及已废弃的 data.previousInfo）。"
            % (n_total, n_sec, n_dep))


def main():
    out = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "t_epoch": round(time.time(), 3),
        "trading_day": DAY,
        "kind": "official_close_final",
        "collector": "spot_close_fix.py",
        "sources": {},
    }

    # --- 主路径：Nasdaq info.secondaryData ---
    try:
        d, ms = get("https://api.nasdaq.com/api/quote/ANT/info?assetclass=stocks")
        sec = (d.get("data") or {}).get("secondaryData") or {}
        pri = (d.get("data") or {}).get("primaryData") or {}
        out["sources"]["nasdaq_info_secondaryData"] = {
            "ok": True, "ms": ms,
            "path": "/api/quote/ANT/info?assetclass=stocks",
            "field": "data.secondaryData.lastSalePrice",
            "close_usd": money(sec.get("lastSalePrice")),
            "raw": sec.get("lastSalePrice"),
            "stamp_src": sec.get("lastTradeTimestamp"),
            "is_realtime_src": sec.get("isRealTime"),
            "net_chg_usd": money(sec.get("netChange")),
            "chg_pct_src": sec.get("percentageChange"),
            "market_status_src": (d.get("data") or {}).get("marketStatus"),
            "day_range_src": ((d.get("data") or {}).get("keyStats") or {}).get("dayrange", {}).get("value"),
            "post_last_usd": money(pri.get("lastSalePrice")),
            "post_stamp_src": pri.get("lastTradeTimestamp"),
            "vol_raw_post_src": pri.get("volume"),
        }
    except Exception as e:
        out["sources"]["nasdaq_info_secondaryData"] = {"ok": False, "err": repr(e)}

    # --- 旧路径留证：previousInfo 到底是什么 ---
    try:
        d, ms = get("https://api.nasdaq.com/api/quote/ANT/extended-trading"
                    "?assetclass=stocks&markettype=post&time=0")
        out["sources"]["nasdaq_extended_post_previousInfo"] = {
            "ok": True, "ms": ms,
            "path": "/api/quote/ANT/extended-trading?markettype=post",
            "field": "data.previousInfo",
            "raw": (d.get("data") or {}).get("previousInfo"),
            "note": "实测为上一交易日收盘参考值，非本日官方收盘价。2026-11-19（上市首日）那天它等于发行价 83.0，因为前一交易日不存在；其余日子它应等于前一交易日的收盘价。本字段只留证，勿用于定稿。",
        }
    except Exception as e:
        out["sources"]["nasdaq_extended_post_previousInfo"] = {"ok": False, "err": repr(e)}

    # --- 互校：Yahoo ---
    try:
        d, ms = get("https://query2.finance.yahoo.com/v8/finance/chart/ANT?range=1d&interval=1m")
        m = d["chart"]["result"][0]["meta"]
        out["sources"]["yahoo_meta"] = {
            "ok": True, "ms": ms,
            "path": "v8/finance/chart/ANT?range=1d&interval=1m",
            "field": "meta.regularMarketPrice",
            "close_usd": m.get("regularMarketPrice"),
            "market_time_src": m.get("regularMarketTime"),
            "market_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime(m.get("regularMarketTime")))
            if m.get("regularMarketTime") else None,
            "prev_close_usd": m.get("chartPreviousClose"),
            "vol_shares_regular": m.get("regularMarketVolume"),
        }
    except Exception as e:
        out["sources"]["yahoo_meta"] = {"ok": False, "err": repr(e)}

    # --- 互校：CNBC ---
    try:
        d, ms = get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
                    "?symbols=ANT&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1"
                    "&output=json&events=1")
        q = d["FormattedQuoteResult"]["FormattedQuote"][0]
        out["sources"]["cnbc"] = {
            "ok": True, "ms": ms,
            "path": "quote.cnbc.com/restQuote",
            "field": "last",
            "close_usd": money(q.get("last")),
            "stamp_src": q.get("last_timedate"),
            "prev_close_usd": money(q.get("previous_day_closing")),
            "vol_raw_src": q.get("volume"),
        }
    except Exception as e:
        out["sources"]["cnbc"] = {"ok": False, "err": repr(e)}

    # --- 互校：Nasdaq 自己的日线（T+1 填充）---
    # 7.9 的 caveat 写过「日线出来后可据其 close 复核」。2026-11-20 实测:
    # 11-19 的日线已出,open/high/low/close = 111.50/115.10/92.72/97.17,
    # 与本路已有的数四项全对上。于是让定稿器自己去查 —— 当日跑通常取不到
    # （T+1），但隔日重跑这条就是裁决者。
    try:
        # **fromdate==todate 实测返回零行**（totalRecords=None, rows=0）。
        # 必须给一个严格更宽的窗口再按日期过滤 —— 否则用最自然的单日查询
        # 去复核某一天，会拿到空结果，而空结果很容易被读成「权威源没有这天」。
        _lo = _day_shift(DAY, -1)
        _hi = _day_shift(DAY, +1)
        d, ms = get("https://api.nasdaq.com/api/quote/ANT/historical"
                    "?assetclass=stocks&fromdate=%s&todate=%s&limit=10"
                    % (_lo, _hi))
        dd = (d.get("data") or {})
        rows = ((dd.get("tradesTable") or {}).get("rows")) or []
        mm, dd2, yy = DAY[5:7], DAY[8:10], DAY[0:4]
        want = "%s/%s/%s" % (mm, dd2, yy)
        hit = [r for r in rows if want in str(r.get("date"))]
        out["sources"]["nasdaq_historical"] = {
            "ok": True, "ms": ms,
            "path": "/api/quote/ANT/historical",
            "field": "tradesTable.rows[date=%s]" % want,
            "totalRecords": dd.get("totalRecords"),
            "row_present": bool(hit),
            "close_usd": money(hit[0].get("close")) if hit else None,
            "open_usd": money(hit[0].get("open")) if hit else None,
            "high_usd": money(hit[0].get("high")) if hit else None,
            "low_usd": money(hit[0].get("low")) if hit else None,
            "volume_raw": hit[0].get("volume") if hit else None,
            "note": ("日线按 T+1 填充;当日定稿时通常 row_present=false。"
                     "隔日重跑本脚本即可用它裁决。"),
        }
    except Exception as e:
        out["sources"]["nasdaq_historical"] = {"ok": False, "err": repr(e)}

    # --- 定稿判定：口径闸门 + 互校；发行价只告警不拒收（7.45）---
    primary = out["sources"].get("nasdaq_info_secondaryData", {}).get("close_usd")
    cross = [out["sources"].get(k, {}).get("close_usd")
             for k in ("yahoo_meta", "cnbc")]
    cross = [c for c in cross if c is not None]
    agree = [c for c in cross if primary is not None and abs(c - primary) < 0.01]

    out["official_close_usd"] = None
    out["finalized"] = False
    out["reject_why"] = []
    out["warn"] = []

    # **口径闸门。** 初版只守 primary != 83.0,而它记录 stamp_src 却从不检查 ——
    # 守的是一个具体数字,不是口径。真正该守的是「这个值是不是已收盘的值」:
    # 盘中 secondaryData 可能为空或为盘前值(ant_spot.py 的 closed_ok 守的就是这个)。
    _stamp = out["sources"].get("nasdaq_info_secondaryData", {}).get("stamp_src")
    closed_ok = bool(_stamp) and "Closed" in str(_stamp)
    out["primary_stamp_says_closed"] = closed_ok

    # **日期匹配闸门。** 实时端点永远返回「最近一个已收盘的交易日」,
    # 而 --day 的标签由人给。两者不一致时,初版会把今天的收盘价写进
    # 过去某一天的文件并打上那天的 trading_day —— 正是本文件头注警告过的错,
    # 修法只把写死改成派生,没堵住这个覆盖口。沙箱实测:
    # `--day 2026-11-19` 在 11-20 跑,产出 88.91 而 trading_day 标 2026-11-19。
    out["primary_stamp_day"] = _stamp_day(_stamp)
    stamp_day_ok = (out["primary_stamp_day"] == DAY)
    out["primary_stamp_day_matches_trading_day"] = stamp_day_ok

    # 过去的日子只能用日线定稿 —— 实时报价与那一天无关。
    _today = _current_trading_day()
    out["current_trading_day_at_run"] = _today
    is_past = bool(_today) and DAY != _today
    out["is_past_day_rerun"] = is_past
    _h0 = out["sources"].get("nasdaq_historical", {})
    if is_past:
        out["primary_source_used"] = "nasdaq_historical"
        primary = _h0.get("close_usd")
    else:
        out["primary_source_used"] = "nasdaq_info_secondaryData"

    # **发行价:告警,不拒收(7.45)。** 新路径返回的是本日真实收盘价,
    # 83.00 在其上是一个合法价格;原闸门只剩误伤 —— 某日正好收在 83.00
    # 就永久拒收该日收盘价。2026-11-20 实测日内低点 83.05,距 83.00 仅 $0.05,
    # 风险不再是假想的。
    if primary is not None and abs(primary - ISSUE_PRICE) < 1e-9:
        out["warn"].append("close_equals_issue_price_83_coincidence")

    if primary is None:
        out["reject_why"].append(
            "historical_row_missing_for_past_day" if is_past
            else "primary_path_no_value")
    elif is_past:
        # 日线这条路径不经实时戳,所以只需要行存在且日期对
        if not _h0.get("row_present"):
            out["reject_why"].append("historical_row_missing_for_past_day")
        else:
            out["official_close_usd"] = primary
            out["finalized"] = True
    elif not closed_ok:
        out["reject_why"].append("primary_stamp_not_closed")
    elif not stamp_day_ok:
        out["reject_why"].append(
            "primary_stamp_day_%s_!=_trading_day_%s"
            % (out["primary_stamp_day"], DAY))
    else:
        out["official_close_usd"] = primary
        out["finalized"] = True
    if is_past:
        # **过去某天重跑:实时互校源与那一天无关,不得参与。**
        # 否则一次正确的日线定稿会显示 cross_check_dissenters=[yahoo,cnbc],
        # 看起来像一比三 —— 而那两个值是今天的。
        out["cross_check_agree_n"] = 0
        out["cross_check_values"] = []
        out["cross_check_unanimous"] = None
        out["cross_check_note"] = (
            "过去某天重跑:主路径为 Nasdaq 日线;yahoo / cnbc / 报价页均为实时端点，"
            "返回的是运行当日的值，与 %s 无关，故不参与互校（其原始值仍留在 sources 里备查）。"
            % DAY)
    else:
        out["cross_check_agree_n"] = len(agree)
        out["cross_check_values"] = cross
        out["cross_check_unanimous"] = (len(agree) == len(cross) and len(cross) > 0)
    # 哪一源异议要能指名 —— 2026-11-20 实测 cnbc 报 88.30 而
    # nasdaq secondaryData 与 yahoo regularMarketPrice 都报 88.91,差 $0.61。
    # 三次重取 cnbc 的 last 稳定在 88.30、戳固定 16:00:00-0500,
    # 所以那不是「实时价贴了收盘标签」,是真异议。
    out["cross_check_by_source"] = {
        k: {"close_usd": out["sources"].get(k, {}).get("close_usd"),
            "field": out["sources"].get(k, {}).get("field"),
            # 「没有值」不是「异议」—— close_usd 为 None 时 agrees 置 None,
            # 否则日线在当日(T+1 未填充)会显示 agrees:false,被读成它在反对。
            "agrees": (None
                       if (out["sources"].get(k, {}).get("close_usd") is None
                           or primary is None)
                       else abs(out["sources"][k]["close_usd"] - primary) < 0.01)}
        for k in ("yahoo_meta", "cnbc", "nasdaq_historical")
    }
    out["cross_check_dissenters"] = ([] if is_past else [
        k for k, v in out["cross_check_by_source"].items()
        if v["close_usd"] is not None and not v["agrees"]])

    # 本日正常时段最后一笔成交（与官方收盘价可能不同）
    if is_past:
        # 实时戳指向运行当日,与 DAY 矛盾 —— 过去某天用日线自己的日期。
        out["regular_close_stamp_src"] = "Nasdaq 日线 date=%s（%s）" % (
            _h0.get("field"), "row_present" if _h0.get("row_present") else "行缺失")
        out["live_quote_stamp_at_run"] = out["sources"].get(
            "nasdaq_info_secondaryData", {}).get("stamp_src")
    else:
        out["regular_close_stamp_src"] = out["sources"].get(
            "nasdaq_info_secondaryData", {}).get("stamp_src")
    # **caveat 由实测派生，不写死。** 初版把「historical 仍返回 totalRecords=0」
    # 写进了字符串 —— 那是 2026-11-19 当天的事实，T+1 之后就不成立了。
    _h = out["sources"].get("nasdaq_historical", {})
    _hist = ("Nasdaq 日线已发布，其 close = %s（%s）。"
             % (_h.get("close_usd"),
                "与本值一致" if (_h.get("close_usd") is not None
                               and primary is not None
                               and abs(_h["close_usd"] - primary) < 0.01)
                else "**与本值不一致，须查**")
             ) if _h.get("row_present") else (
        "Nasdaq 日线尚未发布本日行（row_present=false，按 T+1 填充；"
        "查询窗口 %s..%s 内共 %s 行，那些是更早的交易日）；"
        "隔日重跑本脚本即可据其 close 裁决。"
        % (_day_shift(DAY, -1), _day_shift(DAY, 1), _h.get("totalRecords")))
    _unan = ("互校一致。" if out["cross_check_unanimous"]
             else "**互校不一致，异议源：%s。**" % (out["cross_check_dissenters"] or "—"))
    if is_past:
        out["caveat"] = (
            "公开端点不区分 NOCP（收盘撮合定出的官方收盘价）与最后一笔合并成交价。"
            "本值取自 Nasdaq 自己的日线记录（历史端点），那是场所自己的日终记录，"
            "比报价页是更强的出处；但日线的 close 字段同样没有标明它是不是 NOCP。"
            "本次为过去某天重跑：实时端点（报价页 / yahoo / cnbc）返回的是运行当日 %s 的值，"
            "已排除在互校之外。%s"
            % (out.get("current_trading_day_at_run"),
               ("日线同时给出 open=%s high=%s low=%s volume=%s。"
                % (_h0.get("open_usd"), _h0.get("high_usd"),
                   _h0.get("low_usd"), _h0.get("volume_raw")))
               if _h0.get("row_present") else ""))
    else:
        out["caveat"] = ("公开端点不区分 NOCP（收盘撮合定出的官方收盘价）与最后一笔合并成交价。"
                         "本值取自 Nasdaq 自己报价页的收盘价字段（戳 says_closed=%s），"
                         "不能据此断言它就是 NOCP。%s%s"
                         % (closed_ok, _unan, _hist))

    with open(CLOSE, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.flush(); os.fsync(f.fileno())

    # 向 spot_*.jsonl 追加一条精简记录（不嵌 cross_check，保证单次 write 足够小、
    # 与在跑的 ant_spot.py 的 O_APPEND 写入不会撕裂）
    line = {
        "ts": out["ts"], "t_epoch": out["t_epoch"], "trading_day": DAY,
        "kind": "official_close_final", "collector": "spot_close_fix.py",
        "pid": os.getpid(),
        "official_close_usd": out["official_close_usd"],
        "finalized": out["finalized"],
        "official_close_path": "/api/quote/ANT/info?assetclass=stocks",
        "official_close_field": "data.secondaryData.lastSalePrice",
        "official_close_stamp_src": out["regular_close_stamp_src"],
        "cross_check_values": cross,
        "cross_check_unanimous": out["cross_check_unanimous"],
        "supersedes": _supersedes_note(),
        "detail_file": "data/close_%s.json" % DAY,
    }
    with open(SPOT, "a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())

    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
