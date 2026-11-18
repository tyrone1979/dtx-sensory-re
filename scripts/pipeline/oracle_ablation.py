import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""oracle_ablation.py — 把「语义规则的净贡献」从「词典漂移」里分离出来。

背景：oracle_sim.py 的 L1 基线只跑朴素规则（不含 S1–S5 语义守卫、不含 G4 粒度让位），
但 benchmark 里的 gold 是上一版词典构建的。直接对比会把两种误差混在一起：
  (a) 语义规则缺失 —— 我们想量的
  (b) 别名表/负向守卫条数变化 —— 我们不想要的
做法：对 dev/test 每篇，用**当前**词典 + **全规则**（build_dataset.annotate）就地重算 gold，
再让 L1（oracle_sim.annotate）在同一份 gold 上打分。差值即语义规则的净贡献。

输出 dataset/results/oracle_ablation.json
"""
import json
import sys
from pathlib import Path

HERE = _paths.DATA          # 唯一数据目录 dataset/
ROOT = _paths.ROOT          # 仓库根
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(_paths.SCRIPTS / "pubmed"))

import evaluate_extraction as E          # noqa: E402
import oracle_sim as L1                  # noqa: E402
import build_dataset as B                # noqa: E402

BENCH = _paths.BM
REL_EN = _schema.rel_zh2en()         # {中文关系名: 英文 id}


def setup_protocol():
    """复现 build_dataset.main() 里 annotate() 的全部入参。"""
    kg = json.loads(B.KG_PATH.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in kg["nodes"]}
    edges = kg["edges"]
    route = B.build_routing(nodes, edges)
    alias = json.loads(B.ALIAS_PATH.read_text(encoding="utf-8"))
    node_name = {**nodes, **{k: {"name": v, "type": "stimulus"}
                             for k, v in alias.get("head_names", {}).items()}}  # v2.0: 合并感官类目名
    MOD_PREFIX = {"vis_": "视觉", "aud_": "听觉", "olf_": "嗅觉", "tas_": "味觉",
                  "tac_": "触觉", "per_": "知觉", "env_": "多感官环境"}
    route2 = dict(route)
    for hid in alias["head_aliases"]:
        for p, m in MOD_PREFIX.items():
            if hid.startswith(p):
                route2[hid] = [m]
                break
    alias = json.loads(B.ALIAS_PATH.read_text(encoding="utf-8"))
    head_res = {k: [__import__("re").compile(p, __import__("re").I) for p in v]
                for k, v in alias["head_aliases"].items()}
    tail_res = {k: [__import__("re").compile(p, __import__("re").I) for p in v]
                for k, v in alias["tail_aliases"].items()}
    global_trigger = __import__("re").compile(alias["trigger_words"], __import__("re").I)
    neg_res = __import__("re").compile("|".join(alias["negative_context"]), __import__("re").I) \
        if alias.get("negative_context") else None
    from collections import Counter, defaultdict
    benefit_relation = {}
    cnt = defaultdict(Counter)
    for e in edges:
        if nodes.get(e["target"], {}).get("type") == "benefit":
            cnt[e["target"]][e["relation"]] += 1
    for b, c in cnt.items():
        benefit_relation[b] = c.most_common(1)[0][0]
    return dict(head_res=head_res, tail_res=tail_res, node_name=node_name,
                benefit_relation=benefit_relation, global_trigger=global_trigger,
                neg_res=neg_res, route=route2, child_of=None)


def main():
    P = setup_protocol()
    inputs, gold_file = {}, {}
    for _s in _paths.SPLITS:                      # 自包含 split：题面与答案同一行
        for r in E.load_jsonl(_paths.sp(_s)):
            inputs[str(r["pmid"])] = r["input"]
            gold_file[r["task_id"]] = r
    alias_res = E.build_matchers()

    rows = []
    for split in ["dev", "test"]:
        ids = [tid for tid, g in gold_file.items() if g["split"] == split]
        # ① 当前词典+全规则 重算 gold
        gold_proto = {}
        for tid in ids:
            g = gold_file[tid]
            inp = inputs.get(str(g["pmid"]), {})
            paper = {"title": inp.get("title", ""), "abstract": inp.get("abstract", ""),
                     "pubtypes": inp.get("pubtypes", [])}
            trip = B.annotate(paper, P["head_res"], P["tail_res"], P["node_name"],
                              P["benefit_relation"], None, P["global_trigger"],
                              neg_res=P["neg_res"], route=P["route"], child_of=P["child_of"])
            # benchmark 的 dev/test gold 已英文化，重算 gold 需对齐到同一套关系名
            for t in trip:
                t["relation"] = REL_EN.get(t["relation"], t["relation"])
            gold_proto[tid] = {"task_id": tid, "pmid": g["pmid"], "split": split,
                               "gold_type": "protocol_regen", "gold": trip}

        # ② L1 预测
        preds = [{"task_id": tid, "pmid": gold_file[tid]["pmid"],
                  "triples": L1.annotate({"title": inputs.get(str(gold_file[tid]["pmid"]), {}).get("title", ""),
                                          "abstract": inputs.get(str(gold_file[tid]["pmid"]), {}).get("abstract", ""),
                                          "pubtypes": inputs.get(str(gold_file[tid]["pmid"]), {}).get("pubtypes", [])})}
                 for tid in ids]

        m_old = L1.evaluate(preds, ids, gold_file, alias_res, {}, False)
        m_new = L1.evaluate(preds, ids, gold_proto, alias_res, {}, False)
        n_old = sum(len(gold_file[t]["gold"]) for t in ids)
        n_new = sum(len(gold_proto[t]["gold"]) for t in ids)
        n_pred = sum(len(p["triples"]) for p in preds)

        rows.append({
            "split": split, "tasks": len(ids),
            "gold_triples_file": n_old, "gold_triples_protocol": n_new, "L1_pred_triples": n_pred,
            "L1_vs_old_gold": {"p": round(m_old["s"][0], 4), "r": round(m_old["s"][1], 4), "f1": round(m_old["s"][2], 4)},
            "L1_vs_protocol_gold": {"p": round(m_new["s"][0], 4), "r": round(m_new["s"][1], 4), "f1": round(m_new["s"][2], 4)},
            "semantic_rule_gain_f1": round(m_new["s"][2] - m_old["s"][2], 4),
        })
        print("%-5s tasks=%d | gold(file)=%d gold(protocol)=%d L1pred=%d" % (
            split, len(ids), n_old, n_new, n_pred))
        print("      L1 vs 旧gold   P=%.3f R=%.3f F1=%.3f" % (m_old["s"][0], m_old["s"][1], m_old["s"][2]))
        print("      L1 vs 协议gold P=%.3f R=%.3f F1=%.3f   (语义规则净增益 %+.3f)" % (
            m_new["s"][0], m_new["s"][1], m_new["s"][2], m_new["s"][2] - m_old["s"][2]))

    dest = _paths.EVAL / "results"
    dest.mkdir(exist_ok=True)
    (dest / "oracle_ablation.json").write_text(
        json.dumps({"note": "L1_vs_protocol_gold 是干净的诊断量：同一份词典，只差语义规则", "rows": rows},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n写出:", dest / "oracle_ablation.json")


if __name__ == "__main__":
    main()
