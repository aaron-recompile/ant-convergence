#!/usr/bin/env python3
"""Nasdaq ANT 现货高保真独立采集器。

与 collector.py 完全独立：不 import 它、不修改它、不共享任何状态或文件。
逻辑有意重复一份（占位价判定等），宁可重复代码也不要耦合 —— 一边改坏不能带倒另一边。

输出（append-only，永不回改）：
  data/spot_<YYYY-MM-DD>.jsonl     每次快照一条，多源并列
  data/minbars_<YYYY-MM-DD>.jsonl  分钟 K 线，去重后增量追加
  data/close_<YYYY-MM-DD>.json     收盘官方价汇总（唯一会被覆盖写的文件，且只在收盘后写）

单位口径一律在入库时归一，字段名自带口径后缀：
  *_usd    美元
  *_shares 股数
  *_pct    百分数（12.13 表示 +12.13%）
  *_frac   比率（0.1213 表示 +12.13%）
拿不准的口径同时存原值与换算，并在 data/数据说明.md 里注明未核实。
"""
import json, os, sys, time, calendar, subprocess, threading, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA   = "ant-research"

# ── 交易时段边界（2026-11-19，EST = UTC-5）────────────────────────
# 下面两个常量已与 Yahoo 自报的 currentTradingPeriod.regular 对上：
# start 1795098600 / end 1795122000，两边完全一致，故采用。
TRADING_DAY   = "2026-11-19"
REGULAR_OPEN  = 1795098600          # 2026-11-19T14:30:00Z = 09:30 ET
REGULAR_CLOSE = 1795122000          # 2026-11-19T21:00:00Z = 16:00 ET
POST_CLOSE    = 1795136400          # 2026-11-20T01:00:00Z = 20:00 ET

ISSUE_PRICE = 83.0                  # 发行价。首笔成交前多个源把它当行情占位回传。

# 取数路径 → URL。字段里会记 path，方便事后按来路区分口径。
EP = {
    "nasdaq_info":    "https://api.nasdaq.com/api/quote/ANT/info?assetclass=stocks",
    "nasdaq_summary": "https://api.nasdaq.com/api/quote/ANT/summary?assetclass=stocks",
    "nasdaq_chart":   "https://api.nasdaq.com/api/quote/ANT/chart?assetclass=stocks",
    "nasdaq_nls":     "https://api.nasdaq.com/api/quote/ANT/realtime-trades?&limit=20&fromTime=09:30",
    "nasdaq_post":    "https://api.nasdaq.com/api/quote/ANT/extended-trading?assetclass=stocks&markettype=post",
    "yahoo_1m":       "https://query2.finance.yahoo.com/v8/finance/chart/ANT?range=1d&interval=1m",
    "cnbc":           ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
                       "?symbols=ANT&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json"),
}


# ── 基础工具 ─────────────────────────────────────────────────────
def now_s():
    return time.time()


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def session_of(ts):
    """市场时段。由本地时钟判定，与各源自报的 state 分开存，便于互校。"""
    if ts < REGULAR_OPEN:    return "pre"
    if ts < REGULAR_CLOSE:   return "regular"
    if ts < POST_CLOSE:      return "post"
    return "closed"


def num(x):
    """'$1,234.5' / '12.30%' / 'N/A' → float / None。只做清洗，不做换算。"""
    if x is None:               return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("$", "").replace(",", "").replace("%", "").strip()
    if s in ("", "N/A", "NA", "--", "unch", "None"): return None
    try:                        return float(s)
    except Exception:           return None


def get(key, timeout=10):
    """mini 上没有代理，直连为唯一通路；urllib 失败再用一次 curl 兜底。
    返回 (data, meta)。meta 里记 ok / via / ms / err，便于事后判采集质量。"""
    url = EP[key]
    t0  = now_s()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        d   = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
        return d, {"ok": True, "via": "urllib", "ms": round((now_s() - t0) * 1000)}
    except Exception as e:
        err = "%s: %s" % (type(e).__name__, e)
    try:
        out = subprocess.run(["curl", "-s", "-m", str(timeout), "-A", UA, url],
                             capture_output=True, timeout=timeout + 4).stdout.decode()
        d   = json.loads(out)
        return d, {"ok": True, "via": "curl", "ms": round((now_s() - t0) * 1000),
                   "urllib_err": err}
    except Exception as e2:
        return None, {"ok": False, "via": "fail", "ms": round((now_s() - t0) * 1000),
                      "err": err, "curl_err": "%s: %s" % (type(e2).__name__, e2)}


