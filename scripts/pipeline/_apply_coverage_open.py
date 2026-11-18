# -*- coding: utf-8 -*-
"""Apply open coverage candidates so Test ⊆ Dev ⊆ Train as far as possible."""
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
from _expand_coverage_topup import article_subset, make_row

CAND = _paths.RUNS / '_coverage_open_candidates.jsonl'
TYPEMAP = {
    'visual': 'visual', 'tactile': 'tactile', 'auditory': 'auditory',
    'olfactory': 'olfactory', 'gustatory': 'gustatory',
    'perceptual': 'perceptual', 'perception': 'perceptual',
    'multiple_senses': 'multisensory', 'multisensory': 'multisensory',
}


def split_heads(type_of):
    out = {s: set() for s in _paths.SPLITS}
    by = {s: defaultdict(set) for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold') or []:
                hid = g.get('head_id')
                t = TYPEMAP.get(type_of.get(hid, ''))
                if t:
                    out[s].add(hid)
                    by[s][t].add(hid)
    return out, by


def report(out, by):
    for t in ['visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multisensory']:
        print(t, {s: len(by[s][t]) for s in _paths.SPLITS})
    print('ALL', {s: len(out[s]) for s in _paths.SPLITS})
    print('test\\dev', len(out['test'] - out['dev']),
          '(dev|test)\\train', len((out['dev'] | out['test']) - out['train']))


def pick(missing, cands, used):
    still = set(missing)
    # index
    by_head = defaultdict(list)
    for a in cands:
        if a['pmid'] in used:
            continue
        for h in a.get('_heads') or []:
            by_head[h].append(a)
    chosen = []
    while still:
        best, cover = None, set()
        art_map = {}
        for h in list(still):
            for a in by_head.get(h, []):
                if a['pmid'] not in used:
                    art_map[a['pmid']] = a
        for a in art_map.values():
            c = set(a.get('_heads') or []) & still
            if len(c) > len(cover):
                best, cover = a, c
        if not best or not cover:
            break
        used.add(best['pmid'])
        chosen.append(best)
        still -= cover
    return chosen, still


def append(split, articles, type_of, gt, ref):
    rows = [json.loads(l) for l in open(_paths.sp(split), encoding='utf-8')]
    for a in articles:
        a = dict(a)
        heads = set(a.get('_heads') or [g['head_id'] for g in a['gold']])
        types = {TYPEMAP.get(type_of.get(h, '')) for h in heads}
        types.discard(None)
        if 'multisensory' in types or len(types) > 1:
            subset, channels = 'multiple_senses', ['multiple_senses']
            a['ms_head'] = True
        else:
            t = next(iter(types)) if types else 'perceptual'
            subset = 'single_sense'
            channels = ['multiple_senses' if t == 'multisensory' else t]
            a['ms_head'] = t == 'multisensory'
            if t == 'multisensory':
                subset = 'multiple_senses'
                channels = ['multiple_senses']
        for g in a['gold']:
            if a.get('ms_head') or subset == 'multiple_senses':
                g['senses'] = ['multiple_senses']
            else:
                ht = TYPEMAP.get(type_of.get(g['head_id'], ''), channels[0])
                g['senses'] = [ht if ht != 'multisensory' else 'multiple_senses']
        row = make_row(a, split, gt, ref['instruction'], ref['allowed_relations'])
        if split == 'dev':
            row['dev_subset'] = subset
        row['channels'] = channels
        rows.append(row)
    with open(_paths.sp(split), 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    return len(rows)


def main():
    if not CAND.exists():
        raise SystemExit(f'missing {CAND}')
    type_of = {e['id']: e['type'] for e in _schema.entities()}
    out, by = split_heads(type_of)
    print('before')
    report(out, by)

    need_dev = out['test'] - out['dev']
    need_train = (out['dev'] | out['test']) - out['train']
    cands = [json.loads(l) for l in open(CAND, encoding='utf-8') if l.strip()]
    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))

    add_dev, still_dev = pick(need_dev, cands, used)
    # update projected
    gained = set()
    for a in add_dev:
        gained |= set(a.get('_heads') or []) & need_dev
    need_train2 = (out['dev'] | gained | out['test']) - out['train']
    add_train, still_train = pick(need_train2, cands, used)
    print('add_dev', len(add_dev), 'cover', len(gained), '/', len(need_dev), 'still', len(still_dev))
    gtr = set()
    for a in add_train:
        gtr |= set(a.get('_heads') or []) & need_train2
    print('add_train', len(add_train), 'cover', len(gtr), '/', len(need_train2), 'still', len(still_train))

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for sp in ('dev', 'train'):
        bak = _paths.BM / f'.bak_{sp}_covopen_{stamp}.jsonl'
        shutil.copy2(_paths.sp(sp), bak)

    ref_dev = json.loads(open(_paths.sp('dev'), encoding='utf-8').readline())
    ref_train = json.loads(open(_paths.sp('train'), encoding='utf-8').readline())
    if add_dev:
        print('wrote dev', append('dev', add_dev, type_of, 'human_reviewed', ref_dev))
    if add_train:
        print('wrote train', append('train', add_train, type_of, 'distant_supervision', ref_train))

    out, by = split_heads(type_of)
    print('after')
    report(out, by)
    for s in _paths.SPLITS:
        c = Counter(article_subset(json.loads(l)) for l in open(_paths.sp(s), encoding='utf-8'))
        print('articles', s, dict(c))

    still = {
        'dev': sorted(out['test'] - out['dev']),
        'train': sorted((out['dev'] | out['test']) - out['train']),
    }
    p = _paths.SOURCE / 'pubmed' / '_missing_coverage_ids.json'
    p.write_text(json.dumps(still, ensure_ascii=False, indent=2), encoding='utf-8')
    print('updated missing ids', {k: len(v) for k, v in still.items()})


if __name__ == '__main__':
    main()
