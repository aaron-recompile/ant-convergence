#!/bin/bash
# ant_spot.py 的守护循环。独立于 run_mini.sh —— 不读它、不改它、不碰主采集器。
#
# 刻意不做 git commit：run_mini.sh 已经每 60 秒 `git add data/ && commit && push`，
# 它会把本进程写的 data/spot_*.jsonl、data/minbars_*.jsonl 一起带上。
# 再加一个 commit 循环只会抢 .git/index.lock 并制造非快进 push。
#
# 文件名刻意不含 "collector.py" 子串：run_mini.sh 用 pgrep -f "collector.py"
# 判断主采集器是否存活，同名会让它误判成主采集器还在跑、从而不再自愈。
#
# 存活判定用 pidfile + kill -0，不用 pgrep -f。
# 实测踩过：`pgrep -f ant_spot.py` 会匹配到任何命令行里出现这个字符串的进程
# —— 一条含文件名的 ssh 命令、一个 grep，都会让守护误判「它还活着」而不再拉起。
# 这是 pgrep -f 判存活的通病，与 run_mini.sh 那个 collector.py 同名坑是一回事。

cd "$(dirname "$0")" || exit 1
export PATH="/opt/homebrew/bin:/usr/bin:/bin"
PIDFILE="spot.pid"
LOG="spot_runner.log"

alive() {
  [ -f "$PIDFILE" ] || return 1
  local pid; pid=$(cat "$PIDFILE" 2>/dev/null)
  [ -n "$pid" ] || return 1
  # 既要进程在，也要确认它真是我们的 python 进程（防 PID 复用张冠李戴）
  kill -0 "$pid" 2>/dev/null || return 1
  ps -p "$pid" -o command= 2>/dev/null | grep -q "ant_spot" || return 1
  return 0
}

while true; do
  if ! alive; then
    nohup /opt/homebrew/bin/python3 ant_spot.py >> spot.log 2>&1 &
    echo $! > "$PIDFILE"
    echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] 拉起 ant_spot.py pid=$(cat $PIDFILE)" >> "$LOG"
  fi
  sleep 15
done