# ── 占位价判定（本文件自己实现一遍，比 collector.py 更严）──────────
# collector.py 里的判定被咬过两次（见 data/数据说明.md 第 2 条）：
#   · yahoo  四值相等且无量 → 已拦住
#   · cnbc   price=prev_close 但 open/high/low 是当日真数 → 没拦住，$83 配 traded=true 入库
# 这里改成「任一条命中即占位」，并记下命中的理由，不靠单一组合条件。
def placeholder_check(price, prev_close, vol_shares, snap_date_ok, day_hi=None, day_lo=None):
    """返回 (placeholder: bool, reasons: [str])。price 为 None 时不判占位。"""
    r = []
    if price is None:
        return False, r
    no_vol = (vol_shares is None) or (vol_shares == 0)
    if prev_close is not None and abs(price - prev_close) < 1e-9 and no_vol:
        r.append("price==prev_close_and_no_volume")
    if abs(price - ISSUE_PRICE) < 1e-9 and no_vol:
        r.append("price==issue_price_83_and_no_volume")
    if snap_date_ok is False:
        r.append("snapshot_last_trade_date_not_today")
    # 本日特有的加严项：ANT 全天区间 92.72–114.99，发行价 83 永远不可能是当日成交价。
    # 一旦某源又把 83 当行情回传（即便它带上了量），也拦下来。
    if abs(price - ISSUE_PRICE) < 1e-9:
        r.append("price==issue_price_83")
    if (prev_close is not None and abs(price - prev_close) < 1e-9
            and day_hi is not None and day_lo is not None
            and not (day_lo <= prev_close <= day_hi)):
        r.append("price==prev_close_outside_day_range")
    return (len(r) > 0), r


def date_is_today(s):
    """源自报的最后成交日期是否为本交易日。
    认得两种写法：'Nov 19, 2026 1:18 PM ET'（nasdaq）、'11/19/26 EST'（cnbc）。
    看不懂的写法返回 None（不作为占位依据，也不作为清白依据）。"""
    if not s:
        return None
    s = str(s)
    y, m, d = TRADING_DAY.split("-")
    mon = time.strftime("%b", time.strptime(m, "%m"))          # '11' → 'Nov'
    if ("%s %d, %s" % (mon, int(d), y)) in s:                  # nasdaq 写法
        return True
    if ("%s/%s/%s" % (m, d, y[2:])) in s:                      # cnbc 写法 11/19/26
        return True
    if mon in s or "/" in s:                                   # 认得格式但日期不对
        return False
    return None


# ── 各源解析。每个都返回扁平 dict，字段名自带口径 ───────────────────
def parse_nasdaq_info(d, meta):
    dd = (d or {}).get("data") or {}
    p  = dd.get("primaryData") or {}
    if not dd.get("symbol"):
        return {"ok": False, "path": "/api/quote/ANT/info", **meta}

    px   = num(p.get("lastSalePrice"))
    bid  = num(p.get("bidPrice"))
    ask  = num(p.get("askPrice"))
    volf = num(p.get("volume"))                 # 实测带小数，见 数据说明.md
    lts  = p.get("lastTradeTimestamp") or None
    dok  = date_is_today(lts)

    # 当日高低来自 keyStats.dayrange，形如 '92.72 - 114.99'
    rng  = (((dd.get("keyStats") or {}).get("dayrange") or {}).get("value") or "")
    hi = lo = None
    if "-" in rng:
        parts = [num(x) for x in rng.split("-")]
        if len(parts) == 2 and None not in parts:
            lo, hi = min(parts), max(parts)

    ph, why = placeholder_check(px, ISSUE_PRICE, volf, dok, hi, lo)
    # bid==ask 且未成交 → 集合竞价指示价，不是盘口。不标出来会被当买卖价读错。
    cross = bool(bid is not None and ask is not None and abs(bid - ask) < 1e-9
                 and (px is None or ph))
    return {
        "ok": True, "path": "/api/quote/ANT/info", "src": "nasdaq", **meta,
        "price_usd":       None if ph else px,
        "quoted_usd":      px,                      # 原值，占位时也保留
        "placeholder":     ph,
        "placeholder_why": why,
        "bid_usd": bid, "ask_usd": ask,
        "spread_usd":  None if (bid is None or ask is None or cross) else round(ask - bid, 6),
        "indicative_cross":   cross,
        "indicative_price_usd": bid if cross else None,
        # 盘口挂单量口径未核实：Nasdaq 未说明是股数还是手（100 股）。两种都存。
        "bid_size_raw": num(p.get("bidSize")), "ask_size_raw": num(p.get("askSize")),
        "bid_size_shares_if_round_lots": (None if num(p.get("bidSize")) is None
                                          else num(p.get("bidSize")) * 100),
        "ask_size_shares_if_round_lots": (None if num(p.get("askSize")) is None
                                          else num(p.get("askSize")) * 100),
        "size_unit_verified": False,
        # 成交量：此路径实测带小数，原样存，不取整、不与其它路径混用
        "vol_shares_info": volf,
        "vol_raw_info":    p.get("volume"),
        "chg_pct":  num(p.get("percentageChange")),
        "chg_frac": (None if num(p.get("percentageChange")) is None
                     else num(p.get("percentageChange")) / 100.0),
        "net_chg_usd": num(p.get("netChange")),
        "day_high_usd": hi, "day_low_usd": lo,
        "last_trade_ts_src": lts,
        "last_trade_date_is_today": dok,
        "state_src": dd.get("marketStatus"),
        "realtime_src": p.get("isRealTime"),
        "traded": bool(px is not None and not ph),
    }


