import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""
eval_report.py — 批量评测并输出机器可读的结果文件（论文表格直接取用）

对 dev / test / test_core 三个集合，分别在「全量 gold」与「strong-gold 去噪」两种口径下
计算 strict / relaxed 的 P/R/F1 与证据等级准确率，写入 results/baseline_<name>.json。

用法：
  python scripts/pipeline/eval_report.py --pred-dir tmp/eval/preds_remote --name qwen25_7b
"""
import argparse
import json
import sys
from pathlib import Path

HERE = _paths.DATA
sys.path.insert(0, str(HERE))
import evaluate_extraction as E  # noqa: E402


def eval_split(pred_path, split, strong_only):
    gold = {}
    for _s in _paths.SPLITS:
        for g in E.load_jsonl(_paths.sp(_s)):
            gold[g["task_id"]] = g
    gold.update({g["task_id"]: g for g in E.load_jsonl(_paths.SOURCE / "gold_core_human.jsonl")})
    strength = json.loads((_paths.AUX / "gold_strength.json").read_text(encoding="utf-8"))
    alias_res = E.build_matchers()
    preds = E.load_jsonl(pred_path)

    tp_s = tp_r = fp = fn = lvl_ok = lvl_n = 0
    npred = 0
    for p in preds:
        g = gold.get(p["task_id"])
        if not g or g["split"] != split:
            continue
        gt = _schema.expand_gold(g["gold"])   # gold 只有 id，补回规范写法
        if strong_only:
            flags = strength.get(p["task_id"], [])
            gt = [t for i, t in enumerate(gt) if i >= len(flags) or flags[i] == "strong"]
            if not gt:
                continue
        matched = set()
        for tr in p.get("triples", []):
            npred += 1
            hit = None
            for i, t in enumerate(gt):
                if i in matched:
                    continue
                if (E.entity_match(tr.get("head", ""), t["head"], t.get("head_id", ""), alias_res)
                        and E.entity_match(tr.get("tail", ""), t["tail"], t.get("tail_id", ""), alias_res)
                        and E.norm(tr.get("relation", "")) == E.norm(t["relation"])):
                    hit = i
                    break
            if hit is not None:
                matched.add(hit)
                tp_s += 1
                if tr.get("evidence_level") and gt[hit].get("evidence_level"):
                    lvl_n += 1
                    if tr["evidence_level"] == gt[hit]["evidence_level"]:
                        lvl_ok += 1
                continue
            for i, t in enumerate(gt):
                if i in matched:
                    continue
                if (E.entity_match(tr.get("head", ""), t["head"], t.get("head_id", ""), alias_res)
                        and E.entity_match(tr.get("tail", ""), t["tail"], t.get("tail_id", ""), alias_res)):
                    matched.add(i)
                    tp_r += 1
                    break
            else:
                fp += 1
        fn += len(gt) - len(matched)

    def prf(tp):
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        return {"precision": round(pr, 4), "recall": round(rc, 4), "f1": round(f1, 4)}

    return {
        "split": split,
        "gold_mode": "strong" if strong_only else "all",
        "gold_triples": tp_s + tp_r + fn,
        "pred_triples": npred,
        "strict": prf(tp_s),
        "relaxed": prf(tp_s + tp_r),
        "evidence_level_acc": round(lvl_ok / lvl_n, 4) if lvl_n else None,
        "evidence_level_n": lvl_n,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred-dir", default=str(_paths.EVAL / "preds_remote"))
    ap.add_argument("--name", default="qwen25_7b")
    ap.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    args = ap.parse_args()

    rows = []
    for split in ["dev", "test", "test_core"]:
        f = Path(args.pred_dir) / ("predictions_%s.jsonl" % split)
        if not f.exists():
            continue
        for strong in (False, True):
            rows.append(eval_split(f, split, strong))

    out = {"model": args.model, "decoding": "closed-set few-shot + structured output (enum)",
           "results": rows}
    dest = _paths.EVAL / "results"
    dest.mkdir(exist_ok=True)
    p = dest / ("baseline_%s.json" % args.name)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("%-10s %-7s %-28s %-28s %s" % ("split", "gold", "strict P/R/F1", "relaxed P/R/F1", "lvl acc"))
    for r in rows:
        s, l = r["strict"], r["relaxed"]
        print("%-10s %-7s %.3f / %.3f / %.3f          %.3f / %.3f / %.3f          %s" % (
            r["split"], r["gold_mode"], s["precision"], s["recall"], s["f1"],
            l["precision"], l["recall"], l["f1"],
            "%.3f" % r["evidence_level_acc"] if r["evidence_level_acc"] is not None else "-"))
    print("\n写出:", p)


if __name__ == "__main__":
    main()
