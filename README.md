# ANT

Anthropic (ANT) pre-IPO perpetuals and Nasdaq spot, seven venues, 10 s
resolution. 825M shares, $70–78 range, listing 2026-11-19.

**Board: https://bitcoincoding.dev/ant-convergence/**

| Venue | Instrument |
|---|---|
| Binance Futures | `ANTUSDT` |
| Hyperliquid (trade.xyz, HIP-3) | `xyz:ANT` |
| Hyperliquid (para, HIP-3) | `para:ANTH` |
| Kraken Futures | `PF_ANTXUSD` |
| Gate.io | `ANT_USDT` |
| Bitget | `ANTUSDT` |
| KuCoin Futures | `ANTUSDTM` |
| Nasdaq | `ANT` |

`data/ant_YYYY-MM-DD.jsonl`, `data/binance_YYYY-MM-DD.jsonl` — one JSON object
per line: mark, index, last, bid/ask, 24h OHLC, volume, open interest, funding.

```bash
python3 collector.py
```

Public market data only. MIT.
