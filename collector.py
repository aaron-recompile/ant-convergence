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

def spot_ant():
    """上市后才有。Nasdaq ANT 现货。"""
    d,v=_get("https://query2.finance.yahoo.com/v8/finance/chart/ANT?range=1d&interval=1m")
    try:
        m=d["chart"]["result"][0]["meta"]
        return {"price":m.get("regularMarketPrice"),"prev_close":m.get("chartPreviousClose"),
                "vol":m.get("regularMarketVolume"),"state":m.get("marketState"),"via":v}
    except Exception:
        return None

def sample(only=None,with_para=True):
    """only: None=全部 | 'binance' 只采币安 | 'noBinance' 不采币安"""
    ts=datetime.datetime.now(datetime.timezone.utc)
    r={"ts_utc":ts.isoformat(timespec="seconds"),"ts_epoch":int(ts.timestamp())}
    if only=="binance":
        r["binance_ANTUSDT"]=binance(); return r
    jobs=[("hl_xyz_ANT",lambda: hyperliquid("xyz","xyz:ANT")),
          ("kraken_PF_ANTXUSD",kraken),
          ("spot_ANT_nasdaq",spot_ant),
          ("gate_ANT_USDT",gate),("bitget_ANTUSDT",bitget),("kucoin_ANTUSDTM",kucoin)]
    if only!="noBinance": jobs.insert(0,("binance_ANTUSDT",binance))
    if with_para: jobs.append(("hl_para_ANTH",lambda: hyperliquid("para","para:ANTH")))
    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futs={k:ex.submit(fn) for k,fn in jobs}
        for k,f in futs.items():
            try: r[k]=f.result(timeout=12)
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
            n+=1
            if n%max(1,int(60/iv))==1 or once: print(f"  [{n:>6}] {line(rec)}",flush=True)
        except Exception as e:
            print(f"  ! {e}",flush=True)
        if once: break
        time.sleep(iv)

if __name__=="__main__": main()
