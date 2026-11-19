"""从真实文件生成「文件 → 时间戳字段 → 时间范围 → 覆盖什么」对照表。手写会过期。"""
import json, os, time

FILES = [
    ("data/spot_2026-11-19.jsonl",                      "仓内"),
    ("data/minbars_2026-11-19.jsonl",                   "仓内"),
    ("data/close_2026-11-19.json",                      "仓内"),
    ("~/ant-spot-archive/spot_2026-11-19.jsonl",        "仓外归档"),
    ("~/ant-spot-archive/minbars_2026-11-19.jsonl",     "仓外归档"),
    ("~/ant-spot-archive/recovered_from_autostash_2026-11-19.jsonl", "仓外抢救（混装）"),
]
CANDIDATE_TS = ["ts", "ts_utc", "fetched_at", "bar_ts_utc", "t_epoch", "ts_epoch", "bar_ts"]

base = os.path.expanduser("~/ant-convergence")
print("| 文件 | 位置 | 条数 | 时间戳字段（实测，按出现率） | 时间范围 | 覆盖 |")
print("|---|---|---|---|---|---|")
for rel, where in FILES:
    p = os.path.expanduser(rel) if rel.startswith("~") else os.path.join(base, rel)
    name = os.path.basename(p)
    if not os.path.exists(p):
        print("| `%s` | %s | — | — | — | 缺失 |" % (name, where)); continue
    if p.endswith(".json"):
        d = json.load(open(p))
        print("| `%s` | %s | 1 个对象 | `ts` / `t_epoch` | %s | 本日官方收盘价定稿（唯一覆盖写） |"
              % (name, where, d.get("ts"))); continue
    recs = []
    for ln in open(p, errors="replace"):
        ln = ln.strip()
        if not ln or ln[:7] in ("<<<<<<<", "=======", ">>>>>>>"): continue
        try: recs.append(json.loads(ln))
        except Exception: pass
    present = [(f, sum(1 for r in recs if r.get(f) is not None)) for f in CANDIDATE_TS]
    present = [(f, n) for f, n in present if n]
    fields = " / ".join("`%s`(%d%%)" % (f, round(100.0 * n / len(recs))) for f, n in
                        sorted(present, key=lambda x: -x[1]))
    iso = sorted(str(r.get("ts") or r.get("fetched_at")) for r in recs
                 if r.get("ts") or r.get("fetched_at"))
    kinds = {}
    for r in recs:
        k = r.get("kind") or r.get("src") or "(无 kind/src)"
        kinds[k] = kinds.get(k, 0) + 1
    cov = "、".join("%s×%d" % (k, v) for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
    print("| `%s` | %s | %d | %s | %s → %s | %s |"
          % (name, where, len(recs), fields,
             iso[0][11:] if iso else "?", iso[-1][11:] if iso else "?", cov))
