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
import calendar
import json, os, sys, time, calendar, subprocess, threading, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UA   = "ant-research"

# ── 交易时段边界（2026-11-19，EST = UTC-5）────────────────────────
# 下面两个常量已与 Yahoo 自报的 currentTradingPeriod.regular 对上：
# start 1795098600 / end 1795122000，两边完全一致，故采用。
def _us_eastern_is_dst(y, m, d):
    """美东夏令时：3 月第二个周日起，11 月第一个周日止（均 2:00 本地）。
    只按日期判，边界那两天的小时级精度对本用途足够（采集跨不过那两天的 2:00）。"""
    if m < 3 or m > 11:
        return False
    if 3 < m < 11:
        return True
    # 该月 1 日是周几（0=周一 … 6=周日）
    wd_first = calendar.weekday(y, m, 1)
    first_sunday = 1 + ((6 - wd_first) % 7)
    if m == 3:
        return d >= first_sunday + 7      # 第二个周日
    return d < first_sunday               # 11 月：第一个周日当天起即为 EST


# ── 交易日：由当前时刻推导，不再硬编码 ──────────────────────────────
# 为什么改：原来写死 TRADING_DAY = "2026-11-19"，而**所有输出文件名都由它拼出来**。
# 进程跨过本场结束（20:00 ET）仍在跑时，会把下一个交易日的数据继续追加到本场的文件里 ——
# 数据不丢，但归属错了，而且因为文件一直在长、看起来完全正常（见数据说明 7.21）。
# 与其留一个「需要有人记得去重启」的雷，不如让它自己推导：下次拉起即正确。
#
# 切换点取 **04:00 ET（盘前开始）**：
#   D 04:00 ET → D 20:00 ET   是 D 这一场（盘前 + 正常 + 盘后）
#   D 20:00 ET → D+1 04:00 ET 无场次，归给 D（本场的尾巴，无害）
# 所以「ET 日期，且 ET 时刻 < 04:00 时算前一天」就是要的规则。
#
# 可用环境变量 ANT_TRADING_DAY 覆盖 —— 重跑历史数据时必须能钉住某一天，
# 否则同一份代码在不同时刻跑会写到不同文件。


def _et_offset_for(y, mo, d):
    """该日的 ET→UTC 偏移秒数（EST 18000 / EDT 14400）。"""
    return 14400 if _us_eastern_is_dst(y, mo, d) else 18000


def derive_trading_day(now=None):
    now = now if now is not None else time.time()
    # 先按 EST 粗判当天，再用该天真实的偏移复算一次（跨 DST 切换日也对）
    for off in (18000,):
        et = time.gmtime(now - off)
        off2 = _et_offset_for(et.tm_year, et.tm_mon, et.tm_mday)
        et = time.gmtime(now - off2)
    if et.tm_hour < 4:                      # 04:00 ET 之前算前一个交易日
        et = time.gmtime(now - off2 - 86400)
    return time.strftime("%Y-%m-%d", et)


TRADING_DAY = os.environ.get("ANT_TRADING_DAY") or derive_trading_day()
# 场次边界：由 TRADING_DAY 推出，不再写死。
# 为什么必须一起改：TRADING_DAY 已改为自动推导（见上），若这三个还写死在 2026-11-19，
# 下一个交易日拉起时文件名会前进、场次判定却留在旧日期 —— **自动前进一半比不前进更糟**，
# 因为 session_of() 会把全天判成 "closed"、收盘 ±600s 的密集窗口也落在错误的时刻。
# 这正是本项目反复撞的「定义比实现宽」的形状（数据说明 7.15.1）：
# 改了一处，却没有把依赖它的那几处一起改。
_Y, _MO, _D = [int(x) for x in TRADING_DAY.split("-")]
_DAY_BASE = calendar.timegm((_Y, _MO, _D, 0, 0, 0, 0, 0, 0))
_ET_OFF = _et_offset_for(_Y, _MO, _D)       # EST 18000 / EDT 14400

REGULAR_OPEN  = _DAY_BASE + 9 * 3600 + 30 * 60 + _ET_OFF   # 09:30 ET
REGULAR_CLOSE = _DAY_BASE + 16 * 3600 + _ET_OFF            # 16:00 ET
POST_CLOSE    = _DAY_BASE + 20 * 3600 + _ET_OFF            # 20:00 ET

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
# 由交易日推出，不写死 —— 跨夏令时必须是 14400。原来写死 18000，
# 常驻自检会喊（见 7.21），但能推导就不该靠喊。
ET_TO_UTC_OFFSET = _ET_OFF


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


