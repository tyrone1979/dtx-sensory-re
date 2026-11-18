import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""
oracle_sim.py — 决定性诊断：用「与 gold 标注完全相同的确定性规则」当作抽取系统跑一遍 benchmark。

若 oracle 在 strong-gold 上接近满分，说明当前 LLM 的低 F1 不是模型能力问题，
而是「模型没学会标注协议 + weak gold 不可从摘要推断 + 评测匹配过严」三件事。
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = _paths.DATA
BENCH = _paths.BM
ROOT = _paths.ROOT
sys.path.insert(0, str(HERE))
import evaluate_extraction as E  # noqa: E402

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
ANIMAL_RE = re.compile(
    r"\b(rats?|mice|mouse|murine|rodents?|porcine|rabbits?|zebrafish|hamsters?|guinea pigs?)\b"
    r"|\b(animal|preclinical)\s+(model|study|experiment)s?\b"
    r"|\bin vitro\b|\bcell (culture|line)s?\b|\bex vivo\b", re.I)
KG = json.loads((ROOT / "output/data/knowledge_graph.json").read_text(encoding="utf-8"))
nodes = {n["id"]: n for n in KG["nodes"]}
NODE_EN = _schema.node_en()          # {id: 英文名}
REL_EN = _schema.rel_zh2en()         # {中文关系名: 英文 id}

benefit_relation = {}
cnt = defaultdict(Counter)
for e in KG["edges"]:
    if nodes.get(e["target"], {}).get("type") == "benefit":
        cnt[e["target"]][e["relation"]] += 1
for b, c in cnt.items():
    benefit_relation[b] = REL_EN[c.most_common(1)[0][0]]

alias = _schema.legacy_alias()       # 实体词表（含 aliases）+ 空 negative_context
head_res = {k: [re.compile(p, re.I) for p in v] for k, v in alias["head_aliases"].items()}
tail_res = {k: [re.compile(p, re.I) for p in v] for k, v in alias["tail_aliases"].items()}
global_trigger = re.compile(alias["trigger_words"], re.I)
# L1 朴素规则基线：只保留词典级通用负向守卫；语义规则 S1–S5 属于人工协议，
# 规则系统无法执行，故显式剔除（这是 L1 与 gold 的差距来源，见协议 §8.4）。
SEMANTIC_GUARDS = {
    r'forced[- ]mindfulness',
    r'focus(ing|ed)? attention on',
    r'\b(anxiolytic|anti-?viral|mucolytic|sedative|antioxidant)\s+propert',
    r'(used|employed) (throughout|for) (human )?history',
    r'has been used (to|for) (prevent|treat)',
}
_neg = [p for p in alias.get("negative_context", []) if p not in SEMANTIC_GUARDS]
NEG_RES = re.compile("|".join(_neg), re.I) if _neg else None
# 配对级 Granularity：stimulus 子节点 → 父 modality（modality--包含-->stimulus）
CHILD_OF = {e["target"]: e["source"] for e in KG["edges"]
            if e["relation"] == "包含" and nodes.get(e["source"], {}).get("type") == "modality"
            and nodes.get(e["target"], {}).get("type") == "stimulus"}


def suggest_level(pubtypes):
    pt = [p.lower() for p in pubtypes]
    if any("meta-analysis" in p or "systematic review" in p for p in pt):
        return "A"
    if any("randomized controlled trial" in p or "clinical trial" in p or "comparative study" in p for p in pt):
        return "B"
    if any("review" in p for p in pt):
        return "D"
    return "C"


def annotate(paper):
    text = re.sub(r"\s+", " ", (paper.get("title", "") + ". " + paper.get("abstract", "")))
    if ANIMAL_RE.search(text):
        return []  # 动物/体外/临床前：整篇不产三元组
    sents = SENT_SPLIT.split(text) if text else []
    sent_hits = []
    for sid, sent in enumerate(sents):
        if not global_trigger.search(sent):
            continue
        if NEG_RES is not None and NEG_RES.search(sent):
            continue
        heads = {h for h, rxs in head_res.items() if any(rx.search(sent) for rx in rxs)}
        tails = {t for t, rxs in tail_res.items() if any(rx.search(sent) for rx in rxs)}
        # 注：L1 不执行 S1 列举句守卫，也不执行配对级粒度让位（协议语义规则）
        if heads and tails:
            sent_hits.append((sid, heads, tails))
    found = {}
    for sid, heads, tails in sent_hits:
        for h in heads:
            for t in tails:
                if h != t and (h, t) not in found:
                    found[(h, t)] = sid
    lvl = suggest_level(paper.get("pubtypes", []))
    return [{"head": NODE_EN[h], "head_id": h, "relation": benefit_relation.get(t, "improves"),
             "tail": NODE_EN[t], "tail_id": t, "evidence_level": lvl}
            for (h, t) in found]


