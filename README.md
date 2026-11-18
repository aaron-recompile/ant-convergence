# ANT listing-day convergence dataset

High-frequency capture of **Anthropic (ANT) pre-IPO perpetuals across four
venues, converging onto the Nasdaq spot price** on listing day, 2026-11-19.

Pre-IPO perps stop existing the moment the stock lists. This window does not
come back.

## Venues

| Source | Instrument | Notes |
|---|---|---|
| Binance Futures | `ANTUSDT` | `TRADIFI_PERPETUAL`, onboarded 2026-11-17. Geo-blocked from US IPs. |
| Hyperliquid (trade.xyz, HIP-3) | `xyz:ANT` | Deepest of the HIP-3 markets |
| Hyperliquid (para, HIP-3) | `para:ANTH` | Thin; useful as a cross-check |
| Kraken Futures | `PF_ANTXUSD` | Opened 2026-11-13. Only venue exposing bid/ask. |
| Nasdaq | `ANT` spot | Empty until 2026-11-19 open — that is the point |

## Data

`data/ant_YYYY-MM-DD.jsonl` — one JSON object per line, 10 s interval,
append-only. Per venue, where available: mark, index/oracle, last, bid/ask,
24h OHLC, 24h volume, open interest, funding rate and prediction, premium.
Every record carries `ts_utc`, `ts_epoch`, and a `via` field recording whether
the fetch went direct or through a proxy (so gaps are attributable).

IPO terms: 825M shares, indicative range $70–78, priced 2026-11-18 after the
close, trading from 2026-11-19 on Nasdaq.

## Run

```bash
python3 collector.py          # continuous, 10s interval
python3 collector.py --once   # single sample
```

`index.html` renders the collected series; it reads `data/index.json` and the
JSONL files next to it, so it works from GitHub Pages or any static host.

## Scope

Public market data only. No account, position or identity information is
collected or stored. MIT.
