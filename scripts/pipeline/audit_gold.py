import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""
audit_gold.py — gold truth 噪声审计（无需 GPU）

对每条 gold 三元组判断它在摘要中是否有「句内共现」支撑：
  strong  : 同一句里同时出现 head 别名 与 tail 别名（远程监督真正可见的证据）
  weak    : 全文出现但不在同一句 —— 多为全局兜底（cross-product）产物，噪声概率高
  unknown : 该节点在别名表里没有可匹配模式，无法判定

产出 benchmark/gold_strength.json：{task_id: ["strong"|"weak"|"unknown", ...]}（与 gold 顺序一一对应）
评测时用 --strong-only 只保留 strong，得到「去噪 gold」指标。

用法：
  python dataset/audit_gold.py
"""
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = _paths.DATA
BENCH = _paths.BM
OUT = _paths.AUX / "gold_strength.json"


def load_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def main():
    # v3 语义：gold 每条自带 evidence 证据句，strong = 头/尾实体的任一写法都出现在
    # 该证据句里（token 级），weak = 只能回溯到全文共现。不再依赖 literature.jsonl 反查。
    idx = defaultdict(set)                    # {id: {规范写法 token 键, ...}}
    def _key(s):
        return tuple(w for w in re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).split())
    for e in _schema.entities():
        k = _key(e["text"])
        if k:
            idx[e["id"]].add(k)

    def _in(text, eid):
        tk = _key(text)
        n = len(tk)
        for pat in idx.get(eid, ()):
            m = len(pat)
            if m and any(tk[i:i + m] == pat for i in range(n - m + 1)):
                return True
        return False

    golds = []
    for _s in _paths.SPLITS:
        golds += load_jsonl(_paths.sp(_s))
    core = _paths.SOURCE / "gold_core_human.jsonl"
    if core.exists():
        golds += load_jsonl(core)
    out, stat = {}, {"strong": 0, "weak": 0, "unknown": 0}
    for g in golds:
        flags = []
        for t in g["gold"]:
            hid, tid = t.get("head_id", ""), t.get("tail_id", "")
            if not idx.get(hid) or not idx.get(tid):
                flags.append("unknown")
                continue
            ev = t.get("evidence", "")
            flags.append("strong" if (_in(ev, hid) and _in(ev, tid)) else "weak")
        for f in flags:
            stat[f] += 1
        out[g["task_id"]] = flags

    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    tot = sum(stat.values())
    print("gold 三元组审计：共 %d 条" % tot)
    for k, v in stat.items():
        print("  %-8s %6d (%.1f%%)" % (k, v, 100.0 * v / max(tot, 1)))
    by_split = {}
    for g in golds:
        by_split.setdefault(g.get("split", "core"), []).extend(out[g["task_id"]])
    print("\n分集合 strong 占比：")
    for s, fs in sorted(by_split.items()):
        n = sum(1 for f in fs if f == "strong")
        print("  %-8s strong %d/%d (%.1f%%)" % (s, n, len(fs), 100.0 * n / max(len(fs), 1)))
    print("\n写出:", OUT)


if __name__ == "__main__":
    main()
