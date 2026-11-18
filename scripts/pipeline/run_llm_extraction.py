import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""
run_llm_extraction.py — 在 GPU 服务器上用本地 LLM 跑知识抽取 benchmark。

输入：dataset/benchmark/{train,dev,test}.jsonl（每行自包含 input + gold）
输出：predictions jsonl（与 scripts/pipeline/evaluate_extraction.py 兼容）

依赖（服务器上二选一）：
  pip install vllm                      # 后端 vllm（推荐，吞吐高）
  pip install torch transformers accelerate   # 后端 hf

用法示例（服务器 ~/digital-therapeutics 下）：
  # vLLM 后端，跑 dev（500 篇）
  python scripts/pipeline/run_llm_extraction.py --model Qwen/Qwen2.5-7B-Instruct \
      --backend vllm --split dev --out predictions_dev.jsonl

  # HF 后端，跑人工核验 gold（87 篇，论文主指标）
  python scripts/pipeline/run_llm_extraction.py --model /path/to/local-model \
      --backend hf --split test_core --out predictions_core.jsonl --fp16

  # 评测
  python scripts/pipeline/evaluate_extraction.py predictions_dev.jsonl --split dev --strict-level
  python scripts/pipeline/evaluate_extraction.py predictions_core.jsonl --split test_core --strict-level
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = _paths.DATA
BENCH = _paths.BM
RELATIONS = [r["id"] for r in _schema.relations()]   # 关系表里的全部 id（当前 12 种）


def load_vocab():
    """[v3 已废弃闭集词表] 开放实体口径下 head/tail 不再限于图谱词表。
    保留函数仅为兼容旧引用；返回空表。"""
    return [], []


RELATIONS = [r["id"] for r in _schema.relations()]   # 关系 id（当前 12 种，封闭）
REL_NAME2ID = _schema.rel_name2id()                  # 关系别名写法 → id


def build_fewshot():
    """从 train split 取 2 条真实 gold 作 few-shot（确定性）。"""
    picks = []
    try:
        with open(_paths.sp("train"), encoding="utf-8") as f:   # 自包含：input 与 gold 同一行
            for l in f:
                g = json.loads(l)
                if 1 <= len(g["gold"]) <= 3:
                    picks.append((g, g))
                if len(picks) >= 2:
                    break
    except Exception:
        pass
    return picks


FEWSHOT = build_fewshot()


def build_prompt(rec, fewshot=True):
    """v3 开放实体抽取 prompt：head/tail 用论文原文中的具体英文名词短语，关系限 12 个 id。
    与 evaluate_extraction.py 的开放实体匹配、build_sft_data.py 的训练 prompt 保持同一口径。"""
    inp = rec["input"]
    parts = [
        "You are a medical literature knowledge extraction assistant. Extract (head, relation, tail) triples from the abstract of a sensory-intervention study.",
        "",
        "[Hard constraints]",
        "1. Head entity: the specific intervention / stimulus / environmental design discussed in the abstract (e.g., 'auricular acupressure', 'nature view from window', 'forest therapy').",
        "2. Tail entity: the specific outcome measure or benefit reported (e.g., 'anxiety', 'blood pressure', 'sleep quality', 'cognitive function').",
        "3. Head and tail MUST be specific English noun phrases COPIED VERBATIM (or minimally inflected) from the title or abstract. Never invent, generalize, or translate.",
        "4. Relation must be one of: " + ", ".join(RELATIONS) + ".",
        "5. Only extract relations with positive first-hand evidence in the abstract. Skip negative results, protocols without results, narrative reviews without conclusions, case reports, animal/in-vitro studies, and economic evaluations.",
        "6. Direction rules: improves/enhances/promotes for upward benefits (sleep, well-being, cognition, immunity); reduces/alleviates/lowers for downward measures (stress, anxiety, pain, depression, cortisol, blood pressure); accelerates for time-to-outcome; affects only when the direction is genuinely unclear; evidence_supports for strong evidence claims (large/moderate effect sizes, 'more effective than', statistically significant improvement).",
        "7. Evidence level: A = systematic review/meta-analysis, B = RCT or quasi-experimental, C = observational/pre-post study, D = review/mechanism/consensus.",
        "8. Extract ALL supported benefits, usually 1-4 and at most 6; one head entity may map to multiple tails.",
        "Output ONLY a JSON array, no explanations, no markdown fences. Format: [{\"head\":\"...\",\"relation\":\"...\",\"tail\":\"...\",\"evidence_level\":\"C\"}]; output [] if nothing applies.",
        "",
    ]
    if fewshot:
        for task, g in FEWSHOT:
            a = task["input"]["abstract"][:400]
            ex = json.dumps([{"head": t["head"], "relation": t["relation"], "tail": t["tail"],
                              "evidence_level": t.get("evidence_level", "C")}
                             for t in _schema.expand_gold(g["gold"])],
                            ensure_ascii=False)
            parts += ["Example -- Title: %s" % task["input"]["title"][:120],
                      "Abstract: %s" % a, "Output: %s" % ex, ""]
    parts += ["To extract -- Title: %s" % inp.get("title", ""),
              "Abstract: %s" % inp.get("abstract", "")[:5000]]
    return "\n".join(parts)


