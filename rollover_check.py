#!/usr/bin/env python3
"""本路换天链路的两级核对。**只读:不 kill、不写 data/、不碰 git。**

另一个会话指出本路比他多一级前置条件，这个区分必须写清：

| | depth 那路 | 本路 spot |
|---|---|---|
| 换天机制 | `rec["ts_utc"][:10]` 逐条推导 | `TRADING_DAY` 模块级推导（**新代码**） |
| 需要先重启吗 | 不需要 | **需要** —— 01:05Z 那次把新代码装进运行时 |
| 换天时刻 | UTC 00:00 | **09:00Z**（04:00 ET 盘前开始） |

所以本路是**两级**：A 重启成功 → B 换天成功。A 不成立时 B 必然不成立，
而且 B 的失败会长得像「换天逻辑有问题」—— 实际原因是新代码没装进去。
**分两级报，就不会把前置条件的失败误诊成逻辑的失败。**

用法：`--stage a`（01:05Z 之后跑）/ `--stage b`（09:00Z 之后跑）。
每一级都把**失败的样子**列出来，不留给读者推断。
"""
import calendar
import io
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
REPO = os.path.join(HOME, "ant-convergence")
DATA = os.path.join(REPO, "data")
# **不要把「我记下来的 pid」当输入。** 初版写的是 OLD_PID = 13784 —— 那是我上一轮
# 观察到的数，不是检查时实测的。后果比假 FAIL 坏：若守护因别的原因在 01:05Z 前
# 重启过一次，当前 pid 自然就不是 13784 了，A 级那条「pid 已变」会**假 PASS**，
# 于是在 arm_newcode 根本没跑的情况下报告「重启成功」。
#
# 改为从 arm_newcode.log 里**实测**它到底杀了哪个 pid（它自己会写「已 kill <pid>」），
# 并要求它写过「任务结束」。这样判据链是：
#   任务确实动过手（它自己的日志） → 它杀的那个 pid 已不在 → 当前 pid 与之不同
# 每一环都是读出来的，没有一环来自记忆。
KILLED_PID_RE = re.compile(r"已 kill (\d+)")
DAY_A = "2026-11-19"
DAY_B = "2026-11-20"
SAMPLE_GAP = 40                      # 取样间隔，需大于最慢一档的采样周期


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()


def _count_in(path, needle):
    """数 path 里含 needle 的行数。文件不存在算 0。不经 shell。"""
    if not os.path.exists(path):
        return 0
    n = 0
    for ln in io.open(path, errors="replace"):
        if needle in ln:
            n += 1
    return n


def size(p):
    try:
        return os.path.getsize(p)
    except OSError:
        return None


def lines_days(p):
    """返回该文件里出现过的 trading_day 集合（jsonl）。"""
    out = set()
    if not os.path.exists(p):
        return out
    for ln in io.open(p, errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        v = d.get("trading_day")
        if v:
            out.add(v)
        elif d.get("ts"):
            out.add(d["ts"][:10])
        elif d.get("fetched_at"):
            out.add(d["fetched_at"][:10])
    return out


def report(stage, checks, failure_modes):
    bad = [n for n, ok, _ in checks if not ok]
    print("== 第 %s 级核对 @ %s ==" % (stage, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())))
    for n, ok, detail in checks:
        print("  [%s] %-46s %s" % ("PASS" if ok else "FAIL", n, detail))
    print()
    if bad:
        print("  失败项: %s" % "、".join(bad))
        print("  失败的样子（不留给读者推断）：")
        for m in failure_modes:
            print("    - %s" % m)
    else:
        print("  第 %s 级通过。" % stage)
    return not bad


