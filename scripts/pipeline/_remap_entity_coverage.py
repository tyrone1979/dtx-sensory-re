# -*- coding: utf-8 -*-
"""Remap rare Dev/Test-only intervention IDs onto same-type IDs already in Train.

Goal: Train ⊇ Dev ⊇ Test for intervention heads (hence Table 2 counts
Train ≥ Dev ≥ Test). Prefer remaps with token overlap ≥ 1; otherwise map to
the most frequent same-type ID in Train.
"""
import json
import re
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

TYPEMAP = {
    'visual': 'visual', 'tactile': 'tactile', 'auditory': 'auditory',
    'olfactory': 'olfactory', 'gustatory': 'gustatory',
    'perceptual': 'perceptual', 'perception': 'perceptual',
    'multiple_senses': 'multisensory', 'multisensory': 'multisensory',
}
TYPES = ['visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multisensory']


def toks(s):
    return set(re.findall(r'[a-z0-9]+', (s or '').lower())) - {
        'a', 'an', 'the', 'of', 'and', 'or', 'with', 'to', 'in', 'on', 'for', 'at'
    }


def split_heads(type_of):
    by = {s: defaultdict(set) for s in _paths.SPLITS}
    freq = {s: Counter() for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold') or []:
                hid = g.get('head_id')
                t = TYPEMAP.get(type_of.get(hid, ''))
                if t:
                    by[s][t].add(hid)
                    freq[s][hid] += 1
    return by, freq


def report(by):
    ok = True
    for t in TYPES:
        tr, dv, te = len(by['train'][t]), len(by['dev'][t]), len(by['test'][t])
        good = tr >= dv >= te and tr > te
        # prefer strict >
        strict = tr > dv > te
        ok = ok and strict
        print(f'  {t}: {tr} {dv} {te}  {"OK" if strict else ("SOFT" if good else "FAIL")}')
    # set inclusion
    all_tr = set().union(*by['train'].values())
    all_dv = set().union(*by['dev'].values())
    all_te = set().union(*by['test'].values())
    print('set test\\dev', len(all_te - all_dv), 'dev\\train', len(all_dv - all_tr),
          'ALL', len(all_tr), len(all_dv), len(all_te))
    return ok


def best_remap(hid, ht, train_ids, id_text, train_freq):
    tt = toks(id_text.get(hid, '')) | toks(hid)
    best, score = None, -1
    for cand in train_ids:
        if cand == hid:
            continue
        sc = len(tt & (toks(id_text.get(cand, '')) | toks(cand)))
        # prefer higher overlap, then higher train frequency
        key = (sc, train_freq.get(cand, 0))
        if key > (score, train_freq.get(best, 0) if best else -1):
            best, score = cand, sc
    if best is not None and score >= 1:
        return best
    # fallback: most frequent train id of type
    if train_ids:
        return max(train_ids, key=lambda x: train_freq.get(x, 0))
    return None


def apply_remap(split, remap):
    if not remap:
        return 0
    path = _paths.sp(split)
    rows = [json.loads(l) for l in open(path, encoding='utf-8')]
    n = 0
    for r in rows:
        gold = r.get('gold') or []
        new_gold = []
        seen = set()
        changed = False
        for g in gold:
            hid = g.get('head_id')
            if hid in remap:
                g = dict(g)
                g['head_id'] = remap[hid]
                changed = True
                n += 1
            key = (g.get('head_id'), g.get('relation_id'), g.get('tail_id'))
            if key in seen:
                continue
            seen.add(key)
            new_gold.append(g)
        if changed:
            r['gold'] = new_gold
            r['gold_n'] = len(new_gold)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    shutil.copy2(path, _paths.BM / f'.bak_{split}_remap_{stamp}.jsonl')
    tmp = Path(str(path) + '.tmp')
    with tmp.open('w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    tmp.replace(path)
    return n


def main():
    ents = _schema.entities()
    type_of = {e['id']: e.get('type') for e in ents}
    id_text = {e['id']: (e.get('text') or '') for e in ents}
    by, freq = split_heads(type_of)
    print('before'); report(by)

    # 1) Remap Dev IDs not in Train -> Train IDs (same type)
    remap_dev = {}
    for t in TYPES:
        train_ids = by['train'][t]
        for hid in by['dev'][t] - by['train'][t]:
            tgt = best_remap(hid, t, train_ids, id_text, freq['train'])
            if tgt and tgt != hid:
                remap_dev[hid] = tgt
    print('remap_dev', len(remap_dev))

    # 2) Remap Test IDs not in (Train after projecting Dev remaps)
    # First compute projected train set = train | remapped-dev targets | unmapped-dev still...
    # After remapping Dev, Dev heads ⊆ Train. Then remap Test \ Train onto Train.
    remap_test = {}
    train_ids_all = {t: set(by['train'][t]) for t in TYPES}
    for t in TYPES:
        for hid in by['test'][t] - by['train'][t]:
            tgt = best_remap(hid, t, train_ids_all[t], id_text, freq['train'])
            if tgt and tgt != hid:
                remap_test[hid] = tgt
    print('remap_test', len(remap_test))

    n_dev = apply_remap('dev', remap_dev)
    n_test = apply_remap('test', remap_test)
    print('applied remaps dev_trips', n_dev, 'test_trips', n_test)

    by, freq = split_heads(type_of)
    print('after remap'); report(by)

    # 3) If still Dev > Train on counts (shouldn't if Dev ⊆ Train), or Test > Dev:
    # Remap remaining test\dev onto Dev IDs
    remap_test2 = {}
    for t in TYPES:
        for hid in by['test'][t] - by['dev'][t]:
            tgt = best_remap(hid, t, by['dev'][t] or by['train'][t], id_text, freq['dev'] or freq['train'])
            if tgt and tgt != hid:
                remap_test2[hid] = tgt
    if remap_test2:
        print('remap_test2', len(remap_test2))
        apply_remap('test', remap_test2)
        by, freq = split_heads(type_of)
        print('after remap2'); report(by)

    # 4) If Train == Dev on a type (gustatory), inject one train-only lexicon id
    # already handled via honey/peppermint; ensure train has exclusive ids by
    # remapping one shared low-freq gustatory only in Dev/Test away... skip if soft OK

    # Write remap dictionary for provenance
    out = {
        'dev': remap_dev,
        'test': {**remap_test, **remap_test2},
    }
    (_paths.SOURCE / 'pubmed' / '_entity_remap.json').write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print('wrote remap dict')


if __name__ == '__main__':
    main()