def snap_rel(name):
    """v3 开放实体下 head/tail 不吸附；只有 relation 还需要归一到 12 个 id
    （模型可能输出 'reduce' / 'reduced' / 'lowers' 等写法变体）。匹配不到就原样返回。"""
    s = (name or "").strip()
    low = s.lower()
    if low in REL_NAME2ID:
        return REL_NAME2ID[low]
    if s in RELATIONS:
        return s
    # 轻度形态折叠：reduce/reduces/reduced/reducing → 按关系别名表再试一次
    for v, rid in REL_NAME2ID.items():
        if v.rstrip('e') == low.rstrip('e') or v.rstrip('d') == low.rstrip('d'):
            return rid
    return s


def _salvage_objects(s):
    """从残缺 JSON（被 max_tokens 截断）中逐个捞取完整的 {...} 对象。"""
    out = []
    for raw in re.findall(r"\{[^{}]*\}?", s):
        if not raw.endswith("}"):
            raw += "}"
        try:
            out.append(json.loads(raw))
        except Exception:
            # 最后再兜一次：直接按字段正则捞
            h = re.search(r'"head"\s*:\s*"([^"]*)"', raw)
            r = re.search(r'"relation"\s*:\s*"([^"]*)"', raw)
            t = re.search(r'"tail"\s*:\s*"([^"]*)"', raw)
            if h and t:
                out.append({"head": h.group(1), "relation": r.group(1) if r else "",
                            "tail": t.group(1)})
    return out


def parse_triples(text):
    """从模型输出中稳健解析 JSON 数组（容忍截断、代码块、前后解释文字）。"""
    if not text:
        return []
    arr = None
    m = re.search(r"\[.*\]", text, re.S)
    if m:
        try:
            arr = json.loads(m.group(0))
        except Exception:
            try:
                arr = json.loads(re.sub(r",\s*([\]}])", r"\1", m.group(0)))
            except Exception:
                arr = _salvage_objects(m.group(0))
    if arr is None:
        # 无闭合 ]，多半是被截断：从第一个 [ 开始逐个捞对象
        i = text.find("[")
        arr = _salvage_objects(text[i:] if i >= 0 else text)
    out = []
    if isinstance(arr, dict):
        arr = [arr]
    for t in arr if isinstance(arr, list) else []:
        if not isinstance(t, dict):
            continue
        out.append({
            "head": str(t.get("head", "")).strip(),
            "relation": str(t.get("relation", "")).strip(),
            "tail": str(t.get("tail", "")).strip(),
            "evidence_level": str(t.get("evidence_level", "")).strip()[:1].upper(),
        })
    return out


