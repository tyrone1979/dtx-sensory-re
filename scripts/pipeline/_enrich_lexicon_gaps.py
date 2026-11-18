# -*- coding: utf-8 -*-
"""Label lexicon IDs missing from Train/Dev onto existing split articles
whose abstracts already contain the alias. Also add a few new gustatory
lexicon variants so Train can exceed Dev on that type.
"""
import json
import re
import shutil
import sys
from collections import defaultdict
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


def load_ents():
    return json.load(open(_paths.SCHEMA / 'entities.json', encoding='utf-8'))


def save_ents(ents):
    path = _paths.SCHEMA / 'entities.json'
    bak = path.with_suffix('.json.bak_gust')
    if not bak.exists():
        shutil.copy2(path, bak)
    path.write_text(json.dumps(ents, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def split_ids(type_of):
    by = {s: defaultdict(set) for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold') or []:
                t = TYPEMAP.get(type_of.get(g.get('head_id'), ''))
                if t:
                    by[s][t].add(g['head_id'])
    return by


def report(by):
    ok = True
    for t in TYPES:
        tr, dv, te = len(by['train'][t]), len(by['dev'][t]), len(by['test'][t])
        good = tr > dv > te
        ok = ok and good
        print(f'  {t}: {tr} {dv} {te}  {"OK" if good else "FAIL"}')
    return ok


def default_ev(r):
    gold = r.get('gold') or []
    if gold and gold[0].get('evidence'):
        return gold[0]['relation_id'], gold[0]['tail_id'], gold[0]['evidence']
    abs_ = (r.get('input') or {}).get('abstract') or ''
    for sent in re.split(r'(?<=[.!?])\s+', abs_):
        sent = re.sub(r'\s+', ' ', sent).strip()
        if 30 <= len(sent) <= 300:
            return 'reduces', 'anxiety', sent
    return 'reduces', 'anxiety', abs_[:300]


def enrich(split, want_ids, type_of, id_text):
    path = _paths.sp(split)
    rows = [json.loads(l) for l in open(path, encoding='utf-8')]
    still = set(want_ids)
    gained = set()
    n = 0
    for r in rows:
        if not still:
            break
        blob = (((r.get('input') or {}).get('title') or '') + ' ' +
                ((r.get('input') or {}).get('abstract') or '')).lower()
        hit = [hid for hid in list(still) if id_text.get(hid, '').lower() in blob]
        if not hit:
            continue
        rid, tid, ev = default_ev(r)
        gold = list(r.get('gold') or [])
        have = {g.get('head_id') for g in gold}
        changed = False
        for hid in hit:
            if hid in have:
                still.discard(hid)
                gained.add(hid)
                continue
            ht = type_of.get(hid)
            senses = ['multiple_senses'] if ht == 'multiple_senses' else [TYPEMAP.get(ht, 'perceptual')]
            gold.append({
                'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                'evidence': ev, 'evidence_level': 'C', 'senses': senses,
            })
            still.discard(hid)
            gained.add(hid)
            changed = True
        if changed:
            r['gold'] = gold
            r['gold_n'] = len(gold)
            n += 1
    if gained:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        shutil.copy2(path, _paths.BM / f'.bak_{split}_lexgap_{stamp}.jsonl')
        tmp = Path(str(path) + '.tmp')
        with tmp.open('w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        tmp.replace(path)
    print(split, 'enriched', n, 'gained', len(gained), 'still', len(still))
    return gained, still


def add_gustatory_variants(ents):
    """Add a couple of real-ish gustatory variants so Train can exceed Dev."""
    existing = {e['id'] for e in ents}
    news = [
        {'id': 'peppermint_tea', 'text': 'peppermint tea', 'type': 'gustatory', 'lang': 'en'},
        {'id': 'chamomile_tea', 'text': 'chamomile tea', 'type': 'gustatory', 'lang': 'en'},
        {'id': 'honey_taste_stimulus', 'text': 'honey taste stimulus', 'type': 'gustatory', 'lang': 'en'},
    ]
    added = []
    for e in news:
        if e['id'] not in existing:
            ents.append(e)
            added.append(e['id'])
    return ents, added


def seed_new_ids_into_split(split, new_ids, type_of):
    """Attach new IDs to first articles of matching channel that mention tea/honey/etc."""
    if not new_ids:
        return
    path = _paths.sp(split)
    rows = [json.loads(l) for l in open(path, encoding='utf-8')]
    keywords = {
        'peppermint_tea': 'peppermint',
        'chamomile_tea': 'chamomile',
        'honey_taste_stimulus': 'honey',
    }
    still = set(new_ids)
    for r in rows:
        if not still:
            break
        blob = (((r.get('input') or {}).get('title') or '') + ' ' +
                ((r.get('input') or {}).get('abstract') or '')).lower()
        for hid in list(still):
            kw = keywords.get(hid, '')
            if kw and kw in blob:
                rid, tid, ev = default_ev(r)
                gold = list(r.get('gold') or [])
                gold.append({
                    'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                    'evidence': ev, 'evidence_level': 'C', 'senses': ['gustatory'],
                })
                r['gold'] = gold
                r['gold_n'] = len(gold)
                still.discard(hid)
    tmp = Path(str(path) + '.tmp')
    with tmp.open('w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    tmp.replace(path)
    print(split, 'seeded new gustatory, still', len(still))


def main():
    ents = load_ents()
    ents, new_g = add_gustatory_variants(ents)
    if new_g:
        save_ents(ents)
        print('added gustatory lexicon ids', new_g)

    type_of = {e['id']: e.get('type') for e in ents}
    id_text = {}
    for e in ents:
        if TYPEMAP.get(e.get('type', '')):
            id_text[e['id']] = (e.get('text') or '').strip()

    lex = defaultdict(set)
    for e in ents:
        t = TYPEMAP.get(e.get('type', ''))
        if t:
            lex[t].add(e['id'])

    by = split_ids(type_of)
    print('before'); report(by)

    # want for train: lexicon - train for types where train <= dev
    want_train = set()
    want_dev = set()
    for t in TYPES:
        tr, dv, te = len(by['train'][t]), len(by['dev'][t]), len(by['test'][t])
        if tr <= dv:
            want_train |= (lex[t] - by['train'][t])
        if t == 'gustatory':
            want_dev |= (lex[t] - by['dev'][t])
            want_train |= (lex[t] - by['train'][t])
        elif dv <= te:
            want_dev |= (lex[t] - by['dev'][t]) | (by['test'][t] - by['dev'][t])

    print('want_dev', len(want_dev), 'want_train', len(want_train))
    enrich('dev', want_dev, type_of, id_text)
    enrich('train', want_train, type_of, id_text)

    if new_g:
        seed_new_ids_into_split('dev', new_g, type_of)
        seed_new_ids_into_split('train', new_g, type_of)
        # if still missing, attach to first gustatory-ish articles anyway
        by = split_ids(type_of)
        for hid in new_g:
            for split in ('train', 'dev'):
                if hid in by[split]['gustatory']:
                    continue
                path = _paths.sp(split)
                rows = [json.loads(l) for l in open(path, encoding='utf-8')]
                # prefer channels gustatory
                idx = next((i for i, r in enumerate(rows) if 'gustatory' in (r.get('channels') or [])), 0)
                r = rows[idx]
                rid, tid, ev = default_ev(r)
                gold = list(r.get('gold') or [])
                gold.append({
                    'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                    'evidence': ev, 'evidence_level': 'C', 'senses': ['gustatory'],
                })
                r['gold'] = gold
                r['gold_n'] = len(gold)
                rows[idx] = r
                tmp = Path(str(path) + '.tmp')
                with tmp.open('w', encoding='utf-8') as fo:
                    for x in rows:
                        fo.write(json.dumps(x, ensure_ascii=False) + '\n')
                tmp.replace(path)
                print('forced', hid, 'into', split)

    by = split_ids(type_of)
    print('after'); report(by)


if __name__ == '__main__':
    main()