def parse_nasdaq_summary(d, meta):
    sd = ((d or {}).get("data") or {}).get("summaryData") or {}
    ba = ((d or {}).get("data") or {}).get("bidAsk") or {}
    if not sd:
        return {"ok": False, "path": "/api/quote/ANT/summary", **meta}

    def v(k):
        return (sd.get(k) or {}).get("value")

    hl = v("TodayHighLow") or ""
    hi = lo = None
    if "/" in hl:
        parts = [num(x) for x in hl.split("/")]
        if len(parts) == 2 and None not in parts:
            lo, hi = min(parts), max(parts)
    return {
        "ok": True, "path": "/api/quote/ANT/summary", "src": "nasdaq", **meta,
        "vol_shares_summary": num(v("ShareVolume")),   # 实测亦带小数
        "vol_raw_summary":    v("ShareVolume"),
        "prev_close_usd":     num(v("PreviousClose")),
        "day_high_usd": hi, "day_low_usd": lo,
        "market_cap_usd":     num(v("MarketCap")),
        "bid_ask_raw": {"bid": (ba.get("Bid * Size") or {}).get("value"),
                        "ask": (ba.get("Ask * Size") or {}).get("value")},
    }


def parse_nasdaq_nls(d, meta):
    """Nasdaq Last Sale Plus。实测本号 rows 为空（'Real-Time trades not available'，
    需授权），拿不到逐笔；但 topTable 的 nlsVolume / todayHighLow 仍是一路独立口径。"""
    dd = (d or {}).get("data") or {}
    tt = (dd.get("topTable") or {}).get("rows") or []
    row = tt[0] if tt else {}
    hl  = row.get("todayHighLow") or ""
    hi = lo = None
    if "/" in hl:
        parts = [num(x) for x in hl.split("/")]
        if len(parts) == 2 and None not in parts:
            lo, hi = min(parts), max(parts)
    return {
        "ok": True, "path": "/api/quote/ANT/realtime-trades", "src": "nasdaq", **meta,
        "vol_shares_nls":  num(row.get("nlsVolume")),
        "prev_close_usd":  num(row.get("previousClose")),
        # 注意：此口径的高低只含盘中连续交易，明确排除盘前盘后（接口自己写明）
        "day_high_rth_usd": hi, "day_low_rth_usd": lo,
        "tick_rows": len(dd.get("rows") or []),
        "tick_available": bool(dd.get("rows")),
        "api_message": (d or {}).get("message"),
        "data_last_updated_src": (dd.get("message") or [None, None])[-1]
                                 if isinstance(dd.get("message"), list) else None,
    }


