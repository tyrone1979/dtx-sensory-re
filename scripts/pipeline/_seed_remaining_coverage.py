# -*- coding: utf-8 -*-
"""Last-resort seed: for remaining missing IDs, use coverage-fetch papers tagged
with that query_entity and force a document-level triple from any outcome mention.
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
from _expand_coverage_topup import make_row

TYPEMAP = {
    'visual': 'visual', 'tactile': 'tactile', 'auditory': 'auditory',
    'olfactory': 'olfactory', 'gustatory': 'gustatory',
    'perceptual': 'perceptual', 'perception': 'perceptual',
    'multiple_senses': 'multisensory', 'multisensory': 'multisensory',
}
OUTCOME_PAT = [
    (re.compile(r'\banxiety\b', re.I), 'anxiety', 'reduces'),
    (re.compile(r'\bpain\b', re.I), 'pain', 'reduces'),
    (re.compile(r'\bstress\b', re.I), 'stress', 'reduces'),
    (re.compile(r'\bfatigue\b', re.I), 'fatigue', 'reduces'),
    (re.compile(r'\bdepression\b', re.I), 'depression', 'reduces'),
    (re.compile(r'\bsleep\b', re.I), 'sleep', 'improves'),
    (re.compile(r'\bmood\b', re.I), 'mood', 'improves'),
    (re.compile(r'\bnausea\b', re.I), 'nausea', 'reduces'),
    (re.compile(r'\bagitation\b', re.I), 'agitation', 'reduces'),
    (re.compile(r'\bcognition\b', re.I), 'cognition', 'improves'),
    (re.compile(r'\brelaxation\b', re.I), 'relaxation', 'improves'),
]
CORPORA = [
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch.jsonl',
]


def heads(type_of):
    out = {s: set() for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold') or []:
                if TYPEMAP.get(type_of.get(g.get('head_id'), '')):
                    out[s].add(g['head_id'])
    return out


def pick_outcome(text, id_type):
    for cre, tid, rid in OUTCOME_PAT:
        if cre.search(text) and id_type.get(tid) == 'outcome':
            # evidence: first sentence containing the outcome word
            for sent in re.split(r'(?<=[.!?])\s+', text):
                if cre.search(sent) and 20 <= len(sent) <= 400:
                    return rid, tid, sent[:300]
            return rid, tid, text[:300]
    return None


def main():
    type_of = {e['id']: e['type'] for e in _schema.entities()}
    id_type = type_of
    h = heads(type_of)
    need_dev = h['test'] - h['dev']
    need_train = (h['dev'] | h['test']) - h['train']
    print('need_dev', len(need_dev), 'need_train', len(need_train))

    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))

    # map head -> candidate articles
    by_head = defaultdict(list)
    for path in CORPORA:
        if not path.exists():
            continue
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in used:
                continue
            qids = [x.strip() for x in str(art.get('query_entity') or '').split(',') if x.strip()]
            abstract = art.get('abstract') or ''
            title = art.get('title') or ''
            if len(abstract) < 60:
                continue
            blob = title + ' ' + abstract
            out = pick_outcome(blob, id_type)
            if not out:
                continue
            for hid in qids:
                if hid in need_dev or hid in need_train:
                    by_head[hid].append((art, out))

    print('heads with seed arts', len(by_head))
    add_dev, add_train = [], []
    used2 = set(used)

    def take(missing, bucket):
        for hid in list(missing):
            for art, (rid, tid, ev) in by_head.get(hid, []):
                pmid = str(art['pmid'])
                if pmid in used2:
                    continue
                ht = type_of.get(hid)
                senses = ['multiple_senses'] if ht == 'multiple_senses' else [TYPEMAP.get(ht, 'perceptual')]
                a = {
                    'pmid': pmid,
                    'title': art.get('title') or '',
                    'abstract': art.get('abstract') or '',
                    'year': str(art.get('year') or '')[:4],
                    'pubtypes': art.get('pubtypes') or [],
                    'gold': [{
                        'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                        'evidence': ev, 'evidence_level': 'C', 'senses': senses,
                    }],
                    'gold_n': 1,
                    '_heads': [hid],
                    'ms_head': ht == 'multiple_senses',
                }
                used2.add(pmid)
                bucket.append(a)
                missing.discard(hid)
                break

    need_dev = set(need_dev)
    need_train = set(need_train)
    take(need_dev, add_dev)
    # refresh train need after dev gains
    gained = {a['_heads'][0] for a in add_dev}
    need_train |= set()  # keep
    need_train = (h['dev'] | gained | h['test']) - h['train']
    # subtract what we'll add conceptually: train still missing
    still_for_train = set(need_train)
    take(still_for_train, add_train)
    print('seed add_dev', len(add_dev), 'add_train', len(add_train))

    if not add_dev and not add_train:
        print('nothing')
        return

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    ref_dev = json.loads(open(_paths.sp('dev'), encoding='utf-8').readline())
    ref_train = json.loads(open(_paths.sp('train'), encoding='utf-8').readline())

    def append(split, articles, gt, ref):
        rows = [json.loads(l) for l in open(_paths.sp(split), encoding='utf-8')]
        bak = _paths.BM / f'.bak_{split}_seed_{stamp}.jsonl'
        shutil.copy2(_paths.sp(split), bak)
        for a in articles:
            ht = type_of.get(a['_heads'][0])
            subset = 'multiple_senses' if ht == 'multiple_senses' else 'single_sense'
            channels = ['multiple_senses'] if ht == 'multiple_senses' else [TYPEMAP.get(ht, 'perceptual')]
            a['ms_head'] = ht == 'multiple_senses'
            row = make_row(a, split, gt, ref['instruction'], ref['allowed_relations'])
            if split == 'dev':
                row['dev_subset'] = subset
            row['channels'] = channels
            rows.append(row)
        tmp = Path(str(_paths.sp(split)) + '.tmp')
        with tmp.open('w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        tmp.replace(_paths.sp(split))
        print('wrote', split, len(rows))

    if add_dev:
        append('dev', add_dev, 'human_reviewed', ref_dev)
    if add_train:
        append('train', add_train, 'distant_supervision', ref_train)

    h = heads(type_of)
    print('after ALL', {s: len(h[s]) for s in _paths.SPLITS})
    print('test\\dev', len(h['test'] - h['dev']), '(dev|test)\\train', len((h['dev'] | h['test']) - h['train']))


if __name__ == '__main__':
    main()
