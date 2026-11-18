import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""Validate human gold against the annotation protocol (C1-C5 hard constraints).

Checks:
  C1 head/tail must be in the closed 85-node vocabulary
  C2 relation must be one of the 24 enumeration
  C3 (head_type, relation, tail_type) must match the relation type signature
  C4 every triple carries a non-empty evidence field quoting the abstract
  C5 no duplicate (head, relation, tail) within one document
  (v1.1: category field deprecated — no longer checked or required)
⚠️ v2.0 闭集校验器：C1/C3 依赖 92 节点闭集词表，只适用于 legacy 的 gold_core_human.jsonl
   与旧远程监督黄金。现行 v3 开放实体数据请用 scripts/benchmark/_sem_verify.py（test）与
   _dev_verify.py（dev）校验。

Usage:
  python scripts/pipeline/validate_gold.py ../tmp/source/gold_core_human.jsonl
  exit 0 = pass, exit 1 = violations found (CI-friendly)
"""
import json
import sys
from pathlib import Path

ROOT = _paths.ROOT
KG = json.load(open(ROOT / "output/data/knowledge_graph.json", encoding="utf-8"))
NODES = {n["id"]: n for n in KG["nodes"]}
NAME2ID = {}
for n in KG["nodes"]:
    NAME2ID[n["id"]] = n["id"]  # id itself counts
    NAME2ID[n.get("name", "")] = n["id"]

REL_EN = _schema.rel_zh2en()         # {中文关系名: 英文 id}
ZH2EN = {zh: en for zh, en in REL_EN.items() if not zh.startswith("_")}

REL_SIG = {  # protocol signature: relation(en) -> allowed (head_type, tail_type) pairs
    "primarily_via": {("modality", "channel")},
    "acts_on": {("stimulus", "channel")},
    "stimulates": {("stimulus", "channel")},
    "includes": {("modality", "stimulus")},
    "adopts": {("design", "stimulus"), ("design", "modality")},
    "combined_with": {("modality", "modality")},
    "synergizes_with": {("modality", "modality"), ("modality", "channel"), ("design", "design")},
    "improves": {("modality", "benefit"), ("stimulus", "benefit")},
    "enhances": {("modality", "benefit"), ("stimulus", "benefit")},
    "promotes": {("modality", "benefit")},
    "reduces": {("modality", "benefit"), ("stimulus", "benefit")},
    "lowers": {("modality", "benefit"), ("stimulus", "benefit")},
    "alleviates": {("modality", "benefit"), ("stimulus", "benefit")},
    "accelerates": {("modality", "benefit"), ("stimulus", "benefit")},
    "strengthens": {("modality", "benefit")},
    "activates": {("stimulus", "benefit")},
    "triggers": {("stimulus", "benefit"), ("modality", "benefit")},
    "adjunct_improves": {("modality", "benefit"), ("stimulus", "benefit")},
    "multidimensional_assessment": {("modality", "benefit")},
    "mechanism": {("modality", "benefit")},
    "affects": {("modality", "benefit")},
    "impairs": {("stimulus", "benefit")},
    "evidence_supports": {("design", "benefit")},
    "evidence": {("modality", "benefit")},
}
# distant-supervision legacy profile: evidence_supports doubles as the fallback
# efficacy relation for modality/stimulus heads.  Human gold must NOT use it.
REL_SIG_DS = {k: (v | {("modality", "benefit"), ("stimulus", "benefit")})
              if k == "evidence_supports" else v for k, v in REL_SIG.items()}
CHANNEL_IDS = {n["id"] for n in KG["nodes"] if n["type"] == "channel"}  # reserved (v1.1: category deprecated)


def resolve(entity):
    """Accept node id or English node name; return node dict or None."""
    nid = NAME2ID.get(entity)
    return NODES.get(nid) if nid else None


def validate_file(path, ds_profile=False):
    rel_sig = REL_SIG_DS if ds_profile else REL_SIG
    violations = []
    n_triples = 0
    for line_no, line in enumerate(open(path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        doc = json.loads(line)
        doc_id = doc.get("id", doc.get("task_id", f"line{line_no}"))
        seen = set()
        for i, t in enumerate(doc.get("triples", []) or doc.get("gold", [])):
            n_triples += 1
            where = f"{doc_id}#{i}"
            # resolve entities by id first (language-agnostic), fall back to name
            hn = NODES.get(t.get("head_id", "")) or resolve(t.get("head", ""))
            tn = NODES.get(t.get("tail_id", "")) or resolve(t.get("tail", ""))
            r_raw = t.get("relation", "")
            r = ZH2EN.get(r_raw, r_raw)
            # C1 closed vocabulary (id or name must resolve; name must match id)
            if hn is None:
                violations.append((where, "C1", f"head not in vocabulary: {t.get('head')!r}/{t.get('head_id')!r}"))
            elif hn["id"] != t.get("head_id"):
                violations.append((where, "C1", f"head_id mismatch: {t.get('head_id')!r} resolves to {hn['id']}"))
            if tn is None:
                violations.append((where, "C1", f"tail not in vocabulary: {t.get('tail')!r}/{t.get('tail_id')!r}"))
            elif tn["id"] != t.get("tail_id"):
                violations.append((where, "C1", f"tail_id mismatch: {t.get('tail_id')!r} resolves to {tn['id']}"))
            # C2 relation enumeration
            if r not in rel_sig:
                violations.append((where, "C2", f"relation not in enumeration: {r!r}"))
                continue
            # C3 type signature
            if hn and tn:
                sig = (hn["type"], tn["type"])
                if sig not in rel_sig[r]:
                    violations.append((where, "C3",
                        f"{hn['type']} -{r}-> {tn['type']} not allowed; "
                        f"allowed: {sorted(rel_sig[r])}"))
                # modality never as concrete-content head (Granularity G3 guard)
                if hn["type"] == "modality" and tn["type"] == "stimulus" \
                        and tn["id"].startswith("stim_vr"):
                    violations.append((where, "C3/G3", "modality head with VR scene tail"))
            # C4 evidence sentence present (remote-supervision gold may omit; human gold must not)
            if not (t.get("evidence") or t.get("evidence_sentence") or "").strip() \
                    and doc.get("gold_type") == "human_curated":
                violations.append((where, "C4", "empty evidence"))
            # C5 duplicates
            key = (hn["id"] if hn else t.get("head"), r, tn["id"] if tn else t.get("tail"))
            if key in seen:
                violations.append((where, "C5", f"duplicate triple {key}"))
            seen.add(key)
    return n_triples, violations


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=str(_paths.SOURCE / "gold_core_human.jsonl"))
    ap.add_argument("--ds", action="store_true",
                    help="legacy distant-supervision profile (evidence_supports fallback allowed)")
    args = ap.parse_args()
    path = Path(args.path)
    n, violations = validate_file(path, ds_profile=args.ds)
    profile = "legacy_ds" if args.ds else "strict(human)"
    print(f"validated {path} [{profile}] : {n} triples, {len(violations)} violations")
    for where, code, msg in violations[:50]:
        print(f"  [{code}] {where}: {msg}")
    if len(violations) > 50:
        print(f"  ... and {len(violations) - 50} more")
    sys.exit(1 if violations else 0)


if __name__ == "__main__":
    main()
