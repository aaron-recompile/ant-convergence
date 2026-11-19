#!/usr/bin/env python3
"""实测换天链路：从推导出的 TRADING_DAY 一直到**实际写出去的文件名**。

另一个会话指出我的证据只到「常量推导边界 9 档全过」，那证明的是推导函数对，
**没有证明「推导出来的日期真的决定了写出去的文件名」** ——
正是数据说明 7.22.2 那个教训：改了一处，没验依赖它的那几处。

本脚本把**部署版 `ant_spot.py` 原样导入**（先用正则确认测的就是它的那几行），
在 `tempfile.TemporaryDirectory()` 里把输出路径指过去，喂合成记录，
看落盘的文件名是不是推导出的那一天。

**不碰 `data/`、不碰 git、不碰在跑的进程**：只 import 模块、只写临时目录。
"""
import importlib
import io
import json
import os
import re
import sys
import tempfile

SRC = os.path.expanduser("~/ant-convergence/ant_spot.py")
sys.path.insert(0, os.path.dirname(SRC))

# ── ① 先确认部署版里确实是这几行在决定文件名 ──────────────────────
src = io.open(SRC, encoding="utf-8").read()
checks = {
    "TRADING_DAY 取自环境变量或推导":
        r'TRADING_DAY\s*=\s*os\.environ\.get\("ANT_TRADING_DAY"\)\s*or\s*derive_trading_day\(\)',
    "SPOT_PATH 由 TRADING_DAY 拼出":
        r'SPOT_PATH\s*=\s*os\.path\.join\(DATA,\s*"spot_%s\.jsonl"\s*%\s*TRADING_DAY\)',
    "BARS_PATH 由 TRADING_DAY 拼出":
        r'BARS_PATH\s*=\s*os\.path\.join\(DATA,\s*"minbars_%s\.jsonl"\s*%\s*TRADING_DAY\)',
    "CLOSE_PATH 由 TRADING_DAY 拼出":
        r'CLOSE_PATH\s*=\s*os\.path\.join\(DATA,\s*"close_%s\.json"\s*%\s*TRADING_DAY\)',
}
print("== ① 确认测的就是部署版里那几行 ==")
missing = []
for name, pat in checks.items():
    hit = re.search(pat, src) is not None
    print("   [%s] %s" % ("OK" if hit else "**没找到**", name))
    if not hit:
        missing.append(name)
if missing:
    print("   → 部署版的写法与预期不符，本测试无意义。退出。")
    sys.exit(2)

# ── ② 对三个连续交易日，各跑一次完整链路 ──────────────────────────
print()
print("== ② 换天链路实测：推导日 → 文件名 → 实际落盘 ==")
bad = 0
for day in ("2026-11-19", "2026-11-20", "2026-11-21"):
    with tempfile.TemporaryDirectory(prefix="dayswitch_") as tmp:
        os.environ["ANT_TRADING_DAY"] = day
        for m in [k for k in list(sys.modules) if k == "ant_spot"]:
            del sys.modules[m]
        S = importlib.import_module("ant_spot")

        # 把输出目录指到临时目录，并按部署版同样的拼法重算三个路径
        S.DATA = tmp
        S.SPOT_PATH = os.path.join(tmp, "spot_%s.jsonl" % S.TRADING_DAY)
        S.BARS_PATH = os.path.join(tmp, "minbars_%s.jsonl" % S.TRADING_DAY)
        S.CLOSE_PATH = os.path.join(tmp, "close_%s.json" % S.TRADING_DAY)

        # 喂一条合成记录走真正的 emit()
        S.emit({"ts": day + "T15:00:00Z", "t_epoch": S.REGULAR_OPEN + 1800,
                "trading_day": S.TRADING_DAY, "kind": "quote",
                "collector": "dayswitch_test", "synthetic": True})

        files = sorted(os.listdir(tmp))
        want = "spot_%s.jsonl" % day
        ok_name = files == [want]
        recs = [json.loads(x) for x in io.open(os.path.join(tmp, want), encoding="utf-8")
                if x.strip()] if want in files else []
        days_in = sorted({r.get("trading_day") for r in recs})
        ok_body = days_in == [day]
        ok = ok_name and ok_body
        bad += 0 if ok else 1
        print("   [%s] ANT_TRADING_DAY=%s → TRADING_DAY=%s  落盘 %s  %d 条，日期 %s"
              % ("PASS" if ok else "FAIL", day, S.TRADING_DAY, files, len(recs), days_in))
        if not ok_name:
            print("        期望只有 %s" % want)

os.environ.pop("ANT_TRADING_DAY", None)

# ── ③ 不带覆盖时，按时刻推导的那一档也要走一遍 ────────────────────
print()
print("== ③ 不带环境变量：按当前时刻推导 ==")
for m in [k for k in list(sys.modules) if k == "ant_spot"]:
    del sys.modules[m]
S = importlib.import_module("ant_spot")
import calendar
import time


def ep(x):
    return calendar.timegm(time.strptime(x, "%Y-%m-%dT%H:%M:%SZ"))


cases = [("2026-11-20T08:59:00Z", "2026-11-19", "03:59 ET 切换点前"),
         ("2026-11-20T09:00:00Z", "2026-11-20", "04:00 ET 盘前开始")]
for iso, want, why in cases:
    got = S.derive_trading_day(ep(iso))
    ok = got == want
    bad += 0 if ok else 1
    print("   [%s] %s → %s（期望 %s）%s"
          % ("PASS" if ok else "FAIL", iso, got, want, why))
    # 并验这一天拼出的文件名
    print("        该日文件名会是 spot_%s.jsonl" % got)

print()
print("== 结论 ==")
if bad == 0:
    print("   链路实测通过：**推导出的日期确实决定了写出去的文件名**，三个连续交易日零串档。")
    print("   证据等级：表达式与落盘链路**已实测**；")
    print("   但「进程真的跨过一次午夜」仍未发生 —— 那要等 09:00Z。两者不可互相代替。")
else:
    print("   **%d 项失败** —— 换天链路有问题，必须在 09:00Z 前查清。" % bad)
sys.exit(1 if bad else 0)
