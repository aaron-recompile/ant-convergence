#!/bin/bash
# 两级换天核对的定时执行。一次定时，不是轮询。
#
# 本路的换天链路是两级（另一个会话指出的，他那路只有一级）：
#   A 级 01:10Z —— arm_newcode.sh 那次预约重启是否真的把新代码装进了运行时
#   B 级 09:05Z —— 09:00Z（04:00 ET 盘前）是否真的换到了 spot_2026-11-20.jsonl
# A 不成立时 B 必然不成立，且 B 的失败会长得像「换天逻辑有问题」。分两级报就不会误诊。
#
# 两级都已在事件发生前跑过一次、确认会 FAIL（rc=1）——
# 一个只会在成功时被跑一次的检查，没人知道它失败时会不会出声。
#
# 只读：rollover_check.py 不 kill、不写 data/、不碰 git。

export PATH="/opt/homebrew/bin:/usr/bin:/bin"
cd "$HOME/ant-convergence" || exit 1
LOG="$HOME/ant-convergence/rollover_watch.log"

say() { echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] $*" >> "$LOG"; }

A_AT=1795137000   # 2026-11-20T01:10:00Z —— arm_newcode 在 01:05Z 动手、sleep 45 等守护，
                  # 故 A 级必须在那之后。**初版写 1795136700 = 01:05:00Z，少了 300 秒**，
                  # 会在重启还没完成时跑、虚报一次 FAIL。又是「手算 epoch」那一类
                  # （今天第三次：数据说明 7.17.1、7.22.1、本条）。
                  # 它被抓住的唯一原因是脚本启动时把换算后的时刻**打印出来**了。
B_AT=1795165500   # 2026-11-20T09:00:00Z + 300s = 09:05:00Z（换天后 5 分钟）

# **打印给人看的时刻必须由程序从同一个变量推出，不得与变量并列硬写。**
# 初版这行把「01:10Z / 09:05Z」硬写在字面量里，与 A_AT / B_AT 并列 ——
# 而 A_AT 初版恰好少了 300 秒（实际是 01:05Z），这行字照样会说「01:10Z」。
# 字面量与算出的值一致是运气，不是设计。
say "任务启动。A 级 $(date -u -r $A_AT +%FT%TZ)，B 级 $(date -u -r $B_AT +%FT%TZ)。事件前的预检已确认两级都会 FAIL。"

while [ "$(date -u +%s)" -lt "$A_AT" ]; do sleep 60; done
say "---- A 级：重启是否把新代码装进运行时 ----"
python3 rollover_check.py --stage a >> "$LOG" 2>&1
A_RC=$?
say "A 级 rc=$A_RC $([ $A_RC -eq 0 ] && echo '（通过）' || echo '（**失败，见上**）')"
if [ "$A_RC" -ne 0 ]; then
  say "A 级未过 ⇒ B 级预期也会失败，且原因是前置条件而非换天逻辑。仍会在 09:05Z 跑 B 级留证。"
fi

while [ "$(date -u +%s)" -lt "$B_AT" ]; do sleep 60; done
say "---- B 级：是否换到新一天的文件 ----"
python3 rollover_check.py --stage b >> "$LOG" 2>&1
B_RC=$?
say "B 级 rc=$B_RC $([ $B_RC -eq 0 ] && echo '（通过）' || echo '（**失败，见上**）')"

say "两级都跑完。A=$A_RC B=$B_RC"
if [ "$A_RC" -eq 0 ] && [ "$B_RC" -eq 0 ]; then
  say "结论：换天链路两级均已**实测通过** —— 此前只有代码级验证（数据说明 7.25 证据等级表）。"
else
  say "结论：链路有失败项，须人工处理。失败的样子已在上面各级输出里列出。"
fi
