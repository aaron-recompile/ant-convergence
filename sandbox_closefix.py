#!/usr/bin/env python3
"""在沙箱里跑打过补丁的 spot_close_fix.py,对 2026-11-19 做回归。

**绝不能直接对 11-19 跑真的** —— close_2026-11-19.json 已进 Zenodo 包,
且我验收过它与包内逐字节相同。覆盖它会破坏一个已发布的制品。

办法:导入模块、把 DATA / SPOT / CLOSE 三个模块级量重指向临时目录,再调 main()。
(这三个量在模块级由 DATA 派生 —— 正是 7.46 那个形状,所以必须三个都改,
 不能只改 DATA。改完后断言它们都落在沙箱里。)
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-11-19"
REAL = os.path.expanduser("~/ant-convergence/data")
SRC = os.path.expanduser("~/ant-convergence/spot_close_fix.py")

box = tempfile.mkdtemp(prefix="closefix_sandbox_")
# 只复制它会读的那个 spot 文件(它会向其追加一行 —— 在沙箱里追加)
src_spot = os.path.join(REAL, "spot_%s.jsonl" % DAY)
if os.path.exists(src_spot):
    shutil.copy(src_spot, os.path.join(box, "spot_%s.jsonl" % DAY))
print("沙箱: %s" % box)

sys.argv = ["spot_close_fix.py", "--day", DAY]
spec = importlib.util.spec_from_file_location("closefix", SRC)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

# 三个按 DATA 派生的量全部重指向 —— 不能只改 DATA(7.46)
m.DATA = box
m.SPOT = os.path.join(box, "spot_%s.jsonl" % DAY)
m.CLOSE = os.path.join(box, "close_%s.json" % DAY)
assert m.DAY == DAY, "DAY 不是 %s 而是 %s" % (DAY, m.DAY)
for name in ("DATA", "SPOT", "CLOSE"):
    v = getattr(m, name)
    assert v.startswith(box), "**%s 仍指向沙箱之外: %s** —— 中止" % (name, v)
print("  三个路径全部落在沙箱内 ✓")
print("  真实 close_%s.json 的修改时间(跑完后应不变): %s"
      % (DAY, os.path.getmtime(os.path.join(REAL, "close_%s.json" % DAY))
         if os.path.exists(os.path.join(REAL, "close_%s.json" % DAY)) else "不存在"))
before = (os.path.getmtime(os.path.join(REAL, "close_%s.json" % DAY))
          if os.path.exists(os.path.join(REAL, "close_%s.json" % DAY)) else None)

m.main()

out = json.load(open(m.CLOSE))
print()
print("=== 沙箱结果（%s）===" % DAY)
for k in ("official_close_usd", "finalized", "primary_stamp_says_closed",
          "cross_check_values", "cross_check_unanimous", "cross_check_dissenters",
          "reject_why", "warn"):
    print("  %-28s %s" % (k, json.dumps(out.get(k), ensure_ascii=False)))
print("  nasdaq_historical:")
h = (out.get("sources") or {}).get("nasdaq_historical") or {}
for k in ("row_present", "totalRecords", "open_usd", "high_usd", "low_usd",
          "close_usd", "volume_raw"):
    print("      %-14s %s" % (k, h.get(k)))
print("  supersedes(追加行里):")
last = open(m.SPOT).read().strip().split("\n")[-1]
try:
    print("      %s" % json.loads(last).get("supersedes"))
except Exception:
    print("      (无法解析最后一行)")
print()
print("  caveat:")
print("      %s" % out.get("caveat"))

after = (os.path.getmtime(os.path.join(REAL, "close_%s.json" % DAY))
         if os.path.exists(os.path.join(REAL, "close_%s.json" % DAY)) else None)
print()
print("=== 真实文件未被触碰 ===")
print("  close_%s.json 修改时间 前=%s 后=%s  未变: %s"
      % (DAY, before, after, before == after))
assert before == after, "**真实文件被改了 —— 严重**"
