# -*- coding: utf-8 -*-
"""Probe how many unused extractable articles exist per sensory subset."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import build_train_distant as btd
from _expand_coverage_topup import (
    CORPORA, KEEP_TYPES, KEEP_REL, build_indexes, extract_article, load_used, article_subset,
)

EXTRA = [
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing_train.jsonl',
]


def primary_sense(art_ex, type_of):
    if art_ex.get('ms_head'):
        return 'multisensory'
    for t in art_ex['gold']:
        ht = type_of.get(t['head_id'])
        if ht == 'multiple_senses':
            return 'multisensory'
        if ht in KEEP_TYPES:
            return ht
    return 'unknown'


def main():
    used = load_used()
    type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen = build_indexes()
    counts = {k: 0 for k in ('visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multisensory')}
    seen = set(used)
    paths = list(CORPORA) + EXTRA
    for path in paths:
        if not path.exists():
            continue
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in seen:
                continue
            ex = extract_article(art, type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen,
                                 prefer_missing=None, force_ms=False)
            if not ex:
                continue
            seen.add(pmid)
            sense = primary_sense(ex, type_of)
            if sense in counts:
                counts[sense] += 1
    print('unused extractable by head type:', counts)
    print('current subsets:')
    for s in _paths.SPLITS:
        from collections import Counter
        c = Counter()
        for line in open(_paths.sp(s), encoding='utf-8'):
            c[article_subset(json.loads(line))] += 1
        print(s, dict(c))


if __name__ == '__main__':
    main()