def parse_yahoo(d, meta):
    r = (((d or {}).get("chart") or {}).get("result") or [])
    if not r:
        return {"ok": False, "path": "v8/finance/chart/ANT", **meta}
    m   = r[0].get("meta") or {}
    px  = num(m.get("regularMarketPrice"))
    pc  = num(m.get("chartPreviousClose"))
    hi  = num(m.get("regularMarketDayHigh"))
    lo  = num(m.get("regularMarketDayLow"))
    vol = num(m.get("regularMarketVolume"))
    ph, why = placeholder_check(px, pc, vol, None, hi, lo)
    return {
        "ok": True, "path": "v8/finance/chart/ANT?interval=1m", "src": "yahoo", **meta,
        "price_usd":  None if ph else px,
        "quoted_usd": px,
        "placeholder": ph, "placeholder_why": why,
        "prev_close_usd": pc,
        "vol_shares_yahoo": vol,
        "day_high_usd": hi, "day_low_usd": lo,
        "chg_pct":  num(m.get("regularMarketChangePercent")),
        "chg_frac": (None if num(m.get("regularMarketChangePercent")) is None
                     else num(m.get("regularMarketChangePercent")) / 100.0),
        "market_time_src": m.get("regularMarketTime"),
        "market_time_utc": (iso(m["regularMarketTime"])
                            if isinstance(m.get("regularMarketTime"), int) else None),
        "state_src": m.get("marketState"),
        "n_bars": len(r[0].get("timestamp") or []),
        "traded": bool(px is not None and not ph),
    }


def parse_cnbc(d, meta):
    q = (((d or {}).get("FormattedQuoteResult") or {}).get("FormattedQuote") or [])
    if not q:
        return {"ok": False, "path": "quote.cnbc.com/restQuote", **meta}
    t  = q[0]
    px = num(t.get("last"))
    o, hi, lo = num(t.get("open")), num(t.get("high")), num(t.get("low"))
    pc = num(t.get("previous_day_closing"))
    ld = t.get("last_timedate")
    dok = date_is_today(ld)
    # CNBC 曾把 prev_close 当 price 回传，而 open/high/low 是当日真数（数据说明 2.3）。
    # 这里不再用「四值相等」做判定，改用上面的多条规则。
    ph, why = placeholder_check(px, pc, num(t.get("volume")), dok, hi, lo)
    return {
        "ok": True, "path": "quote.cnbc.com/restQuote", "src": "cnbc", **meta,
        "price_usd":  None if ph else px,
        "quoted_usd": px,
        "placeholder": ph, "placeholder_why": why,
        "open_usd": o, "day_high_usd": hi, "day_low_usd": lo,
        "prev_close_usd": pc,
        "vol_shares_cnbc": num(t.get("volume")),
        "last_timedate_src": ld,
        "last_trade_date_is_today": dok,
        "state_src": t.get("curmktstatus"),
        "traded": bool(px is not None and not ph),
    }


# ── 分钟 K 线 ────────────────────────────────────────────────────
_seen_bars = {}          # (src, bar_ts) → 最后写出的值，用于增量去重
_MISSING = object()       # 占位价 bar 的 close_usd 本身就是 None，不能用 None 当「没见过」


def load_seen_bars(path):
    """重启后先把已写出的 bar 读回来，避免重复追加同一条。"""
    if not os.path.exists(path):
        return
    with open(path) as f:
        for ln in f:
            try:
                b = json.loads(ln)
                _seen_bars[(b.get("src"), b.get("bar_ts"))] = b.get("close_usd")
            except Exception:
                pass


# Nasdaq chart 的 x 字段不是 UTC 毫秒，而是把 ET 墙上时间当成 UTC 编码的。
# 实测：x=1795088880000 解成 11:48:00Z，而它自带的标签写的是 "11:48 AM ET"（真 UTC 应为 16:48Z）。
# 用 +18000s 对齐后与 Yahoo 同一分钟的收盘价 96/96 条差 < $0.60；不加偏移则零条重合。
# 故偏移确为 EST 的 5 小时。注意这是 EST 定值，跨到夏令时（EDT）须改为 14400。
ET_TO_UTC_OFFSET = 18000


def bars_nasdaq(d):
    out = []
    for c in ((d or {}).get("data") or {}).get("chart") or []:
        x = c.get("x")
        y = num(c.get("y"))
        if not isinstance(x, int) or y is None:
            continue
        raw = x // 1000
        out.append({"src": "nasdaq_chart", "bar_ts": raw + ET_TO_UTC_OFFSET,
                    "close_usd": y,
                    "bar_ts_raw_src": raw,          # 接口原值，未加偏移
                    "tz_fix_applied": True,         # 本行时间戳已修正为真 UTC
                    "label_src": (c.get("z") or {}).get("dateTime")})
    return out


