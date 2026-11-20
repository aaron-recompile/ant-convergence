#!/bin/bash
# 测 7.50 修法里**没测过**的那一支:退避中本场开始 → 拉起。
#
# 7.50 的沙箱只验了「本场已结束 → 退避」。那是我新加的分支;
# **走出这个分支的转换没测** —— 而那正是明天 09:00Z 要走的路。
# 我测了我新加的分支,没测走出它的转换。
#
# 只测守护逻辑,用桩替掉采集器:
#   - 不打 api.nasdaq.com(本路是该端点现货侧唯一消费者,不该为测试加压)
#   - 桩的命令行含 "ant_spot" 以便 alive() 的 ps|grep 能认出它
# 桩的行为由一个开关文件控制:PENDING 不存在 ⇒ --session-pending 返回 1(本场已结束)
#                              PENDING 存在   ⇒ 返回 0(本场待跑)
set -u
BOX=$(mktemp -d /tmp/runnertrans.XXXXXX)
cd "$BOX" || exit 1
cp ~/ant-convergence/spot_runner.sh .

# —— 桩:名字必须含 ant_spot，alive() 靠 ps 的命令行匹配 ——
cat > ant_spot.py <<'STUB'
#!/bin/bash
# 桩，不是真采集器。名字含 ant_spot 以便守护的 alive() 认出。
if [ "${1:-}" = "--session-pending" ]; then
  if [ -f "$(dirname "$0")/PENDING" ]; then
    echo "stub: pending=True"; exit 0
  else
    echo "stub: pending=False"; exit 1
  fi
fi
# 被当作采集器拉起：睡着，让 alive() 判它活。
# **不要用 exec** —— exec 会把进程映像替换成 sleep，命令行里就没有 "ant_spot"，
# 于是守护的 alive() 判死、每 15 秒重拉一次。实测过:拉起了 3 次。
# 真的 ant_spot.py 是 `python3 ant_spot.py`，命令行永远含 ant_spot。
sleep 600
STUB
chmod +x ant_spot.py
# 守护里是 `python3 ant_spot.py`，桩是 bash 脚本 —— 把调用改成直接执行
sed -i '' 's|/opt/homebrew/bin/python3 ant_spot.py|./ant_spot.py|g' spot_runner.sh
# **断言替换生效。** 初版用 `^  sleep 300$`（两空格），而真实缩进是四空格 ——
# sed 不匹配时静默返回 0，于是沙箱里退避仍是 300 秒，而文案那条 sed 匹配上了，
# 日志宣称「退避 5 秒」而代码睡 300 秒。阶段二等 14 秒当然看不到动静，
# 我差一步把这报成「守护的转换坏了」。
sed -i '' 's|^\( *\)sleep 300$|\1sleep 5|; s|退避 300 秒|退避 5 秒(沙箱)|' spot_runner.sh
grep -q 'sleep 5' spot_runner.sh || { echo "**替换未生效:找不到 sleep 5**"; exit 1; }
grep -q 'sleep 300' spot_runner.sh && { echo "**替换未生效:sleep 300 仍在**"; exit 1; }
echo "  替换已生效: $(grep -n 'sleep 5' spot_runner.sh | tr -d '\n')"
bash -n spot_runner.sh || { echo "沙箱脚本语法错"; exit 1; }


# 数桩进程:**不能用 pgrep -f 加全路径** —— 命令行是 `./ant_spot.py`（相对），
# 全路径永远匹配不上，会一直数到 0。按 pidfile 里的 pid 判，和守护用同一个判据。
count_stub() {
  local pid
  pid=$(cat spot.pid 2>/dev/null) || { echo 0; return; }
  [ -n "$pid" ] || { echo 0; return; }
  if kill -0 "$pid" 2>/dev/null && ps -p "$pid" -o command= 2>/dev/null | grep -q ant_spot; then
    echo 1
  else
    echo 0
  fi
}

echo "沙箱: $BOX"
echo
echo "=== 阶段一:本场已结束(无 PENDING 文件)⇒ 应只退避、不拉起 ==="
nohup bash ./spot_runner.sh >/dev/null 2>&1 &
RUN=$!
sleep 14
echo "  守护日志:"; sed 's/^/    /' spot_runner.log 2>/dev/null || echo "    (空)"
echo "  spot.pid: $(cat spot.pid 2>/dev/null || echo '未创建 ✓')"
echo "  桩进程数: $(count_stub)  (应为 0)"

echo
echo "=== 阶段二:本场开始(创建 PENDING)⇒ 应恰好拉起一次 ==="
touch PENDING
sleep 14
echo "  守护日志:"; sed 's/^/    /' spot_runner.log 2>/dev/null
echo "  spot.pid: $(cat spot.pid 2>/dev/null || echo '未创建 **✗**')"
N=$(count_stub)
echo "  桩进程数: $N  (应为 1)"

echo
echo "=== 阶段三:再等一轮 ⇒ 不应重复拉起 ==="
sleep 20
N2=$(count_stub)
LAUNCHES=$(grep -c "拉起" spot_runner.log 2>/dev/null || echo 0)
echo "  桩进程数: $N2  (应仍为 1)"
echo "  日志里「拉起」行数: $LAUNCHES  (应为 1)"
echo "  守护日志全文:"; sed 's/^/    /' spot_runner.log

echo
echo "=== 判读 ==="
[ "$N" = "1" ] && [ "$N2" = "1" ] && [ "$LAUNCHES" = "1" ] \
  && echo "  ✓ 转换正确:退避期零拉起;本场开始后恰好拉起一次;之后不重复。" \
  || echo "  ✗ **转换不正确** —— 看上面的计数"

kill "$RUN" 2>/dev/null
kill "$(cat spot.pid 2>/dev/null)" 2>/dev/null
sleep 1
echo "  清理后桩进程数: $(count_stub)"
cd / && rm -rf "$BOX"
echo "  沙箱已删"
