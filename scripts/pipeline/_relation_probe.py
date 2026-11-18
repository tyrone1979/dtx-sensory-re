# -*- coding: utf-8 -*-
"""_relation_probe.py — 缺失关系的定点排查。

在语料里检索"含指定线索短语 + 句中至少 2 个实体"的句子，打印出来供人工挑选。
用于规则抽不到、但语义确实存在的稀有/元关系（multidimensional_assessment /
evidence_supports / primarily_via）。

用法
----
  python scripts/pipeline/_relation_probe.py --rel multidimensional_assessment
  python scripts/pipeline/_relation_probe.py --rel evidence_supports --limit 20
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402
import _schema  # noqa: E402
import build_train_distant as B  # noqa: E402

CUES = {
    'multidimensional_assessment': [r'multi-?\s?dimensional assessment',
                                    r'multi-?\s?dimensional evaluation'],
    'primarily_via': [r'primarily (?:via|through)', r'mainly (?:via|through)',
                      r'mediated primarily (?:via|through|by)',
                      r'primarily mediated (?:via|through|by)'],
    'evidence_supports': [r'effectively (?:improv|reduc|enhanc|increas|decreas)\w*',
                          r'more effective than', r'showed (?:large|moderate) effects',
                          r'statistically significant (?:improvement|reduction|increase)',
                          r'large effects? (?:in|on)'],
}
CORPUS = ['entity_retrieval.jsonl', 'entity_retrieval_cue.jsonl',
          'entity_retrieval_missing.jsonl', 'entity_retrieval_deep.jsonl',
          'entity_retrieval_wide.jsonl', 'entity_retrieval_deep2.jsonl',
          'entity_retrieval_phrase.jsonl', 'entity_retrieval_rescue.jsonl']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rel', required=True, choices=sorted(CUES))
    ap.add_argument('--limit', type=int, default=25)
    args = ap.parse_args()

    type_of, ent_cues = {}, []
    for e in _schema.entities():
        type_of[e['id']] = e['type']
        w = tuple(B.toks(e['text']))
        if w:
            ent_cues.append((w, (e['id'], e['type'])))
    ent_idx = B.first_index(ent_cues)
    ent_maxlen = max(len(w) for w, _ in ent_cues)

    rx = re.compile('|'.join(CUES[args.rel]), re.I)
    dev_test = set()
    for split in ('dev', 'test'):
        for line in open(_paths.sp(split), encoding='utf-8'):
            dev_test.add(str(json.loads(line)['pmid']))

    paths = [Path(_paths.LITERATURE)] + [Path(_paths.SOURCE / 'pubmed' / f) for f in CORPUS]
    seen, n = set(), 0
    for path in paths:
        if not path.exists():
            continue
        for line in open(path, encoding='utf-8'):
            try:
                r = json.loads(line)
            except Exception:
                continue
            pmid = str(r.get('pmid'))
            if pmid in seen or pmid in dev_test:
                continue
            seen.add(pmid)
            abstract = B.norm(r.get('abstract'))
            if len(abstract) < 150:
                continue
            for s in B.SENT_SPLIT.split(abstract):
                s = s.strip()
                if len(s) < 30 or len(s) > 300 or '?' in s or s[0].islower():
                    continue
                if not rx.search(s):
                    continue
                ents = B.find_mentions(B.toks(s), ent_idx, ent_maxlen)
                if len({m[2][0] for m in ents}) < 2:
                    continue
                print(f'--- {pmid} | {r.get("year")}')
                print('   ', s)
                for m in ents:
                    print(f'      {m[2][1]:10s} {m[2][0]}')
                n += 1
                if n >= args.limit:
                    return
            if n >= args.limit:
                return
    print('total', n)


if __name__ == '__main__':
    main()