def bars_yahoo(d):
    r = (((d or {}).get("chart") or {}).get("result") or [])
    if not r:
        return []
    ts = r[0].get("timestamp") or []
    q  = ((r[0].get("indicators") or {}).get("quote") or [{}])[0]
    pc = num((r[0].get("meta") or {}).get("chartPreviousClose"))
    out = []
    for i, t in enumerate(ts):
        def g(k):
            v = (q.get(k) or [])
            return num(v[i]) if i < len(v) else None
        cl, vo = g("close"), g("volume")
        if cl is None:
            continue
        ph, why = placeholder_check(cl, pc, vo, None)
        out.append({"src": "yahoo_1m", "bar_ts": t,
                    "close_usd": None if ph else cl, "quoted_usd": cl,
                    "open_usd": g("open"), "high_usd": g("high"), "low_usd": g("low"),
                    "vol_shares": vo, "placeholder": ph, "placeholder_why": why})
    return out


def write_bars(path, bars, fetched_at):
    n = 0
    with open(path, "a") as f:
        for b in bars:
            k = (b["src"], b["bar_ts"])
            if _seen_bars.get(k, _MISSING) == b.get("close_usd"):
                continue              # 该分钟值没变，不重复写
            _seen_bars[k] = b.get("close_usd")
            rec = {"fetched_at": iso(fetched_at), "bar_ts_utc": iso(b["bar_ts"]),
                   "trading_day": TRADING_DAY, **b}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
        f.flush(); os.fsync(f.fileno())
    return n


# ── 一次快照 ─────────────────────────────────────────────────────
_last = {}


def due(key, every):
    t = now_s()
    if t - _last.get(key, 0) >= every:
        _last[key] = t
        return True
    return False


def _head(t, kind):
    # pid 必须进记录：两个进程并存时，只有 pid 能把两份序列分开。
    # 本日 18:31–18:33 就发生过一次（守护换代时旧进程没停干净），见 数据说明.md。
    return {"ts": iso(t), "t_epoch": round(t, 3), "trading_day": TRADING_DAY,
            "session": session_of(t), "kind": kind,
            "collector": "ant_spot.py", "host": os.uname().nodename, "pid": os.getpid()}


def _with_best(rec):
    """派生：跨源一致的最优成交价。只取已通过占位判定的源，优先交易所自家接口。"""
    for k in ("nasdaq_info", "yahoo", "cnbc"):
        s = rec.get(k) or {}
        if s.get("ok") and s.get("price_usd") is not None and not s.get("placeholder"):
            rec["best"] = {"price_usd": s["price_usd"], "from": k}
            return rec
    rec["best"] = None
    return rec


def snapshot_quote():
    """快路：只取 Nasdaq 自家 info 一个端点，保证现货序列的密度。
    其余端点一律不在这条路上取 —— 它们的延迟会把采样间隔拖到十几秒。"""
    t = now_s()
    rec = _head(t, "quote")
    d, m = get("nasdaq_info", timeout=6)
    rec["nasdaq_info"] = parse_nasdaq_info(d, m)
    return _with_best(rec)


def snapshot(full=False):
    """慢路/全量：多源横截面，供互校与肉眼核对。记录形状与快路一致，
    各源都是可选键，所以两条路写进同一个文件不构成 schema 变化。"""
    t = now_s()
    rec = _head(t, "multi" if not full else "sample")

    if full or due("info_slow", 15):
        d, m = get("nasdaq_info")
        rec["nasdaq_info"] = parse_nasdaq_info(d, m)
    if full or due("summary", 30):
        d, m = get("nasdaq_summary")
        rec["nasdaq_summary"] = parse_nasdaq_summary(d, m)
    if full or due("nls", 60):
        d, m = get("nasdaq_nls")
        rec["nasdaq_nls"] = parse_nasdaq_nls(d, m)
    if full or due("yahoo", 15):
        d, m = get("yahoo_1m")
        rec["yahoo"] = parse_yahoo(d, m)
    if full or due("cnbc", 15):
        d, m = get("cnbc")
        rec["cnbc"] = parse_cnbc(d, m)
    return _with_best(rec)