def main():
    lit = {}
    for r in E.load_jsonl(_paths.SOURCE / "literature.jsonl"):
        lit[str(r["pmid"])] = r
    strength = json.loads((_paths.AUX / "gold_strength.json").read_text(encoding="utf-8"))
    gold = {}
    for _s in _paths.SPLITS:
        for g in E.load_jsonl(_paths.sp(_s)):
            gold[g["task_id"]] = g
    core = E.load_jsonl(_paths.SOURCE / "gold_core_human.jsonl")
    gold.update({g["task_id"]: g for g in core})

    alias_res = E.build_matchers()
    rows = []
    for split in ["dev", "test", "test_core"]:
        ids = [tid for tid, g in gold.items() if g["split"] == split] if split != "test_core" \
            else [g["task_id"] for g in core]
        preds = []
        for tid in ids:
            g = gold[tid]
            paper = lit.get(str(g["pmid"]), {})
            preds.append({"task_id": tid, "pmid": g["pmid"], "triples": annotate(paper)})
        tmp = _paths.EVAL / "preds_remote" / ("oracle_%s.jsonl" % split)
        with open(tmp, "w", encoding="utf-8") as f:
            for p in preds:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        for strong in (False, True):
            m = evaluate(preds, ids, gold, alias_res, strength, strong)
            rows.append({
                "split": split, "gold_mode": "strong" if strong else "all",
                "strict": {"precision": round(m["s"][0], 4), "recall": round(m["s"][1], 4),
                           "f1": round(m["s"][2], 4)},
                "relaxed": {"precision": round(m["r"][0], 4), "recall": round(m["r"][1], 4),
                            "f1": round(m["r"][2], 4)},
            })
            print("%-10s %-7s strict F1=%.3f  relaxed F1=%.3f  (P=%.3f R=%.3f / P=%.3f R=%.3f)" % (
                split, "strong" if strong else "all", m["s"][2], m["r"][2],
                m["s"][0], m["s"][1], m["r"][0], m["r"][1]))

    out = {
        "system": "rule-oracle（与 gold 远程监督标注完全相同的确定性规则，衡量任务上界与协议可复现性）",
        "note": "dev/test 的 gold 由同一规则生成，故 all-gold F1=1.0 属预期；"
                "test_core 为人工 gold，含「包含/协同」等图谱结构关系，摘要不可推断，"
                "oracle 分数即「不依赖人工标注时该集合的可推断上界」。",
        "results": rows,
    }
    dest = _paths.EVAL / "results"
    dest.mkdir(exist_ok=True)
    (dest / "oracle_rule_baseline.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n写出:", dest / "oracle_rule_baseline.json")


def evaluate(preds, ids, gold, alias_res, strength, strong_only):
    tp_s = tp_r = fp = fn = 0
    for p in preds:
        g = gold[p["task_id"]]
        gt = _schema.expand_gold(g["gold"])   # gold 只有 id，补回规范写法
        if strong_only:
            flags = strength.get(p["task_id"], [])
            gt = [t for i, t in enumerate(gt) if i >= len(flags) or flags[i] == "strong"]
            if not gt:
                continue
        matched = set()
        for tr in p["triples"]:
            hit = None
            for i, t in enumerate(gt):
                if i in matched:
                    continue
                if (E.entity_match(tr["head"], t["head"], t.get("head_id", ""), alias_res)
                        and E.entity_match(tr["tail"], t["tail"], t.get("tail_id", ""), alias_res)
                        and E.norm_rel(tr["relation"]) == E.norm_rel(t["relation"])):
                    hit = i
                    break
            if hit is not None:
                matched.add(hit)
                tp_s += 1
                continue
            for i, t in enumerate(gt):
                if i in matched:
                    continue
                if (E.entity_match(tr["head"], t["head"], t.get("head_id", ""), alias_res)
                        and E.entity_match(tr["tail"], t["tail"], t.get("tail_id", ""), alias_res)):
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
        return pr, rc, f1

    return {"s": prf(tp_s), "r": prf(tp_s + tp_r)}


if __name__ == "__main__":
    main()
