import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""Wide-open triple extraction over dev+test (500+500), NOT restricted to the closed vocabulary.

Pipeline per user instruction:
  1. relation-trigger driven sentence scan (24-relation trigger lexicons)
  2. open head NPs (intervention-ish) + open tail NPs (outcome-ish), no alias constraint
  3. emit candidate triples with in_vocab flags for the manual review pass
Output:
  tmp/benchmark/open_triples_devtest.jsonl   one candidate per line
  tmp/benchmark/open_candidates_summary.txt  frequency table for review
"""
import json
import re
import collections
from pathlib import Path

HERE = _paths.DATA
BENCH = _paths.BM

# ------------------------------------------------ relation trigger lexicons --
TRIGGERS = {
    "improves": [r"improv\w+", r"beneficial\w*", r"\befficac\w+", r"\beffective\b",
                 r"therapeutic effect", r"better (sleep|recovery|mood|outcome)"],
    "reduces": [r"reduc\w+", r"attenuat\w+", r"mitigat\w+", r"decreas\w+"],
    "lowers": [r"lower\w*", r"decreas\w+"],
    "alleviates": [r"alleviat\w+", r"reliev\w+", r"\beas\w+ (pain|anxiety|stress|symptom)",
                   r"sooth\w+"],
    "enhances": [r"enhanc\w+", r"increas\w+", r"strengthen\w+", r"boost\w*",
                 r"restor\w+", r"promot\w+"],
    "accelerates": [r"accelerat\w+", r"shorten\w+", r"\bfaster\b", r"\bquicker\b",
                    r"speed\w* (up|recovery)"],
    "triggers": [r"evok\w+", r"elicits?\b", r"trigger\w+", r"induc\w+"],
    "impairs": [r"impair\w+", r"negativ\w+ (affect|impact|influence)", r"disrupt\w+",
                r"\bharm\w*", r"detrimental"],
    "evidence_supports": [r"\bevidence\b", r"suggest\w+", r"demonstrat\w+",
                          r"support\w+", r"associat\w+ with"],
}
TRIG_RES = {rel: re.compile("|".join(pats), re.I) for rel, pats in TRIGGERS.items()}

# ------------------------------------------------------ open head patterns --
HEAD_PATTERNS = [
    r"(?:virtual|augmented) reality [a-z ]{0,30}",
    r"\bVR [a-z ]{0,25}",
    r"[a-z]+(?: [a-z]+){0,2} (?:therapy|therapies|training|exposure|intervention|program)",
    r"[a-z]+(?: [a-z]+)? (?:music|sounds?|noise|melody)",
    r"[a-z]+(?: [a-z]+)? (?:oil|oils|extract|aroma|scent|fragrance)",
    r"[a-z]+(?: [a-z]+)? (?:bath|soak|spring|spa|sauna)",
    r"[a-z]+(?: [a-z]+)? (?:tea|infusion|supplement)",
    r"[a-z]+(?: [a-z]+)? (?:light|lighting)",
    r"[a-z]+(?: [a-z]+)? (?:garden|greenery|plants?|forest|greenspace|green space)",
    r"[a-z]+(?: [a-z]+)? (?:walk|view|window|landscape)",
    r"[a-z]+(?: [a-z]+)? (?:massage|yoga|meditation|breathing|tai chi|qigong)",
    r"\b(?:mindfulness|meditation|aromatherapy|acupressure|acupuncture|reflexology|"
    r"hydrotherapy|balneotherapy|horticultural\w*|biophilic\w*|mHealth|mHealth app)\b",
    r"(?:smartphone|mobile) (?:app|application|health|intervention)s?",
    r"(?:art|pet|animal[- ]assisted|nature|garden|forest) therapy",
    r"\bdigital (?:therapeutic\w*|intervention|tool)s?",
]
HEAD_RES = [re.compile(p, re.I) for p in HEAD_PATTERNS]

# ------------------------------------------------------ open tail patterns --
TAIL_STEMS = [
    "anxiet", "stress", "depress", "mood", "sleep", "insomnia", "pain", "fatigue",
    "well.?being", "quality of life", "QOL", "cortisol", "blood pressure",
    "heart rate", "HRV", "attention", "memory", "cogniti", "executive",
    "immune", "NK cell", "natural killer", "inflammat", "inflammatory", "sIgA",
    "nausea", "appetite", "craving", "withdrawal", "addiction", "skin",
    "arousal", "relaxation", "vigor", "hope", "creativity", "salivary",
    "blood glucose", "pulse", "respiratory", "menstrual", "dysmenorrhea",
    "agitation", "dementia", "boredom", "loneliness", "mood state",
    "negative emotion", "positive emotion", "emotion", "autonomic",
    "sympathetic", "parasympathetic", "vagal",
]
TAIL_RES = re.compile("|".join(s + r"\w*" for s in TAIL_STEMS), re.I)

STOP_HEAD = re.compile(
    r"(control|placebo|sham|usual care|standard|no |non|patient|participant|"
    r"subject|group|treatment as usual|waiting)", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

NEG = _schema.legacy_alias()["negative_context"]   # v3 起不再维护句级负向守卫词表
NEG_RES = re.compile("|".join(NEG), re.I) if NEG else None

alias = _schema.legacy_alias()
VOCAB_RES = [re.compile(p, re.I) for v in
             list(alias["head_aliases"].values()) + list(alias["tail_aliases"].values())
             for p in v]


def sent_split(text):
    return [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]


def main():
    ev = []
    for _s in ("dev", "test"):
        ev += [json.loads(l) for l in open(_paths.sp(_s), encoding="utf-8")]
    out = open(_paths.AUX / "open_triples_devtest.jsonl", "w", encoding="utf-8")
    n_cand = 0
    for d in ev:
        text = d["input"]["title"] + "\n" + d["input"]["abstract"]
        for si, sent in enumerate([d["input"]["title"]] + sent_split(d["input"]["abstract"])):
            if NEG_RES and NEG_RES.search(sent):
                continue
            for rel, res in TRIG_RES.items():
                m = res.search(sent)
                if not m:
                    continue
                heads = []
                for hp in HEAD_RES:
                    heads.extend(x.group(0).strip() for x in hp.finditer(sent))
                tails = [x.group(0).strip() for x in TAIL_RES.finditer(sent)]
                # 优先 trigger 之前的 head / 之后的 tail
                heads = [h for h in heads if not STOP_HEAD.search(h)
                         and h.lower() not in ("this", "that")]
                heads = [re.sub(r"^(the|a|an) ", "", h, flags=re.I).strip() for h in heads]
                if not heads or not tails:
                    continue
                # 距离排序：head 取 trigger 前最近，tail 取 trigger 后最近
                trig_pos = m.start()
                head = min(heads, key=lambda h: abs(sent.lower().find(h.lower()) - trig_pos)) \
                    if heads else None
                tail_after = [t for t in tails
                              if sent.lower().find(t.lower()) >= trig_pos]
                tail = (tail_after or tails)[0]
                head_in = any(v.search(sent) for v in VOCAB_RES)  # 句内是否已有闭集命中
                out.write(json.dumps({
                    "task_id": d["task_id"], "split": d["split"], "sent_i": si,
                    "relation": rel,
                    "head": head, "tail": tail,
                    "sentence": sent.strip(),
                    "head_rel_pos": "before" if sent.lower().find(head.lower()) < trig_pos else "after",
                    "in_vocab_ctx": head_in,
                }, ensure_ascii=False) + "\n")
                n_cand += 1
    out.close()

    # 汇总：未覆盖 (head_lower, rel, tail_lower) 频率
    cnt = collections.Counter()
    ex = {}
    for line in open(_paths.AUX / "open_triples_devtest.jsonl", encoding="utf-8"):
        r = json.loads(line)
        key = (r["head"].lower(), r["relation"], r["tail"].lower())
        cnt[key] += 1
        ex.setdefault(key, r)
    with open(_paths.AUX / "open_candidates_summary.txt", "w", encoding="utf-8") as f:
        f.write(f"total candidates: {n_cand}, unique: {len(cnt)}\n\n")
        for key, n in cnt.most_common():
            e = ex[key]
            f.write(f"[{n:3d}] {key[0]} --{key[1]}--> {key[1] and key[2]}\n"
                    f"      {key[0]} --{key[1]}--> {key[2]}\n"
                    f"      ex: {e['sentence'][:160]}\n\n")
    print(f"candidates: {n_cand}, unique (head,rel,tail): {len(cnt)}")
    print("summary -> tmp/benchmark/open_candidates_summary.txt")


if __name__ == "__main__":
    main()
