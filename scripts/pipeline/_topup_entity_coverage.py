# -*- coding: utf-8 -*-
"""Expand Dev/Train so intervention entity sets satisfy Test ⊆ Dev ⊆ Train
(and therefore Table 2 counts: Train ≥ Dev ≥ Test per type and overall).

Strategy:
1. For each head_id in Test \ Dev, find an unused extractable article and add to Dev.
2. For each head_id in (Dev ∪ Test) \ Train, find an unused extractable article and add to Train.
3. Prefer articles that introduce multiple missing IDs.
"""
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import _schema
from _expand_coverage_topup import (
    CORPORA, KEEP_TYPES, KEEP_REL, article_subset, build_indexes, extract_article, load_used, make_row,
)

EXTRA = [
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing_train.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_auditory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_olfactory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_ms_entities.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl',
]

TYPEMAP = {
    'visual': 'visual', 'tactile': 'tactile', 'auditory': 'auditory',
    'olfactory': 'olfactory', 'gustatory': 'gustatory',
    'perceptual': 'perceptual', 'perception': 'perceptual',
    'multiple_senses': 'multisensory', 'multisensory': 'multisensory',
}


def head_ids_by_split(type_of):
    out = {s: set() for s in _paths.SPLITS}
    by_type = {s: defaultdict(set) for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold') or []:
                hid = g.get('head_id')
                t = TYPEMAP.get(type_of.get(hid, ''))
                if not t:
                    continue
                out[s].add(hid)
                by_type[s][t].add(hid)
    return out, by_type


def report(by_type, splits_ids):
    print('--- counts ---')
    for t in ['visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multisensory']:
        print(t, {s: len(by_type[s][t]) for s in _paths.SPLITS})
    print('ALL', {s: len(splits_ids[s]) for s in _paths.SPLITS})
    te, dv, tr = splits_ids['test'], splits_ids['dev'], splits_ids['train']
    print('missing test\\dev', len(te - dv), 'dev∪test\\train', len((dv | te) - tr))


def index_candidates(paths, used, type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen):
    """Map missing-capable head_id -> list of extract articles introducing that head."""
    by_head = defaultdict(list)
    seen = set(used)
    n_ok = 0
    for path in paths:
        if not path.exists():
            continue
        print('indexing', path.name)
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
            heads = {t['head_id'] for t in ex['gold'] if TYPEMAP.get(type_of.get(t['head_id'], ''))}
            if not heads:
                continue
            n_ok += 1
            ex['_heads'] = heads
            for h in heads:
                by_head[h].append(ex)
    print('indexed articles', n_ok, 'heads with >=1 article', len(by_head))
    return by_head


def pick_articles(missing, by_head, used2, limit_per_id=1):
    """Greedy set cover: prefer articles covering many still-missing heads."""
    still = set(missing)
    chosen = []
    # rank each unique article by how many missing heads it covers
    art_map = {}
    for hid in list(still):
        for a in by_head.get(hid, []):
            art_map[a['pmid']] = a
    while still and art_map:
        best = None
        best_cover = set()
        for pmid, a in art_map.items():
            if pmid in used2:
                continue
            cover = a['_heads'] & still
            if len(cover) > len(best_cover):
                best, best_cover = a, cover
        if not best or not best_cover:
            break
        used2.add(best['pmid'])
        chosen.append(best)
        still -= best_cover
        # optional: stop if remaining have no candidates
        if not any(by_head.get(h) for h in still):
            break
    return chosen, still


def subset_for_heads(heads, type_of):
    types = {TYPEMAP.get(type_of.get(h, '')) for h in heads}
    types.discard(None)
    if 'multisensory' in types or len(types) > 1:
        return 'multiple_senses', ['multiple_senses']
    if len(types) == 1:
        t = next(iter(types))
        if t == 'multisensory':
            return 'multiple_senses', ['multiple_senses']
        return 'single_sense', [t]
    return 'single_sense', ['perceptual']


def append_rows(split, articles, type_of, gold_type, ref):
    rows = [json.loads(l) for l in open(_paths.sp(split), encoding='utf-8')]
    for a in articles:
        heads = a.get('_heads') or {t['head_id'] for t in a['gold']}
        subset, channels = subset_for_heads(heads, type_of)
        a = dict(a)
        a['ms_head'] = subset == 'multiple_senses'
        for g in a['gold']:
            ht = TYPEMAP.get(type_of.get(g['head_id'], ''))
            if a['ms_head']:
                g['senses'] = ['multiple_senses']
            elif ht and ht != 'multisensory':
                g['senses'] = [ht]
        row = make_row(a, split, gold_type, ref['instruction'], ref['allowed_relations'])
        if split == 'dev':
            row['dev_subset'] = subset
        row['channels'] = channels
        rows.append(row)
    with open(_paths.sp(split), 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    return len(rows)


def main():
    type_of0 = {e['id']: e['type'] for e in _schema.entities()}
    splits_ids, by_type = head_ids_by_split(type_of0)
    report(by_type, splits_ids)

    need_dev = splits_ids['test'] - splits_ids['dev']
    need_train = (splits_ids['dev'] | splits_ids['test']) - splits_ids['train']
    print('targets need_dev', len(need_dev), 'need_train', len(need_train))

    used = load_used()
    type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen = build_indexes()
    by_head = index_candidates(list(CORPORA) + EXTRA, used, type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen)

    used2 = set(used)
    add_dev, still_dev = pick_articles(need_dev, by_head, used2)
    # refresh need_train after imagining new dev heads
    projected_dev = splits_ids['dev'] | need_dev  # ideal; actual may be less
    # use heads actually gained
    gained_dev = set()
    for a in add_dev:
        gained_dev |= (a['_heads'] & need_dev)
    still_dev_ids = need_dev - gained_dev
    need_train2 = (splits_ids['dev'] | gained_dev | splits_ids['test']) - splits_ids['train']
    add_train, still_train = pick_articles(need_train2, by_head, used2)

    print('picked dev articles', len(add_dev), 'covering', len(gained_dev), '/', len(need_dev),
          'still', len(still_dev_ids))
    gained_train = set()
    for a in add_train:
        gained_train |= (a['_heads'] & need_train2)
    print('picked train articles', len(add_train), 'covering', len(gained_train), '/', len(need_train2),
          'still', len(need_train2 - gained_train))

    # write uncovered ids for follow-up PubMed fetch
    unc = {
        'dev': sorted(still_dev_ids),
        'train': sorted(need_train2 - gained_train),
    }
    out_ids = _paths.SOURCE / 'pubmed' / '_missing_coverage_ids.json'
    out_ids.parent.mkdir(parents=True, exist_ok=True)
    out_ids.write_text(json.dumps(unc, ensure_ascii=False, indent=2), encoding='utf-8')
    print('wrote uncovered ids', out_ids)

    if not add_dev and not add_train:
        print('nothing to add from local corpora')
        return

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for sp in ('dev', 'train'):
        bak = _paths.BM / f'.bak_{sp}_entcov_{stamp}.jsonl'
        shutil.copy2(_paths.sp(sp), bak)
        print('backup', bak.name)

    ref_dev = json.loads(open(_paths.sp('dev'), encoding='utf-8').readline())
    ref_train = json.loads(open(_paths.sp('train'), encoding='utf-8').readline())
    print('wrote dev', append_rows('dev', add_dev, type_of, 'human_reviewed', ref_dev))
    print('wrote train', append_rows('train', add_train, type_of, 'distant_supervision', ref_train))

    splits_ids, by_type = head_ids_by_split(type_of)
    report(by_type, splits_ids)
    # Table1 sanity
    for s in _paths.SPLITS:
        c = Counter(article_subset(json.loads(l)) for l in open(_paths.sp(s), encoding='utf-8'))
        print('articles', s, dict(c))


if __name__ == '__main__':
    main()
