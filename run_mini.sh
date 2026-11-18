#!/bin/bash
# Mini 常驻入口：采集 + 定期 push 到 GitHub
# 用 nohup 跑，不用 launchd（TCC 读不到 ~/Documents）
cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# 采集器（若未在跑则拉起）
MODE="${COLLECT_MODE-}"   # 默认全量；币安走直连→CoinGecko 自动回退
pgrep -f "collector.py" >/dev/null || nohup python3 collector.py $MODE >> collector.log 2>&1 &

# 每 5 分钟 commit+push 一次
while true; do
  sleep 300
  python3 -c "import json,glob,os;json.dump(sorted(os.path.basename(f) for f in glob.glob('data/ant_*.jsonl')+glob.glob('data/binance_*.jsonl')),open('data/index.json','w'))" 2>/dev/null
  if [ -n "$(git status --porcelain data/)" ]; then
    git pull -q --rebase --autostash origin main 2>/dev/null; git add data/ 2>/dev/null
    git -c user.email="aaron.recompile@gmail.com" -c user.name="Aaron Zhang (mini)" \
        commit -q -m "data: $(date -u +%Y-%m-%dT%H:%MZ) $(wc -l < data/ant_$(date -u +%F).jsonl 2>/dev/null | tr -d ' ') samples" 2>/dev/null
    git push -q origin main 2>>push.log || echo "push failed $(date -u +%H:%M)" >> push.log
  fi
  MODE="${COLLECT_MODE-}"   # 默认全量；币安走直连→CoinGecko 自动回退
pgrep -f "collector.py" >/dev/null || nohup python3 collector.py $MODE >> collector.log 2>&1 &
done
