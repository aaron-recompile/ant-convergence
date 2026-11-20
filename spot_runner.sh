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

# 本场是否还要跑 —— 问 ant_spot.py，不在这里复算。
# 唯一真相是 ant_spot.py 的 TRADING_DAY / POST_CLOSE 推导；守护复算一遍
# 就会多出一处要同步的地方（7.46 那个形状）。
session_pending() {
  /opt/homebrew/bin/python3 ant_spot.py --session-pending >/dev/null 2>&1
}

# 状态变化才记日志。否则退避期间每 300 秒一行，一夜 96 行噪声。
LAST_STATE=""
note() {
  [ "$1" = "$LAST_STATE" ] && return 0
  LAST_STATE="$1"
  # 空消息只换状态、不写日志 —— 否则 running 这个状态会写出一行
  # 只有时间戳、没有内容的日志（部署当天实测到一行）。
  [ -n "$2" ] || return 0
  echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $2" >> "$LOG"
}

while true; do
  if alive; then
    LAST_STATE=running
    sleep 15
    continue
  fi

  # **拉起前先问本场要不要跑。** 2026-11-20 实测:POST_CLOSE 是 20:00 ET,
  # 而 derive_trading_day 的切换点是 04:00 ET —— 中间 8 小时推出的是同一个
  # 交易日,于是新进程启动即退,守护 15 秒再拉一次,01:00Z–09:00Z 空转约 1920 次。
  # 这是「本场结束即退出」(修跨日 bug)与「判死就拉起」两个各自正确的东西
  # 合起来产生的,单独看哪一个都没错。详见 数据说明 7.50。
  if session_pending; then
    nohup /opt/homebrew/bin/python3 ant_spot.py >> spot.log 2>&1 &
    echo $! > "$PIDFILE"
    LAST_STATE=""     # 拉起是个事件，总要记一行
    note launched "拉起 ant_spot.py pid=$(cat $PIDFILE)"
    sleep 15
  else
    note waiting "本场已结束（ant_spot.py --session-pending 返回 1），退避 300 秒等下一个交易日"
    sleep 300
  fi
done
