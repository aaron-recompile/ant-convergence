#!/usr/bin/env python3
"""把包内 README 的文件清单与 zip 的实际条目逐项对照。

README 自称「数字全部由打包脚本读自文件本身」。若清单与实际条目不符,
那句话就不成立,而这个包是要上 Zenodo 的。

另:README 自称「打包于 2026-11-20T20:11:25Z」,而 zip 的 mtime 是 21:04:16Z,
差 53 分钟 —— 可能是 21:04 重打包时复用了旧 README。
"""
import os
import re
import zipfile

Z = os.path.expanduser("~/ant_listing_day_2026-11-19_v1.zip")
z = zipfile.ZipFile(Z)
names = [n for n in z.namelist() if not n.endswith("/")]
rd = z.read("README.md").decode("utf-8", "replace")

print("=== zip 实际条目 (%d) ===" % len(names))
info = {n: z.getinfo(n).file_size for n in names}
for n in sorted(names):
    print("  %-56s %12d 字节" % (n, info[n]))

# README 表格里形如 `data/xxx.jsonl` 的反引号路径
listed = re.findall(r"`([A-Za-z0-9_./-]+\.(?:jsonl|json|md|csv|py|txt))`", rd)
listed = sorted(set(listed))
print()
print("=== README 里以反引号提到的文件路径 (%d) ===" % len(listed))
for x in listed:
    print("  %s" % x)

data_names = {n for n in names}
print()
print("=== 对照 ===")
in_zip_not_readme = sorted(n for n in data_names
                           if n not in listed and (n.startswith("data/")
                                                   or n.startswith("rescued/")))
in_readme_not_zip = sorted(x for x in listed
                           if x not in data_names and ("/" in x))
print("  **在 zip 里但 README 未提及:**")
for x in in_zip_not_readme or ["（无）"]:
    print("     %s" % x)
print("  **README 提及但不在 zip 里:**")
for x in in_readme_not_zip or ["（无）"]:
    print("     %s" % x)

# README 表格里的行数/字节数与实际对照
print()
print("=== README 表格里的「字节」与 zip 内实际大小对照 ===")
rows = re.findall(
    r"\|\s*`([A-Za-z0-9_./-]+)`\s*\|[^|]*\|\s*([\d,]+)\s*\|[^|]*\|[^|]*\|\s*([\d,]+)\s*\|",
    rd)
if not rows:
    print("  （未能解析表格行 —— 格式与预期不符，下面只报条目对照）")
for path, lines, size in rows:
    want = int(size.replace(",", ""))
    got = info.get(path)
    ok = (got == want)
    print("  %-52s README %12d / 实际 %s   %s"
          % (path, want, ("%12d" % got) if got is not None else "   不在包内",
             "OK" if ok else "**不符**"))

print()
print("=== README 里的头号数字 ===")
for pat, what in ((r"开盘撮合\s*\$?([\d.]+)", "开盘撮合"),
                  (r"当日最高\s*\$?([\d.]+)", "当日最高"),
                  (r"官方收盘\s*\$?([\d.]+)", "官方收盘"),
                  (r"打包于\s*([0-9T:\-Z]+)", "自称打包时刻")):
    m = re.search(pat, rd)
    print("  %-12s %s" % (what, m.group(1) if m else "（未找到）"))
print("  zip 文件 mtime: %s" % __import__("time").strftime(
    "%Y-%m-%dT%H:%M:%SZ", __import__("time").gmtime(os.path.getmtime(Z))))
print()
print("  本路 2026-11-20 实测:Nasdaq 日线 11/19 行给 open=111.50 high=115.10")
print("  low=92.72 close=97.17 —— **当日最高是 115.10,不是 114.853**(7.48)。")
print("  README 若写 114.853 为「当日最高」,那是最高采样观测,不是当日最高价。")
