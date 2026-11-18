# -*- coding: utf-8 -*-
"""dump_oracle.py — 把 dev/test 的 gold 原样导出成预测文件（oracle 上限）。

用法：
  python scripts/pipeline/dump_oracle.py                 # 导出 dev + test
  python scripts/pipeline/evaluate_extraction.py tmp/eval/preds/oracle_v3_dev.jsonl --split dev

用途：验证评测器口径（oracle F1 必须等于 1.0），并作为对比表里的「规则上界」。
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths
import _schema
import json

OUT = _paths.EVAL / "preds"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    idx = _schema.entity_index()
    for split in ("dev", "test"):
        path = OUT / ("oracle_v3_%s.jsonl" % split)
        n = 0
        with open(path, "w", encoding="utf-8") as out:
            for ln in open(_paths.sp(split), encoding="utf-8"):
                g = json.loads(ln)
                tr = [{"head": idx[x["head_id"]]["text"],
                       "relation": x["relation_id"],
                       "tail": idx[x["tail_id"]]["text"],
                       "evidence_level": x.get("evidence_level", "C")}
                      for x in g["gold"]]
                out.write(json.dumps({"task_id": g["task_id"], "triples": tr},
                                     ensure_ascii=False) + "\n")
                n += 1
        print("oracle %s: %d 篇 -> %s" % (split, n, path))


if __name__ == "__main__":
    main()