def load_tasks(split):
    tasks = []
    if split == "test_core":
        src = _paths.SOURCE / "gold_core_human.jsonl"
        with open(src, encoding="utf-8") as f:
            for l in f:
                g = json.loads(l)
                tasks.append({"task_id": g["task_id"], "pmid": g["pmid"],
                              "input": {"title": "", "abstract": ""}})
        # test_core 的输入在 split 文件里找不到时，用 literature.jsonl 回查
        lit = {}
        with open(_paths.SOURCE / "literature.jsonl", encoding="utf-8") as f:
            for l in f:
                r = json.loads(l)
                lit[r["pmid"]] = r
        for t in tasks:
            L = lit.get(t["pmid"], {})
            t["input"] = {"title": L.get("title", ""), "abstract": L.get("abstract", ""),
                          "year": L.get("year", ""), "pubtypes": L.get("pubtypes", [])}
        return tasks
    srcs = [_paths.sp(split)] if split else [_paths.sp(s) for s in _paths.SPLITS]
    for src in srcs:
        with open(src, encoding="utf-8") as f:
            for l in f:
                r = json.loads(l)
                tasks.append({"task_id": r["task_id"], "pmid": r["pmid"], "input": r["input"]})
    return tasks


def build_guided_schema():
    """v3 开放实体的受约束解码：head/tail 自由文本（开放词表），
    relation 锁定在 12 个 id、evidence_level 锁定 A-D，同时保证输出是合法 JSON。"""
    return {
        "type": "array",
        "maxItems": 6,
        "items": {
            "type": "object",
            "properties": {
                "head": {"type": "string"},
                "relation": {"type": "string", "enum": RELATIONS},
                "tail": {"type": "string"},
                "evidence_level": {"type": "string", "enum": ["A", "B", "C", "D"]},
            },
            "required": ["head", "relation", "tail", "evidence_level"],
            "additionalProperties": False,
        },
    }


def _make_sampling_params(SamplingParams, args):
    """兼容三种 vLLM 版本的结构化输出参数：structured_outputs(v0.11+) → guided_json(旧) → 无约束。"""
    base = dict(temperature=args.temperature, max_tokens=args.max_new_tokens)
    if not args.guided:
        return SamplingParams(**base)
    schema = build_guided_schema()
    try:  # vLLM >= 0.11
        from vllm.sampling_params import StructuredOutputsParams
        return SamplingParams(**base, structured_outputs=StructuredOutputsParams(json=schema))
    except Exception:
        pass
    try:  # 旧版 vLLM
        return SamplingParams(**base, guided_json=schema)
    except Exception:
        pass
    print("警告: 当前 vLLM 不支持结构化输出，回退到无约束解码")
    return SamplingParams(**base)


def merge_adapter(model, adapter, out_dir):
    """把 LoRA adapter 合并进 base 权重，返回合并后的模型目录（vLLM 直接加载）。
    合并结果缓存在 out_dir，已存在则跳过，避免每次评测重复合并。"""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import PeftModel
    if (Path(out_dir) / "config.json").exists():
        print("复用已合并模型:", out_dir)
        return out_dir
    print("合并 LoRA adapter:", adapter, "->", out_dir)
    tok = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
    mdl = AutoModelForCausalLM.from_pretrained(model, torch_dtype=torch.float16,
                                               trust_remote_code=True)
    mdl = PeftModel.from_pretrained(mdl, adapter)
    mdl = mdl.merge_and_unload()
    mdl.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    return out_dir


def run_vllm(tasks, model, args):
    from vllm import LLM, SamplingParams
    llm = LLM(model=model, dtype="float16" if args.fp16 else "auto",
              gpu_memory_utilization=args.gpu_mem, max_model_len=args.max_model_len,
              tensor_parallel_size=args.tp)
    sp = _make_sampling_params(SamplingParams, args)
    # 关键：用 chat 接口自动套模型的 chat template（instruct 模型必须）
    msgs = [[{"role": "user", "content": build_prompt(t, fewshot=args.fewshot)}] for t in tasks]
    t0 = time.time()
    outs = llm.chat(msgs, sp)
    print("推理完成: %d 条, 耗时 %.1f 分钟" % (len(tasks), (time.time() - t0) / 60))
    return [(o.outputs[0].text if o.outputs else "") for o in outs]


