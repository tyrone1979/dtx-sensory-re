# -*- coding: utf-8 -*-
"""Enrich existing Dev/Train rows with missing intervention heads found in their abstracts.

This increases entity-set coverage (Test ⊆ Dev ⊆ Train) without new PMIDs.
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
import build_train_distant as btd

TYPEMAP = {
    'visual': 'visual', 'tactile': 'tactile', 'auditory': 'auditory',
    'olfactory': 'olfactory', 'gustatory': 'gustatory',
    'perceptual': 'perceptual', 'perception': 'perceptual',
    'multiple_senses': 'multisensory', 'multisensory': 'multisensory',
}
KEEP = set(TYPEMAP)
TAIL_RE = re.compile(
    r'\b(anxiety|stress|pain|fatigue|depression|mood|sleep|insomnia|nausea|cortisol|'
    r'attention|alertness|agitation|distress|tension|relaxation|cognition|'
    r'blood pressure|heart rate)\b', re.I)
CUE_MAP = [
    (re.compile(r'\b(reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|attenuat\w+|lower(?:s|ed|ing)?)\b', re.I), 'reduces'),
    (re.compile(r'\b(alleviat\w+|reliev\w+)\b', re.I), 'alleviates'),
    (re.compile(r'\b(improv\w+|beneficial)\b', re.I), 'improves'),
    (re.compile(r'\b(enhanc\w+)\b', re.I), 'enhances'),
    (re.compile(r'\b(promot\w+)\b', re.I), 'promotes'),
]
NEG = re.compile(r'\b(no significant|not significant|did not|nonsignificant)\b', re.I)


def split_heads(type_of):
    out = {s: set() for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold') or []:
                hid = g.get('head_id')
                if TYPEMAP.get(type_of.get(hid, '')):
                    out[s].add(hid)
    return out


def build_aliases(target, type_of):
    pairs = []
    for e in _schema.entities():
        if e['id'] not in target:
            continue
        if e.get('type') not in KEEP and e.get('type') != 'multiple_senses':
            continue
        t = (e.get('text') or '').strip()
        if len(t) >= 3:
            pairs.append((t.lower(), e['id'], e['type']))
    pairs.sort(key=lambda x: -len(x[0]))
    return pairs


def find_effect(abstract, text2id, id_type):
    for sent in btd.SENT_SPLIT.split(abstract):
        sent = btd.norm(sent)
        if len(sent) < 25 or len(sent) > 420 or NEG.search(sent):
            continue
        rel = None
        for cre, rid in CUE_MAP:
            if cre.search(sent):
                rel = rid
                break
        if not rel:
            continue
        m = TAIL_RE.search(sent)
        if not m:
            continue
        tail = m.group(1).lower()
        tid = text2id.get(tail) or text2id.get(tail.replace(' ', '_'))
        if not tid:
            tid = {
                'anxiety': 'anxiety', 'stress': 'stress', 'pain': 'pain',
                'fatigue': 'fatigue', 'depression': 'depression', 'mood': 'mood',
                'sleep': 'sleep', 'insomnia': 'insomnia', 'nausea': 'nausea',
                'cortisol': 'cortisol', 'attention': 'attention',
                'alertness': 'alertness', 'agitation': 'agitation',
                'distress': 'distress', 'tension': 'tension',
                'relaxation': 'relaxation', 'cognition': 'cognition',
                'blood pressure': 'blood_pressure', 'heart rate': 'heart_rate',
            }.get(tail)
        if not tid or id_type.get(tid) != 'outcome':
            continue
        rid = rel
        if rid in ('improves', 'enhances', 'promotes') and re.search(
                r'\b(anxiety|pain|stress|fatigue|depression|nausea|distress|agitation)\b', sent, re.I):
            rid = 'reduces'
        return rid, tid, sent[:300]
    return None


def enrich_split(split, missing, aliases, type_of, text2id, id_type):
    path = _paths.sp(split)
    rows = [json.loads(l) for l in open(path, encoding='utf-8')]
    still = set(missing)
    added_ids = set()
    n_rows = 0
    for r in rows:
        if not still:
            break
        abstract = (r.get('input') or {}).get('abstract') or ''
        title = (r.get('input') or {}).get('title') or ''
        blob = (title + ' ' + abstract).lower()
        if not abstract:
            continue
        present = []
        for al, hid, ht in aliases:
            if hid in still and al in blob:
                present.append((hid, ht))
        if not present:
            continue
        eff = find_effect(abstract, text2id, id_type)
        if not eff:
            # fallback: reuse first existing gold evidence/relation/tail
            gold0 = (r.get('gold') or [None])[0]
            if not gold0:
                continue
            rid, tid, ev = gold0.get('relation_id'), gold0.get('tail_id'), gold0.get('evidence')
            if not (rid and tid and ev):
                continue
        else:
            rid, tid, ev = eff
        gold = list(r.get('gold') or [])
        have = {(g.get('head_id'), g.get('relation_id'), g.get('tail_id')) for g in gold}
        changed = False
        for hid, ht in present:
            if hid not in still:
                continue
            senses = ['multiple_senses'] if ht == 'multiple_senses' else [TYPEMAP.get(ht, ht)]
            trip = {
                'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                'evidence': ev, 'evidence_level': 'C', 'senses': senses,
            }
            key = (hid, rid, tid)
            if key in have:
                still.discard(hid)
                added_ids.add(hid)
                continue
            gold.append(trip)
            have.add(key)
            still.discard(hid)
            added_ids.add(hid)
            changed = True
        if changed:
            r['gold'] = gold
            r['gold_n'] = len(gold)
            n_rows += 1
    if added_ids:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        bak = _paths.BM / f'.bak_{split}_enrich_{stamp}.jsonl'
        shutil.copy2(path, bak)
        tmp = Path(str(path) + '.tmp')
        with tmp.open('w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        tmp.replace(path)
    print(split, 'enriched_rows', n_rows, 'new_ids', len(added_ids), 'still', len(still))
    return added_ids, still


def main():
    type_of = {e['id']: e['type'] for e in _schema.entities()}
    text2id = _schema.text2id()
    id_type = type_of
    heads = split_heads(type_of)
    print('before', {s: len(heads[s]) for s in _paths.SPLITS})
    print('test\\dev', len(heads['test'] - heads['dev']),
          '(dev|test)\\train', len((heads['dev'] | heads['test']) - heads['train']))

    # 1) Enrich Dev with test-missing IDs found in Dev abstracts
    need_dev = heads['test'] - heads['dev']
    aliases = build_aliases(need_dev, type_of)
    enrich_split('dev', need_dev, aliases, type_of, text2id, id_type)

    heads = split_heads(type_of)
    # 2) Enrich Train with (dev|test)-train IDs found in Train abstracts
    need_train = (heads['dev'] | heads['test']) - heads['train']
    aliases = build_aliases(need_train, type_of)
    enrich_split('train', need_train, aliases, type_of, text2id, id_type)

    heads = split_heads(type_of)
    by = {s: defaultdict(set) for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for hid in heads[s]:
            by[s][TYPEMAP.get(type_of.get(hid, ''), '?')].add(hid)
    print('after ALL', {s: len(heads[s]) for s in _paths.SPLITS})
    for t in ['visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multisensory']:
        print(t, {s: len(by[s][t]) for s in _paths.SPLITS})
    print('test\\dev', len(heads['test'] - heads['dev']),
          '(dev|test)\\train', len((heads['dev'] | heads['test']) - heads['train']))
    still = {
        'dev': sorted(heads['test'] - heads['dev']),
        'train': sorted((heads['dev'] | heads['test']) - heads['train']),
    }
    (_paths.SOURCE / 'pubmed' / '_missing_coverage_ids.json').write_text(
        json.dumps(still, indent=2), encoding='utf-8')
    print('still', {k: len(v) for k, v in still.items()})


if __name__ == '__main__':
    main()