# ── 常驻常量自检 ─────────────────────────────────────────────────
# 为什么要常驻而不是留个对账脚本：`const_audit.py` 是一次性脚本，**要人去跑**，
# 只在有人想起来时才能发现问题。另一个会话的 SPAN_REF 是在采集循环里每 60 条自己比，
# 偏出就在日志里喊 —— **那种在无人看的时候也有效**。本块照那个形式做。
#
# 查三件事，按危害从大到小：
#   1. TRADING_DAY 是否还是今天。**这条最紧**：它是硬编码字符串，
#      所有输出文件名都由它拼出来。进程若跨过午夜仍在跑，
#      会把新一天的数据继续追加到旧一天的文件里 —— 数据没丢，但归属错了，
#      而且因为文件一直在长，看起来完全正常。
#   2. ET→UTC 偏移是否与该日的美东夏令时状态一致。
#      2026-11-19 是 EST（DST 于 11/1 结束）故 18000；夏令时期间应为 14400。
#      这个偏移用在 nasdaq chart 的时间戳修正上（见 7.11 / 数据说明 2.x），
#      错了会让整条分钟线系统性偏移 1 小时。
#   3. REGULAR_OPEN / REGULAR_CLOSE / POST_CLOSE 是否能由 TRADING_DAY + 偏移推出来。
#      它们决定 session 判定与收盘 ±600s 的密集采样窗口中心。
#
# 不自动改任何常量：静默自我修正会让「哪天的数据按哪套常量采的」无法追溯。
# 只在日志里喊，由人决定。



def audit_constants(now=None):
    """返回问题列表（空列表 = 全部对得上）。只读，不改任何常量。"""
    now = now if now is not None else now_s()
    probs = []

    # 判据不是「UTC 日期变了」。**初版就是那么写的，它会在午夜误报整整一小时。**
    # 美东交易日 TRADING_DAY 的完整区间是
    #     TRADING_DAY 14:30Z（09:30 ET 开市）→ 次日 01:00Z（20:00 ET 盘后结束）
    # 所以 00:00–01:00Z 的数据 UTC 日期已经是次日，但它**仍属于 TRADING_DAY 这一场的盘后**，
    # 写进 spot_<TRADING_DAY>.jsonl 是正确的。
    # 拿 UTC 日期当交易日的代理，这两者在盘后那一小时分叉 —— 又是「判据的适用范围
    # 比使用范围窄」（见数据说明 7.18.3）。**而假警报比没有警报更坏：它训练人忽略日志。**
    #
    # 真正的失效条件是**本场已经结束而进程还在跑**：now >= POST_CLOSE。
    # 那之后采到的东西属于下一个交易日，却会继续追加到本场的文件里。
    if now >= POST_CLOSE:
        probs.append("本场（TRADING_DAY=%s）已于 %s 结束，但进程仍在运行 —— "
                     "此后采到的数据属于下一个交易日，却会继续追加到本场的文件里"
                     "（输出文件名由 TRADING_DAY 拼出）。数据不会丢，但归属错了，"
                     "且因为文件一直在长、看起来完全正常。"
                     "须停掉本进程，由守护用新的 TRADING_DAY 拉起。"
                     % (TRADING_DAY, iso(POST_CLOSE)))

    y, m, d = [int(x) for x in TRADING_DAY.split("-")]
    want_off = 14400 if _us_eastern_is_dst(y, m, d) else 18000
    if ET_TO_UTC_OFFSET != want_off:
        probs.append("ET_TO_UTC_OFFSET=%d 但 %s 应为 %d（%s）—— "
                     "nasdaq chart 的分钟时间戳会系统性偏移 %d 秒。"
                     % (ET_TO_UTC_OFFSET, TRADING_DAY, want_off,
                        "EDT 夏令时" if want_off == 14400 else "EST 标准时",
                        abs(ET_TO_UTC_OFFSET - want_off)))

    base = calendar.timegm((y, m, d, 0, 0, 0, 0, 0, 0))
    for name, val, et_h, et_m in (("REGULAR_OPEN", REGULAR_OPEN, 9, 30),
                                  ("REGULAR_CLOSE", REGULAR_CLOSE, 16, 0),
                                  ("POST_CLOSE", POST_CLOSE, 20, 0)):
        want = base + (et_h * 3600 + et_m * 60) + want_off
        if val != want:
            probs.append("%s=%d 但由 %s + %d 推出应为 %d（差 %+d 秒）"
                         % (name, val, TRADING_DAY, want_off, want, val - want))
    return probs


