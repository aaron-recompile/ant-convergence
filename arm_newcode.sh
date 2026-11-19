#!/bin/bash
# 在「本场结束 → 次日盘前」这段死窗口里，让守护用新代码重新拉起 ant_spot.py。
#
# 为什么必须做：在跑的进程是旧代码，TRADING_DAY 写死 "2026-11-19"，**不会自动换天**。
# 到次日 09:00Z（04:00 ET 盘前开始），它会把次日的数据继续写进本场的文件
# —— 数据不丢但归属错，且因为文件一直在长、看起来完全正常（数据说明 7.21 / 7.22）。
# 新代码（095e5f7）里 TRADING_DAY 由当前时刻推导，拉起后即正确。
#
# 为什么等到死窗口：本场 20:00 ET 结束，次日盘前 04:00 ET 才开始，中间 8 小时无任何场次，
# 此时重启**零数据代价**。盘中或盘后重启都会多制造一个空洞
# （7.18.3 登记的两个真空洞共 95 秒，都是重启造成的）。
#
# 为什么只 kill 不 start：spot_runner.sh 是唯一的启动者。自己再起一个会出现两进程并写
# —— 18:32:00Z–18:32:34Z 那 8 个同秒双条就是这么来的（7.6）。

cd "$HOME/ant-convergence" || exit 1
export PATH="/opt/homebrew/bin:/usr/bin:/bin"
LOG="$HOME/ant-convergence/arm_newcode.log"
POST_CLOSE=1795136400          # 2026-11-20T01:00:00Z = 20:00 ET，本场结束
TARGET=$((POST_CLOSE + 300))   # 结束后 5 分钟再动，留余量
DEADLINE=1795165200            # 2026-11-20T09:00:00Z = 04:00 ET 次日盘前，必须在此之前完成

say() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$LOG"; }

say "任务启动。等到 $(date -u -r $TARGET '+%H:%M:%SZ' 2>/dev/null || echo 01:05Z) 再重启；硬期限 09:00Z。"

while [ "$(date -u +%s)" -lt "$TARGET" ]; do sleep 60; done

NOW=$(date -u +%s)
if [ "$NOW" -ge "$DEADLINE" ]; then
  say "!! 已过 09:00Z 硬期限才醒，跨日归属可能已经出错。仍执行重启，但须人工核对文件内容。"
fi

OLD=$(cat spot.pid 2>/dev/null)
if [ -z "$OLD" ] || ! kill -0 "$OLD" 2>/dev/null; then
  say "pidfile 为空或进程已不在（pid=$OLD）。守护应已自行拉起新代码，不做任何事。"
  say "当前 ant_spot 实例数 = $(pgrep -f 'ant_spot\.py' | wc -l | tr -d ' ')"
  exit 0
fi

MAIN_BEFORE=$(ps aux | grep -c '[c]ollector\.py')
ANT_BEFORE=$(wc -l < data/ant_2026-11-19.jsonl)
say "重启前：ant_spot pid=$OLD，主采集器实例=$MAIN_BEFORE，主采集数据=$ANT_BEFORE 行"

kill "$OLD"
say "已 kill $OLD，等守护拉起（它每 15 秒查一次）"
sleep 45

NEW=$(cat spot.pid 2>/dev/null)
CNT=$(pgrep -f 'ant_spot\.py' | wc -l | tr -d ' ')
MAIN_AFTER=$(ps aux | grep -c '[c]ollector\.py')
ANT_AFTER=$(wc -l < data/ant_2026-11-19.jsonl)
say "重启后：ant_spot pid=$NEW 实例数=$CNT，主采集器实例=$MAIN_AFTER，主采集数据=$ANT_AFTER 行"

if [ "$CNT" != "1" ]; then
  say "!! ant_spot 实例数 = $CNT，不是 1。必须人工处理（两进程并写会产生同秒双条）。"
fi
if [ "$MAIN_AFTER" != "1" ]; then
  say "!! 主采集器实例数 = $MAIN_AFTER，不是 1。本任务没碰它，须人工查。"
fi

# 新代码必须自报：TRADING_DAY 推导值 + 常驻自检结果
say "新进程自报："
PYTHONPATH=. python3 -c "
import ant_spot as S
print('  TRADING_DAY(推导) =', S.TRADING_DAY)
print('  REGULAR_CLOSE     =', S.REGULAR_CLOSE)
print('  ET_TO_UTC_OFFSET  =', S.ET_TO_UTC_OFFSET)
p = S.audit_constants()
print('  常驻自检问题数     =', len(p))
for x in p: print('  !', x)
" >> "$LOG" 2>&1

say "日志里 spot.log 尾部："
tail -4 spot.log >> "$LOG" 2>&1
say "任务结束。"