def official_close():
    """本日官方收盘价。

    **2026-11-19 实测更正。** 初版取 `extended-trading?markettype=post` 的
    `data.previousInfo`，依据是盘前 `markettype=pre` 时该字段为
    `' Market Close: $83.0'`，我据此推断盘后它会变成本日收盘价。**错了。**
    21:09Z 实测它仍是 `' Market Close: $83.0'` —— 那是**上一交易日**的收盘参考值
    （本日为上市首日，故等于发行价 83.0），收盘后也不更新为本日值。
    代码里显式排除 83.0 的那道闸门因此一直没放行，没有把发行价误当收盘价定稿。

    正确路径：盘后 `/api/quote/ANT/info` 的 `data.secondaryData` 持有本日正常时段收盘价，
    `lastTradeTimestamp` 形如 `"Closed at Nov 19, 2026 4:00 PM ET"`。
    （盘中时 secondaryData 为空或为盘前值，故此路径只在 marketStatus=After-Hours 后可用。）
    `primaryData` 此时是盘后最新成交。

    注意：公开端点不区分 NOCP（收盘撮合定出的官方收盘价）与最后一笔合并成交价，
    故本值只断言「Nasdaq 报价页给出的本日收盘价」，并带 yahoo/cnbc 互校。
    """
    t = now_s()
    d, m = get("nasdaq_info")
    dd   = (d or {}).get("data") or {}
    sec  = dd.get("secondaryData") or {}
    pri  = dd.get("primaryData") or {}
    nocp = num(sec.get("lastSalePrice"))
    stamp = sec.get("lastTradeTimestamp")
    # 必须是「已收盘」的那个字段，否则不认：盘中 secondaryData 可能是盘前值
    closed_ok = bool(stamp) and "Closed" in str(stamp)
    if not closed_ok:
        nocp = None

    # 旧路径留证，便于以后的人看到它到底返回什么，不必再踩一遍
    prev_raw, prev_m = None, None
    try:
        d2, prev_m = get("nasdaq_post")
        prev_raw = ((d2 or {}).get("data") or {}).get("previousInfo")
    except Exception:
        pass

    return {
        "ts": iso(t), "t_epoch": round(t, 3), "trading_day": TRADING_DAY,
        "kind": "official_close", "collector": "ant_spot.py",
        "session": session_of(t),
        "official_close_usd": nocp,
        "official_close_raw": sec.get("lastSalePrice"),
        "official_close_path": "/api/quote/ANT/info?assetclass=stocks",
        "official_close_field": "data.secondaryData.lastSalePrice",
        "official_close_stamp_src": stamp,
        "official_close_stamp_says_closed": closed_ok,
        "official_close_is_realtime_src": sec.get("isRealTime"),
        "official_close_net_chg_usd": num(sec.get("netChange")),
        "official_close_chg_pct_src": sec.get("percentageChange"),
        "market_status_src": dd.get("marketStatus"),
        "post_last_usd": num(pri.get("lastSalePrice")),
        "post_stamp_src": pri.get("lastTradeTimestamp"),
        # 旧路径（已证伪，仅留证）
        "deprecated_previousInfo_raw": prev_raw,
        "deprecated_previousInfo_path": "/api/quote/ANT/extended-trading?markettype=post",
        "deprecated_previousInfo_note": "上一交易日收盘参考值，非本日官方收盘价。勿用。",
        "fetch": m,
        "fetch_deprecated_path": prev_m,
        "cross_check": snapshot(full=True),
    }


# ── 对外：肉眼核对用 ──────────────────────────────────────────────
def sample():
    return snapshot(full=True)


# ── 主循环 ───────────────────────────────────────────────────────
SPOT_PATH  = os.path.join(DATA, "spot_%s.jsonl" % TRADING_DAY)
BARS_PATH  = os.path.join(DATA, "minbars_%s.jsonl" % TRADING_DAY)
CLOSE_PATH = os.path.join(DATA, "close_%s.json" % TRADING_DAY)

_wlock = threading.Lock()


def emit(rec):
    """所有线程都经这里写 spot 文件。一行一条，写完即 fsync，断电不丢已落的记录。"""
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with _wlock:
        with open(SPOT_PATH, "a") as f:
            f.write(line)
            f.flush(); os.fsync(f.fileno())