def run_hf(tasks, model, args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
    mdl = AutoModelForCausalLM.from_pretrained(
        model, torch_dtype=torch.float16 if args.fp16 else "auto",
        device_map="auto", trust_remote_code=True)
    mdl.eval()
    texts = []
    for t in tasks:
        p = build_prompt(t, fewshot=args.fewshot)
        if getattr(tok, "chat_template", None):
            texts.append(tok.apply_chat_template(
                [{"role": "user", "content": p}], tokenize=False, add_generation_prompt=True))
        else:
            texts.append(p)
    outs = []
    B = args.batch_size
    t0 = time.time()
    for i in range(0, len(texts), B):
        batch = texts[i:i + B]
        enc = tok(batch, return_tensors="pt", padding=True, truncation=True,
                  max_length=args.max_model_len - args.max_new_tokens).to(mdl.device)
        with torch.no_grad():
            gen = mdl.generate(**enc, max_new_tokens=args.max_new_tokens,
                               do_sample=args.temperature > 0,
                               temperature=args.temperature if args.temperature > 0 else None,
                               pad_token_id=tok.eos_token_id)
        for j in range(len(batch)):
            outs.append(tok.decode(gen[j][enc["input_ids"].shape[1]:], skip_special_tokens=True))
        done = min(i + B, len(texts))
        if (i // B) % 5 == 0:
            print("  %d/%d, 已用 %.1f 分钟" % (done, len(texts), (time.time() - t0) / 60))
    return outs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="HF 模型名或本地路径")
    ap.add_argument("--adapter", default=None,
                    help="LoRA adapter 目录（merge 后再推理，用于 SFT 对比）")
    ap.add_argument("--adapter-out", default=None,
                    help="合并权重输出目录，默认 ~/merged_<adapter名>")
    ap.add_argument("--backend", choices=["vllm", "hf"], default="vllm")
    ap.add_argument("--split", default="dev",
                    help="train/dev/test/test_core/all（默认 dev；all=三个评测集全跑）")
    ap.add_argument("--out", default=None, help="输出文件，默认 predictions_<split>.jsonl")
    ap.add_argument("--fp16", action="store_true")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    ap.add_argument("--max-model-len", type=int, default=8192)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--gpu-mem", type=float, default=0.9)
    ap.add_argument("--tp", type=int, default=1, help="vLLM 张量并行数")
    ap.add_argument("--no-guided", dest="guided", action="store_false",
                    help="关闭受约束解码（默认开启，用 JSON Schema enum 锁死闭集）")
    ap.add_argument("--no-fewshot", dest="fewshot", action="store_false",
                    help="prompt 不带 few-shot 示例（微调后的模型推荐关闭）")
    args = ap.parse_args()

    if args.adapter:                              # SFT 对比：先合并 LoRA
        out_dir = args.adapter_out or str(
            Path.home() / ("merged_" + Path(args.adapter).name))
        args.model = merge_adapter(args.model, args.adapter, out_dir)

    splits = ["dev", "test", "test_core"] if args.split == "all" else [args.split]
    for split in splits:
        tasks = load_tasks(split)
        out_path = args.out or str((_paths.EVAL / "preds_remote" / ("predictions_%s.jsonl" % split)))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        print("== split=%s, %d 条, 模型=%s (%s) ==" % (split, len(tasks), args.model, args.backend))
        if args.backend == "vllm":
            outs = run_vllm(tasks, args.model, args)
        else:
            outs = run_hf(tasks, args.model, args)
        n_t = 0
        n_raw = n_drop = 0
        with open(out_path, "w", encoding="utf-8") as f:
            for t, o in zip(tasks, outs):
                trip = parse_triples(o)
                n_raw += len(trip)
                for tr in trip:
                    tr["relation"] = snap_rel(tr["relation"])
                # v3 开放实体：只丢弃头/尾为空的行，不做词表吸附与词表外丢弃
                seen, clean = set(), []
                for tr in trip:
                    if not tr["head"] or not tr["tail"]:
                        n_drop += 1
                        continue
                    key = (tr["head"].lower(), tr["relation"], tr["tail"].lower())
                    if key not in seen:
                        seen.add(key)
                        clean.append(tr)
                n_t += len(clean)
                f.write(json.dumps({"task_id": t["task_id"], "pmid": t["pmid"],
                                    "triples": clean,
                                    "n_raw": len(trip),
                                    "raw": (o or "")[:600]}, ensure_ascii=False) + "\n")
        print("输出: %s (三元组 %d 条；原始解析 %d 条，丢弃 %d 条噪声)" % (out_path, n_t, n_raw, n_drop))


if __name__ == "__main__":
    main()
