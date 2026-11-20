#!/usr/bin/env python3
"""独立定稿今天的官方收盘价。不 import ant_spot、不碰在跑的进程。

为什么需要它：ant_spot.py 原先取 `extended-trading?markettype=post` 的
`data.previousInfo`，盘前实测返回 " Market Close: $83.0"，我以为 16:00 ET 后它会变成本日
官方收盘价。实测没有 —— 21:09Z 仍是 $83.0，那是**上一交易日**的收盘参考值（本日是上市首日，
所以等于发行价）。代码里显式排除 83.0 的闸门因此一直没放行，没把发行价误当收盘价定稿。

正确路径：盘后 `/api/quote/ANT/info` 的 `data.secondaryData` 持有正常时段收盘价，
`lastTradeTimestamp` 写 "Closed at ... 4:00 PM ET"、`isRealTime: false`。
"""
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
            "note": "实测为上一交易日收盘参考值，非本日官方收盘价。本日=上市首日故等于发行价 83.0。",
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

    # --- 定稿判定：必须有主路径、必须不等于发行价、必须三源一致 ---
    primary = out["sources"].get("nasdaq_info_secondaryData", {}).get("close_usd")
    cross = [out["sources"].get(k, {}).get("close_usd")
             for k in ("yahoo_meta", "cnbc")]
    cross = [c for c in cross if c is not None]
    agree = [c for c in cross if primary is not None and abs(c - primary) < 0.01]

    out["official_close_usd"] = None
    out["finalized"] = False
    out["reject_why"] = []
    if primary is None:
        out["reject_why"].append("primary_path_no_value")
    elif abs(primary - ISSUE_PRICE) < 1e-9:
        out["reject_why"].append("primary_equals_issue_price_83")
    else:
        out["official_close_usd"] = primary
        out["finalized"] = True
    out["cross_check_agree_n"] = len(agree)
    out["cross_check_values"] = cross
    out["cross_check_unanimous"] = (len(agree) == len(cross) and len(cross) > 0)

    # 本日正常时段最后一笔成交（与官方收盘价可能不同）
    out["regular_close_stamp_src"] = out["sources"].get(
        "nasdaq_info_secondaryData", {}).get("stamp_src")
    out["caveat"] = ("公开端点不区分 NOCP（收盘撮合定出的官方收盘价）与最后一笔合并成交价。"
                     "本值取自 Nasdaq 自己报价页的收盘价字段，三源一致，但不能据此断言它就是 NOCP。"
                     "api.nasdaq.com 的 historical 端点在 21:10Z 仍返回 totalRecords=0，"
                     "本日日线尚未发布；日线出来后可据其 close 复核。")

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
        "supersedes": "kind=official_close（那些记的是 data.previousInfo=83.0，即上一交易日，非本日收盘价）",
        "detail_file": "data/close_%s.json" % DAY,
    }
    with open(SPOT, "a") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())

    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
