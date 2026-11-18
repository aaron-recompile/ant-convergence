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

def _get(url,timeout=8):
    try:
        r=urllib.request.Request(url,headers={"User-Agent":"ant-research"})
        return json.loads(urllib.request.urlopen(r,timeout=timeout).read().decode()),"direct"
    except Exception:
        pass
    try:
        out=subprocess.run(["curl","-s","-m",str(timeout),"--socks5-hostname",SOCKS,url],
                           capture_output=True,timeout=timeout+4).stdout.decode()
        return json.loads(out),"socks"
    except Exception:
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

def binance():
    t,v1=_get("https://fapi.binance.com/fapi/v1/ticker/24hr?symbol=ANTUSDT")
    p,v2=_get("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=ANTUSDT")
    o,v3=_get("https://fapi.binance.com/fapi/v1/openInterest?symbol=ANTUSDT")
    if not t or "lastPrice" not in t: return None
    r={"last":float(t["lastPrice"]),"chg24h_pct":float(t["priceChangePercent"]),
       "high24h":float(t["highPrice"]),"low24h":float(t["lowPrice"]),
       "vol24h_usd":float(t["quoteVolume"]),"trades24h":int(t["count"]),"via":v1}
    if p: r.update({"mark":float(p["markPrice"]),"index":float(p["indexPrice"]),
                    "funding":float(p["lastFundingRate"])})
    if o: r["oi_contracts"]=float(o["openInterest"])
    return r

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
    if only!="noBinance": r["binance_ANTUSDT"]=binance()
    r["hl_xyz_ANT"]=hyperliquid("xyz","xyz:ANT")
    if with_para: r["hl_para_ANTH"]=hyperliquid("para","para:ANTH")
    r["kraken_PF_ANTXUSD"]=kraken()
    r["spot_ANT_nasdaq"]=spot_ant()
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