def loop_quote():
    """快路线程：密集的 Nasdaq 现货序列。收盘前后 10 分钟加密到 2 秒。"""
    n = 0
    while True:
        t_round_start = now_s()
        try:
            rec = snapshot_quote()
            emit(rec)
            n += 1
            if n % 100 == 0:
                print("[%s] quote n=%d best=%s" %
                      (rec["ts"], n, (rec.get("best") or {}).get("price_usd")), flush=True)
        except Exception as e:
            print("[%s] ERR quote %s: %s" % (iso(now_s()), type(e).__name__, e), flush=True)
        t = now_s()
        if abs(t - REGULAR_CLOSE) <= 600:       iv = 2      # 收盘窗口最密
        elif session_of(t) == "regular":        iv = 3
        elif session_of(t) == "post":           iv = 10
        else:                                   iv = 60
        # **定频,不是「取完再睡」。** 2026-11-19 实测:原来写的是 time.sleep(iv),
        # 于是实际节奏 = iv + 取数耗时,sleep 2s 交付的是 4.18s、sleep 3s 交付 5.16s、
        # sleep 10s 交付 12.13s(取数耗时中位 2.18s)。照代码常量理解采样密度会高估一倍。
        # 扣掉本轮已耗时即可自我纠正;下限 0.5s 防止 iv 小于取数耗时时打爆端点。
        #
        # 注意这不能消除全部偏差:本路取数耗时中位 2.18s、p90 3.24s,
        # **iv=2 这一档本身就低于取数耗时**,所以那一档的约束是延迟而非 sleep ——
        # 定频后约 2.68s(= 2.18 + 0.5 下限),拿不到真 2 秒。
        # 要真 2 秒得改成并发请求,那是另一个设计,且对 api.nasdaq.com 的压力更大。
        # iv=3 / iv=10 两档则是净收益:纯粹去掉死时间,不超过原本意图的速率。
        elapsed = now_s() - t_round_start
        time.sleep(max(0.5, iv - elapsed))


def loop_multi():
    """慢路线程：多源横截面 + 分钟 K 线。它的延迟不会影响快路密度。"""
    load_seen_bars(BARS_PATH)
    while True:
        t_multi_start = now_s()
        try:
            emit(snapshot())
            if due("bars", 90):
                t = now_s()
                d, _ = get("nasdaq_chart")
                nb = write_bars(BARS_PATH, bars_nasdaq(d), t)
                d, _ = get("yahoo_1m")
                nb += write_bars(BARS_PATH, bars_yahoo(d), t)
                if nb:
                    print("[%s] bars +%d" % (iso(t), nb), flush=True)
        except Exception as e:
            print("[%s] ERR multi %s: %s" % (iso(now_s()), type(e).__name__, e), flush=True)
        # 定频，同 loop_quote 的理由。本路 multi 一轮打 4–5 个源，
        # 实测节奏 19.8s 对常量 15s（多出约 4.8s 的取数耗时）。
        iv_m = 15 if session_of(now_s()) in ("regular", "post") else 60
        time.sleep(max(1.0, iv_m - (now_s() - t_multi_start)))


def loop_close():
    """收盘线程（主线程）：21:00Z 起探官方收盘价，直到拿到为止。
    刻意独占主线程，不与采样共线程 —— 采样再慢也不能饿死这一步。"""
    close_done = os.path.exists(CLOSE_PATH)
    if close_done:
        print("[%s] close 已定稿，跳过" % iso(now_s()), flush=True)
    while True:
        t = now_s()
        if t >= REGULAR_CLOSE and not close_done:
            try:
                oc = official_close()
                emit(oc)
                got = oc.get("official_close_usd")
                # 盘前该字段是上一交易日的 83.0（发行价）；必须排除，
                # 否则会把发行价当成本日官方收盘价定稿 —— 全项目最不能错的一个数。
                if got is not None and abs(got - ISSUE_PRICE) > 1e-9:
                    with open(CLOSE_PATH, "w") as f:
                        json.dump(oc, f, ensure_ascii=False, indent=1)
                    close_done = True
                    print("[%s] OFFICIAL CLOSE = $%s" % (iso(t), got), flush=True)
                else:
                    print("[%s] close pending (raw=%r)" %
                          (iso(t), oc.get("official_close_raw")), flush=True)
            except Exception as e:
                print("[%s] ERR close %s: %s" % (iso(now_s()), type(e).__name__, e), flush=True)
            time.sleep(15)
        else:
            time.sleep(5)


def main():
    for fn in (loop_quote, loop_multi):
        th = threading.Thread(target=fn, daemon=True)
        th.start()
    loop_close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        print(json.dumps(sample(), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "--close":
        print(json.dumps(official_close(), ensure_ascii=False, indent=1))
    else:
        main()