def exit_if_session_over(tag):
    """本场结束后主动退出，让守护用新的 TRADING_DAY 重新拉起。

    **为什么必须退出而不只是告警。** 2026-11-20 的实测教训：
    7.22 把 TRADING_DAY 改成推导，7.21 加了常驻自检，两者都按设计工作了 ——
    01:05Z 的预约重启成功，新进程启动时**立刻**报出
    「本场已于 01:00:00Z 结束，但进程仍在运行 …… 会继续追加到本场的文件里」，
    而且在 spot.log 里报了 **11 次**。

    **但告警不是执行器。** 它说了，没有任何东西去做。
    结果 Nov 20 的 2,645 条记录写进了 spot_2026-11-19.jsonl（数据没丢，归属错了）。

    根因：`TRADING_DAY` 在 **import 时算一次**，所以「下次拉起即正确」这句话是对的，
    **但它只覆盖「新启动」，不覆盖「长跑进程跨过场次边界」** ——
    而我在 7.22 写「操作后果已消除」时，恰好漏掉了后一种。

    所以本函数：本场结束即 `os._exit(0)`。守护（spot_runner.sh）会拉起一个新进程，
    它在 import 时重新推导 TRADING_DAY。

    **【更正 2026-11-20，7.50】上面那句「于是自动写到新一天的文件」是错的，**
    而它从未被测试过 —— 它今晚（11-21 01:00Z）才第一次执行。实测：
    `POST_CLOSE` 是 20:00 ET，而 `derive_trading_day` 的切换点是 **04:00 ET**。
    两者之间隔着 8 小时，在这 8 小时里推导出的仍是**同一个**交易日，
    于是新进程的 `POST_CLOSE` 已过 ⇒ 启动即退 ⇒ 守护 15 秒后再拉起
    ⇒ **01:00Z–09:00Z 空转约 1920 次**（逐小时实测，见 7.50）。

    不是数据损失（本场已结束），但每次启动都会打一条启动心跳，
    于是「启动心跳」这个信号被淹成噪声 —— 正是 7.33 那个形状。

    修法在守护侧：拉起前先用 `--session-pending` 问一句，已结束则退避 300 秒。
    **不能改成让本进程睡到下一场** —— `TRADING_DAY` 及其全部派生常量是 import 时
    算的（7.46），长寿进程改不了日期。所以退出是对的，该等的是守护。
    用 `os._exit` 而不是 `sys.exit`：本进程是多线程的，`sys.exit` 只结束调用线程。
    """
    if now_s() < POST_CLOSE:
        return
    print("[%s] 本场（TRADING_DAY=%s）已于 %s 结束，主动退出，"
          "由守护用新的 TRADING_DAY 拉起（%s）"
          % (iso(now_s()), TRADING_DAY, iso(POST_CLOSE), tag), flush=True)
    sys.stdout.flush()
    os._exit(0)


def log_constant_audit(tag, quiet_ok=True):
    """常量自检并写日志。

    **`quiet_ok=False` 时即使全对也打印一行 —— 这是刻意的，不是啰嗦。**

    初版无论如何都只在「有问题」时才出声，于是日志里的沉默是**二义的**：
    「检查跑了、一切正常」和「这段代码根本没在跑」长得一模一样。
    另一个会话正是栽在这上面 —— 他 `grep -c "书跨度偏离基准"` 得到 0，
    那不是「跨度一直正常」而是「那段代码没在跑」。

    更直接的后果：本路 7.27 的 A 级判据拿「`spot.log` 里出现过常驻自检」
    当「新代码进了运行时」的指纹。初版那个写法下，**重启成功后这行字也不会出现**，
    于是 A 级会在重启成功的情况下 FAIL —— 一个假阴性，而且它会被读成「重启没生效」。

    所以：**启动时必发一行正向心跳**（`quiet_ok=False`），
    之后每 100 条的周期检查保持安静（`quiet_ok=True`），只有出问题才喊。
    一次心跳足以让沉默不再二义；周期性刷屏会让人忽略日志（见 7.22.1）。
    """
    probs = audit_constants()
    if probs:
        print("[%s] ***** 常量自检失败（%s）*****" % (iso(now_s()), tag), flush=True)
        for x in probs:
            print("[%s]   ! %s" % (iso(now_s()), x), flush=True)
    elif not quiet_ok:
        print("[%s] 常量自检通过（%s）：TRADING_DAY=%s 收盘=%s ET偏移=%d"
              % (iso(now_s()), tag, TRADING_DAY, iso(REGULAR_CLOSE), ET_TO_UTC_OFFSET),
              flush=True)
    return probs