def stage_a():
    """01:05Z 之后：那次预约重启是否真的把新代码装进了运行时。"""
    pid = sh("cat %s/spot.pid 2>/dev/null" % REPO)
    cnt = sh("pgrep -f 'ant_spot\\.py' | wc -l | tr -d ' '")
    main = sh("ps aux | grep -c '[c]ollector\\.py'")
    log = os.path.join(REPO, "spot.log")
    # **在 Python 里数，不经 shell。** 初版写的是
    #   int(sh("grep -c '常量自检' %s || echo 0"))
    # `grep -c` 没匹配时输出 "0" **并且退出码非 0**，于是 `|| echo 0` 又追加一个 "0"，
    # 得到 "0\n0"，int() 直接炸。这和今天其它几个坑同形：
    # **出错的是「经过 shell 表达它」的那一层**（见 7.12.1 的 BRE、7.19 的 heredoc、
    # 7.26 的 lstrat 时区）。能在 Python 里做的就不要绕 shell。
    audit_hits = _count_in(log, "常量自检")
    derived = sh("cd %s && PATH=/opt/homebrew/bin:/usr/bin:/bin PYTHONPATH=. "
                 "python3 -c 'import ant_spot as S; print(S.TRADING_DAY)' 2>/dev/null" % REPO)
    arm_log = os.path.join(REPO, "arm_newcode.log")
    arm_bang = _count_in(arm_log, "!!")

    # 实测：arm_newcode 自己记下它杀了哪个 pid、以及它是否跑完
    arm_txt = io.open(arm_log, errors="replace").read() if os.path.exists(arm_log) else ""
    killed = KILLED_PID_RE.search(arm_txt)
    killed_pid = killed.group(1) if killed else None
    arm_done = "任务结束" in arm_txt

    checks = [
        ("arm_newcode 确实动过手（日志里有「已 kill <pid>」）",
         killed_pid is not None, "被杀的 pid=%s" % (killed_pid or "无此记录")),
        ("arm_newcode 跑完了（日志里有「任务结束」）",
         arm_done, "有" if arm_done else "**无**"),
        ("当前 pid 与被杀的那个不同（实测，不用记下来的数）",
         bool(killed_pid) and pid.isdigit() and pid != killed_pid,
         "现 pid=%s / 被杀=%s" % (pid or "无", killed_pid or "无")),
        ("ant_spot 实例数 == 1", cnt == "1", "实测 %s" % cnt),
        ("主采集器实例数 == 1", main == "1", "实测 %s"
         % main),
        # **这一条才是「新代码进了运行时」的直接证据**：
        # 旧代码里没有常驻自检，所以 spot.log 里出现过这行字 ⇔ 跑的是新代码。
        ("spot.log 里出现过常驻自检（新代码的指纹）", audit_hits > 0,
         "命中 %d 次" % audit_hits),
        ("推导出的 TRADING_DAY == %s" % DAY_A, derived == DAY_A, "实测 %s" % (derived or "取不到")),
        ("arm_newcode.log 里没有 !!", arm_bang == 0, "!! 出现 %d 次" % arm_bang),
    ]
    modes = [
        "日志里没有「已 kill」⇒ 预约任务没跑到那一步；查它是否还在等（它每 60 秒醒一次）。",
        "有「已 kill」但当前 pid 与之相同 ⇒ kill 没生效（权限？进程忽略 TERM？）。",
        "实例数 != 1 ⇒ 两进程并写（会产生同秒双条，见 7.6）；按 pid 杀掉多余的那个。",
        "自检 0 次命中 ⇒ **跑的还是旧代码**，第二级必然失败，且会长得像换天逻辑有问题。",
        "主采集器 != 1 ⇒ 与本路无关，但必须人工查（本任务从不碰它）。",
    ]
    return report("A（重启是否把新代码装进运行时）", checks, modes)


def stage_b():
    """09:00Z 之后：是否真的换到了新一天的文件，且没有双写/串档。"""
    fa = os.path.join(DATA, "spot_%s.jsonl" % DAY_A)
    fb = os.path.join(DATA, "spot_%s.jsonl" % DAY_B)
    a1, b1 = size(fa), size(fb)
    time.sleep(SAMPLE_GAP)
    a2, b2 = size(fa), size(fb)

    da, db = lines_days(fa), lines_days(fb)
    checks = [
        ("旧文件已停止增长", a1 is not None and a1 == a2,
         "%s → %s 字节" % (a1, a2)),
        ("新文件已出现", b2 is not None, os.path.basename(fb) + ("（在）" if b2 else "（**不存在**）")),
        ("新文件在增长", b1 is not None and b2 is not None and b2 > b1,
         "%s → %s 字节" % (b1, b2)),
        ("旧文件里没有 %s 的记录" % DAY_B, DAY_B not in da, "该文件含日期 %s" % sorted(da)),
        ("新文件里没有 %s 的记录" % DAY_A, DAY_A not in db, "该文件含日期 %s" % sorted(db)),
    ]
    modes = [
        "新文件不存在而旧文件还在长 ⇒ 没换天（最可能:第一级没过,跑的还是旧代码）。",
        "**两个文件同时在长 ⇒ 双写**，和没换天一样严重；只看「新文件出现了吗」会把它读成正常。",
        "任一文件含对方那天的记录 ⇒ 串档；按 trading_day 字段剔除，并登记到数据说明。",
        "旧文件停了但新文件也不长 ⇒ 进程死了；查 spot_runner.log 是否在反复拉起。",
    ]
    return report("B（是否换到新一天的文件）", checks, modes)


if __name__ == "__main__":
    st = sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "a"
    ok = stage_a() if st.lower() == "a" else stage_b()
    print()
    print("注：本脚本只读 —— 不 kill 进程、不写 data/、不碰 git。")
    sys.exit(0 if ok else 1)
