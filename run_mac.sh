#!/bin/bash
# MacBook：只采币安（经新加坡出口），写 binance_*.jsonl，与 mini 不冲突
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/bin:/bin"
pgrep -f "collector.py --binance-only" >/dev/null || nohup python3 collector.py --binance-only >> collector_mac.log 2>&1 &
while true; do
  sleep 300
  if [ -n "$(git status --porcelain data/)" ]; then
    git pull -q --rebase --autostash origin main 2>/dev/null
    git add data/
    git -c user.email="aaron.recompile@gmail.com" -c user.name="Aaron Zhang (macbook)" \
        commit -q -m "binance: $(date -u +%Y-%m-%dT%H:%MZ)" 2>/dev/null
    git push -q origin main 2>>push_mac.log || echo "push fail $(date -u +%H:%M)" >> push_mac.log
  fi
  pgrep -f "collector.py --binance-only" >/dev/null || nohup python3 collector.py --binance-only >> collector_mac.log 2>&1 &
done