def loop_quote():
    """快路线程：密集的 Nasdaq 现货序列。收盘前后 10 分钟加密到 2 秒。"""
    n = 0
    while True:
        t_round_start = now_s()
        exit_if_session_over("quote 循环")
        try:
            rec = snapshot_quote()
            emit(rec)
            n += 1
            if n % 100 == 0:
                print("[%s] quote n=%d best=%s" %
                      (rec["ts"], n, (rec.get("best") or {}).get("price_usd")), flush=True)
                log_constant_audit("每 100 条")
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
                # **【更正 2026-11-20，7.45 / 7.49.4】** 这里原先是
                # `abs(got - ISSUE_PRICE) > 1e-9` —— 排除发行价 83.0。
                # 那道闸门是为旧的 `previousInfo` 路径设的（盘前该字段是上一交易日
                # 的 83.0），而那条路径已废弃。新路径 `secondaryData.lastSalePrice`
                # 要求戳含 "Closed"（见 official_close() 的 closed_ok），返回的本来
                # 就是本日真实收盘价，**83.00 在其上是一个合法价格**。
                #
                # 于是那道闸门不再保护任何东西，只剩一种作用：若某日正好收在 83.00，
                # 就永久拒收该日官方收盘价，且只在日志里印 "close pending"，
                # 一整场重试到进程自杀 —— 一个只会在日志里说话的失败（7.33 的形状）。
                # **2026-11-20 实测日内低点 83.05，距 83.00 仅 $0.05，五源一致** ——
                # 误伤风险不再是假想的。
                #
                # 现在：`got is not None` 即定稿（口径由 closed_ok 守），
                # 恰好等于发行价时记一条告警，不拒收。
                # 与 spot_close_fix.py 的改法一致，那一侧已在 11-19/11-20 两天验过。
                if got is not None:
                    if abs(got - ISSUE_PRICE) < 1e-9:
                        oc["warn"] = ["close_equals_issue_price_83_coincidence"]
                        print("[%s] WARN 本日收盘价恰好等于发行价 $%s —— 已定稿并标注，"
                              "不再拒收（7.45）" % (iso(t), got), flush=True)
                    with open(CLOSE_PATH, "w") as f:
                        json.dump(oc, f, ensure_ascii=False, indent=1)
                    close_done = True
                    print("[%s] OFFICIAL CLOSE = $%s" % (iso(t), got), flush=True)
                else:
                    # got 为 None 只有一个来源：official_close() 里 closed_ok 不通过
                    # （戳不含 "Closed"），即「还没收盘」。那才是该等的情形。
                    print("[%s] close pending（戳未说 Closed）(raw=%r)" %
                          (iso(t), oc.get("official_close_raw")), flush=True)
            except Exception as e:
                print("[%s] ERR close %s: %s" % (iso(now_s()), type(e).__name__, e), flush=True)
            time.sleep(15)
        else:
            time.sleep(5)


def main():
    log_constant_audit("启动", quiet_ok=False)
    for fn in (loop_quote, loop_multi):
        th = threading.Thread(target=fn, daemon=True)
        th.start()
    loop_close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--sample":
        print(json.dumps(sample(), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "--close":
        print(json.dumps(official_close(), ensure_ascii=False, indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "--session-pending":
        # 给守护用：本场还要不要跑？退出码 0=要跑，1=已结束。
        # 唯一真相仍在本文件（TRADING_DAY / POST_CLOSE 的推导），守护不复算。
        # 按本路的规矩，把时刻换算成人读的形式打出来（硬编码时刻要能被看见）。
        _n = now_s()
        _pending = _n < POST_CLOSE
        print("trading_day=%s  now=%s  POST_CLOSE=%s  pending=%s"
              % (TRADING_DAY, iso(_n), iso(POST_CLOSE), _pending), flush=True)
        sys.exit(0 if _pending else 1)
    else:
        main()
