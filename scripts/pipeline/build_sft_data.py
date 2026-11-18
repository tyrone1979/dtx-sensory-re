import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""
build_sft_data.py — 从 benchmark train split 构造 SFT 训练数据。

prompt 与 run_llm_extraction.build_prompt 完全一致（闭集词表 + 关系规则，无 few-shot），
completion 为 gold 三元组 JSON 数组 + EOS。保证「训练即任务」。

用法：python dataset/build_sft_data.py   # 产出 dataset/sft/sft_train.jsonl
"""
import json
import sys
from pathlib import Path

HERE = _paths.DATA
BENCH = _paths.BM
OUT = _paths.EVAL / "sft"
sys.path.insert(0, str(HERE))
from run_llm_extraction import build_prompt  # noqa: E402


def main():
    OUT.mkdir(exist_ok=True)
    n = 0
    with open(_paths.sp("train"), encoding="utf-8") as f, \
         open(OUT / "sft_train.jsonl", "w", encoding="utf-8") as out:
        for l in f:                                    # 自包含：input 与 gold 同一行
            g = json.loads(l)
            t = g
            if not t:
                continue
            completion = json.dumps(
                [{"head": x["head"], "relation": x["relation"], "tail": x["tail"],
                  "evidence_level": x.get("evidence_level", "C")}
                 for x in _schema.expand_gold(g["gold"])],
                ensure_ascii=False)
            out.write(json.dumps({
                "task_id": g["task_id"],
                "prompt": build_prompt(t, fewshot=False),
                "completion": completion,
            }, ensure_ascii=False) + "\n")
            n += 1
    print("SFT 训练样本:", n, "->", OUT / "sft_train.jsonl")


if __name__ == "__main__":
    main()
