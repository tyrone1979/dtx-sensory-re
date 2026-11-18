import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
# -*- coding: utf-8 -*-
"""debug_empty.py — 诊断模型为何对部分论文输出空三元组（打印原始返回）。"""
import json
import sys
from pathlib import Path

HERE = _paths.DATA
sys.path.insert(0, str(HERE))

from run_llm_extraction import build_prompt, load_tasks  # noqa: E402

SPLIT = sys.argv[1] if len(sys.argv) > 1 else "dev"
PRED = sys.argv[2] if len(sys.argv) > 2 else str(_paths.EVAL / "preds_remote" / "predictions_dev.jsonl")
N = int(sys.argv[3]) if len(sys.argv) > 3 else 12
MODEL = sys.argv[4] if len(sys.argv) > 4 else "/home/zhaolei/models/Qwen2.5-7B-Instruct"

tasks = {t["task_id"]: t for t in load_tasks(SPLIT)}
empties = []
with open(PRED, encoding="utf-8") as f:
    for l in f:
        r = json.loads(l)
        if not r["triples"] and r["task_id"] in tasks:
            empties.append(tasks[r["task_id"]])
        if len(empties) >= N:
            break

print("待诊断空输出样本: %d 条" % len(empties))

from vllm import LLM, SamplingParams  # noqa: E402

llm = LLM(model=MODEL, dtype="float16", gpu_memory_utilization=0.9,
          max_model_len=8192, tensor_parallel_size=1)
sp = SamplingParams(temperature=0.0, max_tokens=512)
msgs = [[{"role": "user", "content": build_prompt(t)}] for t in empties]
outs = llm.chat(msgs, sp)

for t, o in zip(empties, outs):
    txt = o.outputs[0].text if o.outputs else ""
    fin = o.outputs[0].finish_reason if o.outputs else "none"
    print("=" * 78)
    print("TASK", t["task_id"], "| finish:", fin, "| prompt_chars:", len(build_prompt(t)))
    print("TITLE:", str(t["input"].get("title"))[:110])
    print("ABS  :", str(t["input"].get("abstract"))[:300].replace("\n", " "))
    print("--- RAW (前 500 字) ---")
    print(txt[:500])
