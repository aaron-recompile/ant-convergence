#!/bin/bash
# 核对「跑着的进程」与「磁盘上的文件」是不是同一份代码。
#
# 通则（另一个会话提的）：
#   报告一个常驻检查「没有告警」之前，必须先确认跑着的那份代码里有这个检查。
#   否则「0 次告警」和「检查不存在」在日志里长得一模一样。
#
# **初版自己栽了一个时区 bug，而且它让一个结论反了。**
# `ps -p PID -o lstart=` 给的是**本机本地时间**（本机 UTC-8），
# 初版用 `date -ju -f ...` 当 UTC 解析，于是每个差值都虚增整 480 分钟：
#   spot_archive.py 被报成「文件比进程新 479 分钟」，**真实是 -1 分钟 —— 同一份代码**。
# 判定方向对、量级错，而量级错到足以把「是」读成「否」。
# 这和今天其它坑同形：**工具给出了一个自信的错答案。**
# 本版用 `date -j -f`（不带 -u，按本地时区解析），并打印双时区供肉眼复核。

export PATH="/opt/homebrew/bin:/usr/bin:/bin"
cd "$HOME/ant-convergence" || exit 1

echo "本机时区偏移: $(date +%z)（lstart 按此解析）"
echo
echo "| 文件 | pid | 进程启动 | 文件 mtime | 差(分钟) | 同一份代码？ |"
echo "|---|---|---|---|---|---|"

check() {
  local pat="$1" pidsrc="$2" file="$3"
  local pid
  if [ "$pidsrc" = "-" ]; then pid=$(pgrep -f "$pat" | head -1); else pid=$(cat "$pidsrc" 2>/dev/null); fi
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    echo "| \`$(basename "$file")\` | — | 未在跑 | — | — | — |"; return
  fi
  local lstart pstart fmtime diff verdict
  lstart=$(ps -p "$pid" -o lstart= | sed 's/^ *//')
  # 关键：不带 -u，按本地时区解析
  pstart=$(date -j -f "%a %b %d %T %Y" "$lstart" +%s 2>/dev/null)
  [ -z "$pstart" ] && pstart=$(date -j -f "%a %b %e %T %Y" "$lstart" +%s 2>/dev/null)
  fmtime=$(stat -f %m "$file" 2>/dev/null)
  if [ -z "$pstart" ] || [ -z "$fmtime" ]; then
    echo "| \`$(basename "$file")\` | $pid | 解析失败($lstart) | — | — | 无法判定 |"; return
  fi
  diff=$(( (fmtime - pstart) / 60 ))
  if [ "$fmtime" -gt "$pstart" ]; then verdict="**否 — 文件更新**"; else verdict="是"; fi
  echo "| \`$(basename "$file")\` | $pid | $(date -u -r "$pstart" +%H:%M:%SZ) | $(date -u -r "$fmtime" +%H:%M:%SZ) | $diff | $verdict |"
}

check "ant_spot\.py"     "spot.pid"                            "$HOME/ant-convergence/ant_spot.py"
check "spot_runner\.sh"  "-"                                   "$HOME/ant-convergence/spot_runner.sh"
check "spot_archive\.py" "$HOME/ant-spot-archive/archive.pid"  "$HOME/ant-spot-archive/spot_archive.py"
check "archive_runner\.sh" "-"                                 "$HOME/ant-spot-archive/archive_runner.sh"
check "arm_newcode\.sh"  "-"                                   "$HOME/ant-convergence/arm_newcode.sh"

echo
echo "=== 常驻自检在不在运行时（「0 次告警」能不能引用的前提）==="
printf "  ant_spot.py 文件里 log_constant_audit: %s 处\n" "$(grep -c 'log_constant_audit' ant_spot.py)"
printf "  spot.log 里出现过「常量自检」:          %s 次\n" "$(grep -c '常量自检' spot.log)"
echo
echo "  判读：文件里有、日志里 0 次 ⇒ **自检只在磁盘上、不在运行时**。"
echo "        此时 spot.log 里「没有自检告警」**不是证据**，只是那段代码没在跑。"
echo "        本路的解法已安排：01:05Z 由守护用新代码拉起（arm_newcode.sh）。"
