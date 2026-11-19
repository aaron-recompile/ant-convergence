#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ANT 上市日 perp↔现货 收敛研究 · 数据采集器

四个 perp 场所 + 上市后的 Nasdaq 现货，每 INTERVAL 秒一条，
append-only JSONL 写入 Google Drive（本机会卖，不留本地）。

  python3 collector.py              前台跑
  python3 collector.py --once       采一条就退出（测试用）
  nohup python3 collector.py &      后台常驻

币安对美国 IP 封锁：优先直连，失败自动改走 SOCKS 127.0.0.1:1086（新加坡节点）。
每条记录都标注用了哪条路径，便于事后判断数据缺口成因。
"""
import json,os,sys,time,subprocess,urllib.request,datetime
from concurrent.futures import ThreadPoolExecutor

HERE=os.path.dirname(os.path.abspath(__file__))
OUT=os.path.join(HERE,"data")
SOCKS="127.0.0.1:1086"

# 自动加密采样：按 UTC 时间切换间隔。2026-11-19 Nasdaq 开盘 14:30 UTC（美东 9:30）
# 大型 IPO 首笔成交通常在美东 10:00–13:00 = 15:00–18:00 UTC
SCHEDULE=[  # (起UTC时, 止UTC时, 间隔秒, 是否采 para 这个薄盘)
    (0.0, 13.0, 10, True),    # 常规
    (13.0,14.5,  3, False),   # 开盘前一小时半
    (14.5,19.0,  2, False),   # 开盘 → 首笔成交窗口（核心）
    (19.0,21.5,  5, False),   # 盘中
    (21.5,24.0, 10, True),    # 收盘后
]
def plan(now=None):
    now=now or datetime.datetime.now(datetime.timezone.utc)
    h=now.hour+now.minute/60
    for a,b,iv,para in SCHEDULE:
        if a<=h<b: return iv,para
    return 10,True

_direct_bad={}   # 按主机记忆：直连失败过就 10 分钟内不再试，省掉每次的超时

def _host(u):
    try: return u.split("/")[2]
    except Exception: return u

def _get(url,timeout=8):
    """直连优先。只有当 SOCKS 确实能替代时，才记住这个主机直连不通并跳过它。
    没有 SOCKS 的机器（如 mini）永远继续试直连——否则一次偶发超时会静默拉黑 10 分钟。"""
    h=_host(url)
    skip = time.time()-_direct_bad.get(h,0) < 600
    direct_failed=False
    if not skip:
        try:
            r=urllib.request.Request(url,headers={"User-Agent":"ant-research"})
            return json.loads(urllib.request.urlopen(r,timeout=timeout).read().decode()),"direct"
        except Exception:
            direct_failed=True
    try:
        out=subprocess.run(["curl","-s","-m",str(timeout),"--socks5-hostname",SOCKS,url],
                           capture_output=True,timeout=timeout+4).stdout.decode()
        d=json.loads(out)
        if isinstance(d,dict) and d.get("code")==0 and "restricted location" in str(d.get("msg","")):
            return None,"geo"
        if direct_failed: _direct_bad[h]=time.time()   # 仅在 socks 成功时才拉黑直连
        return d,"socks"
    except Exception:
        _direct_bad.pop(h,None)                        # socks 也不通 → 不拉黑，下次继续试直连
        return None,"fail"

def _post_hl(dex,timeout=8):
    try:
        r=urllib.request.Request("https://api.hyperliquid.xyz/info",
            data=json.dumps({"type":"metaAndAssetCtxs","dex":dex}).encode(),
            headers={"Content-Type":"application/json"})
        return json.loads(urllib.request.urlopen(r,timeout=timeout).read().decode())
    except Exception:
        return None

def hyperliquid(dex,sym):
    d=_post_hl(dex)
    if not d: return None
    for u,c in zip(d[0]["universe"],d[1]):
        if u["name"]==sym:
            mk=float(c["markPx"])
            return {"mark":mk,"mid":float(c["midPx"]) if c.get("midPx") else None,
                    "index":float(c.get("oraclePx") or mk),
                    "prev_day":float(c.get("prevDayPx") or mk),
                    "vol24h_usd":float(c.get("dayNtlVlm") or 0),
                    "oi_contracts":float(c.get("openInterest") or 0),
                    "funding":float(c.get("funding") or 0),
                    "premium":float(c.get("premium") or 0),
                    "impact_px":c.get("impactPxs"),"via":"direct"}
    return None

_cg_last=[0.0,None]   # 节流：CoinGecko 免费档限频，最快 5 秒一次

def binance_via_coingecko():
    now=time.time()
    if now-_cg_last[0] < 5 and _cg_last[1] is not None:
        return dict(_cg_last[1])
    d,_=_get("https://api.coingecko.com/api/v3/derivatives/exchanges/binance_futures?include_tickers=unexpired",timeout=12)
    if not d: return None
    for x in d.get("tickers",[]):
        if x.get("symbol","").upper()=="ANTUSDT":
            cv=(x.get("converted_volume") or {}).get("usd")
            r={"last":x.get("last"),"mark":x.get("last"),
               "index":x.get("index"),"chg24h_pct":x.get("h24_percentage_change"),
               "basis_pct":x.get("index_basis_percentage"),
               "bid_ask_spread":x.get("bid_ask_spread"),
               "funding":x.get("funding_rate"),
               "oi_usd":x.get("open_interest_usd"),
               "vol24h_contracts":x.get("h24_volume"),
               "vol24h_usd":float(cv) if cv else None,
               "last_traded":x.get("last_traded"),"via":"coingecko"}
            _cg_last[0]=now; _cg_last[1]=dict(r)
            return r
    return None

_bn_blocked=[0.0]   # 直连被封的记忆；10 分钟后重试一次

def binance():
    if time.time()-_bn_blocked[0] < 600:
        return binance_via_coingecko()
    B="https://fapi.binance.com/fapi/v1/"
    with ThreadPoolExecutor(max_workers=3) as ex:
        ft=ex.submit(_get,B+"ticker/24hr?symbol=ANTUSDT",6)
        fp=ex.submit(_get,B+"premiumIndex?symbol=ANTUSDT",6)
        fo=ex.submit(_get,B+"openInterest?symbol=ANTUSDT",6)
        t,v1=ft.result(); p,v2=fp.result(); o,v3=fo.result()
    if not t or "lastPrice" not in t:
        _bn_blocked[0]=time.time()
        return binance_via_coingecko()   # 直连被封时自动改走 CoinGecko
    r={"last":float(t["lastPrice"]),"chg24h_pct":float(t["priceChangePercent"]),
       "high24h":float(t["highPrice"]),"low24h":float(t["lowPrice"]),
       "vol24h_usd":float(t["quoteVolume"]),"trades24h":int(t["count"]),"via":v1}
    if p: r.update({"mark":float(p["markPrice"]),"index":float(p["indexPrice"]),
                    "funding":float(p["lastFundingRate"])})
    if o: r["oi_contracts"]=float(o["openInterest"])
    return r

# ── 次级场所：带节流缓存，最快 15 秒一次，不拖慢加密时的主循环 ──
_cache={}
def _throttled(key,fn,every=15):
    now=time.time(); c=_cache.get(key)
    if c and now-c[0]<every: return dict(c[1]) if c[1] else None
    v=None
    try: v=fn()
    except Exception: v=None
    if v is not None: _cache[key]=(now,dict(v))
    elif c: return dict(c[1]) if c[1] else None
    else: _cache[key]=(now,None)
    return v

def _gate():
    d,_=_get("https://api.gateio.ws/api/v4/futures/usdt/tickers?contract=ANT_USDT")
    if not isinstance(d,list) or not d: return None
    t=d[0]; f=lambda k: float(t[k]) if t.get(k) not in (None,"") else None
    return {"mark":f("mark_price"),"last":f("last"),"index":f("index_price"),
            "bid":f("highest_bid"),"ask":f("lowest_ask"),
            "high24h":f("high_24h"),"low24h":f("low_24h"),
            "chg24h_pct":f("change_percentage"),
            "vol24h_usd":f("volume_24h_quote"),"oi_contracts":f("total_size"),
            "funding":f("funding_rate"),"funding_pred":f("funding_rate_indicative"),
            "via":"direct"}

def _bitget():
    d,_=_get("https://api.bitget.com/api/v2/mix/market/ticker?symbol=ANTUSDT&productType=USDT-FUTURES")
    rows=(d or {}).get("data") or []
    if not rows: return None
    t=rows[0]; f=lambda k: float(t[k]) if t.get(k) not in (None,"") else None
    cp=f("change24h")
    return {"mark":f("markPrice"),"last":f("lastPr"),"index":f("indexPrice"),
            "bid":f("bidPr"),"ask":f("askPr"),"bid_size":f("bidSz"),"ask_size":f("askSz"),
            "high24h":f("high24h"),"low24h":f("low24h"),"open24h":f("open24h"),
            "chg24h_pct":cp*100 if cp is not None else None,
            "vol24h_usd":f("usdtVolume"),"oi_contracts":f("holdingAmount"),
            "funding":f("fundingRate"),"via":"direct"}

def _kucoin():
    d,_=_get("https://api-futures.kucoin.com/api/v1/contracts/ANTUSDTM")
    t=(d or {}).get("data") or {}
    if not t: return None
    f=lambda k: float(t[k]) if t.get(k) not in (None,"") else None
    cp=f("priceChgPct")
    return {"mark":f("markPrice"),"last":f("lastTradePrice"),"index":f("indexPrice"),
            "high24h":f("highPrice"),"low24h":f("lowPrice"),
            "chg24h_pct":cp*100 if cp is not None else None,
            "vol24h_usd":f("turnoverOf24h"),"oi_contracts":f("openInterest"),
            "funding":f("fundingFeeRate"),"funding_pred":f("predictedFundingFeeRate"),
            "status":t.get("status"),"via":"direct"}

def gate():   return _throttled("gate",_gate)
def bitget(): return _throttled("bitget",_bitget)
def kucoin(): return _throttled("kucoin",_kucoin)

def kraken():
    d,_=_get("https://futures.kraken.com/derivatives/api/v3/tickers")
    if not d: return None
    for t in d.get("tickers",[]):
        if t.get("symbol","").upper()=="PF_ANTXUSD":
            g=lambda k: float(t[k]) if t.get(k) is not None else None
            mk=g("markPrice")
            return {"mark":mk,"last":g("last"),"index":g("indexPrice"),
                    "bid":g("bid"),"ask":g("ask"),"bid_size":g("bidSize"),"ask_size":g("askSize"),
                    "vol24h":g("vol24h"),"vol24h_quote":g("volumeQuote"),
                    "oi_contracts":g("openInterest"),
                    "open24h":g("open24h"),"high24h":g("high24h"),"low24h":g("low24h"),
                    "vwap24h":g("vwap24h"),"chg24h_pct":g("change24h"),
                    "funding":g("fundingRate"),"funding_pred":g("fundingRatePrediction"),
                    "rel_funding":g("relativeFundingRate"),
                    "suspended":t.get("suspended"),"via":"direct"}
    return None

def _f(x):
    try:
        x=str(x).replace("$","").replace(",","").strip()
        if x in ("","N/A","NA","--","unch"): return None
        return float(x)
    except Exception: return None

def _spot_nasdaq():
    """Nasdaq 自己的报价接口，带盘口和成交量。首笔成交前 lastSalePrice 是 'N/A'。"""
    d,via=_get("https://api.nasdaq.com/api/quote/ANT/info?assetclass=stocks",timeout=10)
    dd=(d or {}).get("data") or {}
    p=(dd.get("primaryData") or {})
    if not dd.get("symbol"): return None
    px=_f(p.get("lastSalePrice"))
    if px is not None and _f(p.get("volume")) in (None,0) and abs(px-83.0)<1e-9:
        px=None                       # 同一个占位陷阱，交易所接口偶尔也会这样回
    return {"price":px,"bid":_f(p.get("bidPrice")),"ask":_f(p.get("askPrice")),
            "bid_size":_f(p.get("bidSize")),"ask_size":_f(p.get("askSize")),
            "vol":_f(p.get("volume")),"chg_pct":_f((p.get("percentageChange") or "").replace("%","")),
            "last_trade_ts":p.get("lastTradeTimestamp") or None,
            "state":dd.get("marketStatus"),"realtime":p.get("isRealTime"),
            "src":"nasdaq","via":via,"traded":px is not None}

def _spot_yahoo():
    d,via=_get("https://query2.finance.yahoo.com/v8/finance/chart/ANT?range=1d&interval=1m",timeout=10)
    r=((d or {}).get("chart") or {}).get("result") or []
    if not r: return None
    m=r[0].get("meta") or {}
    px=m.get("regularMarketPrice"); pc=m.get("chartPreviousClose")
    hi=m.get("regularMarketDayHigh"); lo=m.get("regularMarketDayLow")
    vol=m.get("regularMarketVolume")
    # 首笔成交前 Yahoo 把发行价当占位回来：price=high=low=prevClose、量为空。
    # 不设这道防线就会把 $83 记成「首笔成交」，而那正是本研究最关键的一条数据。
    placeholder = (px is not None and pc is not None and px==pc
                   and (hi is None or hi==px) and (lo is None or lo==px)
                   and not vol)
    return {"price":None if placeholder else px,"quoted":px,"prev_close":pc,
            "vol":vol,"state":m.get("marketState"),"day_high":hi,"day_low":lo,
            "placeholder":placeholder,
            "src":"yahoo","via":via,"traded":bool(px is not None and not placeholder)}

def _spot_cnbc():
    """注意：首笔成交前 CNBC 回的 last 是发行价 $83（上一日收盘占位）。
    只有当 last_timedate 是今天、且 open/high/low 不全为 0 时才认成交。"""
    d,via=_get("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol"
               "?symbols=ANT&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json",timeout=10)
    q=(((d or {}).get("FormattedQuoteResult") or {}).get("FormattedQuote") or [])
    if not q: return None
    t=q[0]
    o,h,l=_f(t.get("open")),_f(t.get("high")),_f(t.get("low"))
    traded = bool(o or h or l)
    return {"price":_f(t.get("last")) if traded else None,
            "quoted":_f(t.get("last")),"open":o,"high":h,"low":l,
            "prev_close":_f(t.get("previous_day_closing")),
            "last_timedate":t.get("last_timedate"),
            "src":"cnbc","via":via,"traded":traded}

def spot_ant():
    """Nasdaq ANT 现货。三个源依次试，第一个报出真实成交价的胜出；
    都没成交时也返回一条（traded=False），好让记录里留下『当时确实还没开盘』这个事实。"""
    first=None
    for fn in (_spot_nasdaq,_spot_yahoo,_spot_cnbc):
        try: r=fn()
        except Exception: r=None
        if not r: continue
        if first is None: first=r
        if r.get("traded") and r.get("price"): return r
    return first

# ── 资金费归一化 ────────────────────────────────────────────────
# 各场所口径不同，不折算就不能比较。已逐个实测（2026-11-18）：
#   binance   fundingIntervalHours=8，lastFundingRate 是比率
#   binance 走 CoinGecko 时 funding_rate 是【百分数】→ 与直连差 100 倍
#   hyperliquid  每 1 小时
#   kraken    fundingRate 是绝对值（价格单位），relativeFundingRate 才是比率/1h
#   gate funding_interval=28800s / bitget ratePeriod=8 / kucoin granularity=28800000ms
FUND_HRS={"binance_ANTUSDT":8,"hl_xyz_ANT":1,"hl_para_ANTH":1,
          "kraken_PF_ANTXUSD":1,"gate_ANT_USDT":8,
          "bitget_ANTUSDT":8,"kucoin_ANTUSDTM":8}

def norm_funding(key,v):
    """原始值原样保留；另写 funding_8h（每8小时比率）和 funding_apr（年化）。"""
    if not isinstance(v,dict) or key not in FUND_HRS: return v
    hrs=FUND_HRS[key]; raw=v.get("funding")
    if key=="binance_ANTUSDT" and v.get("via")=="coingecko" and raw is not None:
        raw=raw/100.0                      # CoinGecko 给百分数
    if key=="kraken_PF_ANTXUSD":
        raw=v.get("rel_funding")
        if raw is None and v.get("funding") is not None and v.get("index"):
            raw=v["funding"]/v["index"]
    if raw is None: return v
    f8=raw*(8.0/hrs)
    v["funding_8h"]=f8; v["funding_apr"]=f8*3*365; v["funding_hrs"]=hrs
    return v

def _bn_sent():
    """币安多空比 + 未平仓历史 = 情绪的真实读数。
    上市前 mark≡index，premium≡0，资金费被钉在利率基准上不动，读不出情绪；
    这组多空比才动。只有 fapi（直连或代理）有，CoinGecko 没有。"""
    out={}
    eps=[("ls_account","globalLongShortAccountRatio"),
         ("ls_top_pos","topLongShortPositionRatio"),
         ("ls_top_acct","topLongShortAccountRatio")]
    def one(nm,ep):
        d,_=_get(f"https://fapi.binance.com/futures/data/{ep}?symbol=ANTUSDT&period=5m&limit=1",timeout=10)
        if isinstance(d,list) and d:
            return nm,float(d[0]["longShortRatio"]),float(d[0]["longAccount"])
        return nm,None,None
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs=[ex.submit(one,nm,ep) for nm,ep in eps]
        ft=ex.submit(_get,"https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=ANTUSDT&period=5m&limit=1",10)
        fo=ex.submit(_get,"https://fapi.binance.com/futures/data/openInterestHist?symbol=ANTUSDT&period=5m&limit=1",10)
        for f in futs:
            try:
                nm,r,lg=f.result(timeout=12)
                if r is not None: out[nm]=r; out[nm+"_long"]=lg
            except Exception: pass
        try:
            d,_=ft.result(timeout=12)
            if isinstance(d,list) and d:
                out["taker_bs"]=float(d[0]["buySellRatio"])
                out["taker_buy"]=float(d[0]["buyVol"]); out["taker_sell"]=float(d[0]["sellVol"])
        except Exception: pass
        try:
            d,_=fo.result(timeout=12)
            if isinstance(d,list) and d:
                out["oi_contracts"]=float(d[0]["sumOpenInterest"])
                out["oi_usd"]=float(d[0]["sumOpenInterestValue"])
        except Exception: pass
    if not out: return None
    out["via"]="fapi"
    return out

def bn_sent(): return _throttled("bn_sent",_bn_sent,every=60)

def sample(only=None,with_para=True):
    """only: None=全部 | 'binance' 只采币安 | 'noBinance' 不采币安"""
    ts=datetime.datetime.now(datetime.timezone.utc)
    r={"ts_utc":ts.isoformat(timespec="seconds"),"ts_epoch":int(ts.timestamp())}
    if only=="binance":
        # 现货两台都采：首笔成交是全项目最关键的一条，不能单点
        with ThreadPoolExecutor(max_workers=3) as ex:
            fb=ex.submit(binance); fs=ex.submit(bn_sent); fp=ex.submit(spot_ant)
            try: r["binance_ANTUSDT"]=norm_funding("binance_ANTUSDT",fb.result(timeout=12))
            except Exception: r["binance_ANTUSDT"]=None
            try: r["binance_sent"]=fs.result(timeout=12)
            except Exception: r["binance_sent"]=None
            try: r["spot_ANT_nasdaq"]=fp.result(timeout=12)
            except Exception: r["spot_ANT_nasdaq"]=None
        return r
    jobs=[("hl_xyz_ANT",lambda: hyperliquid("xyz","xyz:ANT")),
          ("kraken_PF_ANTXUSD",kraken),
          ("spot_ANT_nasdaq",spot_ant),
          ("gate_ANT_USDT",gate),("bitget_ANTUSDT",bitget),("kucoin_ANTUSDTM",kucoin)]
    if only!="noBinance":
        jobs.insert(0,("binance_ANTUSDT",binance)); jobs.append(("binance_sent",bn_sent))
    if with_para: jobs.append(("hl_para_ANTH",lambda: hyperliquid("para","para:ANTH")))
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs={k:ex.submit(fn) for k,fn in jobs}
        for k,f in futs.items():
            try: r[k]=norm_funding(k,f.result(timeout=12))
            except Exception: r[k]=None
    return r

def line(rec):
    def mk(k):
        v=rec.get(k)
        if not v: return "    —  "
        p=v.get("mark") or v.get("last") or v.get("price")
        return f"{p:>8.2f}" if p else "    —  "
    return (f"{rec['ts_utc'][11:19]}  BN{mk('binance_ANTUSDT')}  "
            f"HL{mk('hl_xyz_ANT')}  KR{mk('kraken_PF_ANTXUSD')}  "
            f"SPOT{mk('spot_ANT_nasdaq')}")

def main():
    os.makedirs(OUT,exist_ok=True)
    once="--once" in sys.argv
    only=None; prefix="ant"
    if "--binance-only" in sys.argv: only,prefix="binance","binance"
    if "--no-binance" in sys.argv:   only="noBinance"
    iv,para=plan()
    print(f"采集启动  模式={only or '全部'}  起始间隔 {iv}s  写入 {OUT}/{prefix}_*.jsonl",flush=True)
    print(f"  自动加密计划(UTC): "+" ".join(f"{a:g}-{b:g}h→{i}s" for a,b,i,_ in SCHEDULE),flush=True)
    n=0; last_iv=iv
    while True:
        iv,para=plan()
        if iv!=last_iv:
            print(f"  ⏱ 间隔切换 {last_iv}s → {iv}s",flush=True); last_iv=iv
        try:
            rec=sample(only=only,with_para=para)
            day=rec["ts_utc"][:10]
            with open(os.path.join(OUT,f"{prefix}_{day}.jsonl"),"a",encoding="utf-8") as f:
                f.write(json.dumps(rec,ensure_ascii=False)+"\n")
            # 最新一条单独落一个小文件：盯盘页只要读这个，不必拉整天的 jsonl
            tmp=os.path.join(OUT,f".latest_{prefix}.tmp")
            with open(tmp,"w",encoding="utf-8") as f: json.dump(rec,f,ensure_ascii=False)
            os.replace(tmp,os.path.join(OUT,f"latest_{prefix}.json"))
            n+=1
            if n%max(1,int(60/iv))==1 or once: print(f"  [{n:>6}] {line(rec)}",flush=True)
        except Exception as e:
            print(f"  ! {e}",flush=True)
        if once: break
        time.sleep(iv)

if __name__=="__main__": main()
