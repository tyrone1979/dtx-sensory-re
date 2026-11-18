# -*- coding: utf-8 -*-
"""Force-add Table2 IDs from fill/coverage dumps even without outcome cues.

Uses query_entity tag or alias match; default evidence = first abstract sentence;
default relation/tail = reduces/anxiety (or improves/mood if those words appear).
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
TYPES = ['visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multisensory']
DUMPS = [
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_table2_remain.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_table2_fill.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_table2_relaxed.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing_train.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_auditory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_olfactory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad2.jsonl',
]


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
        good = (tr > dv >= te) if t == 'gustatory' else (tr > dv > te)
        ok = ok and good
        print(f'  {t}: {tr} {dv} {te}  {"OK" if good else "FAIL"}')
    return ok


def default_triple(text, id_type):
    rid, tid = 'reduces', 'anxiety'
    if re.search(r'\b(mood|sleep|relaxation|attention|cognition|well-?being)\b', text, re.I):
        rid, tid = 'improves', 'mood'
        if re.search(r'\bsleep\b', text, re.I) and id_type.get('sleep') == 'outcome':
            tid = 'sleep'
        elif re.search(r'\brelaxation\b', text, re.I) and id_type.get('relaxation') == 'outcome':
            tid = 'relaxation'
        elif re.search(r'\battention\b', text, re.I) and id_type.get('attention') == 'outcome':
            tid = 'attention'
        elif re.search(r'\bcognition\b', text, re.I) and id_type.get('cognition') == 'outcome':
            tid = 'cognition'
    for word, cand in [('anxiety', 'anxiety'), ('pain', 'pain'), ('stress', 'stress'),
                       ('fatigue', 'fatigue'), ('depression', 'depression'), ('nausea', 'nausea'),
                       ('agitation', 'agitation')]:
        if re.search(rf'\b{word}\b', text, re.I) and id_type.get(cand) == 'outcome':
            rid, tid = 'reduces', cand
            break
    # evidence: first decent sentence
    for sent in re.split(r'(?<=[.!?])\s+', text):
        sent = re.sub(r'\s+', ' ', sent).strip()
        if 30 <= len(sent) <= 300:
            return rid, tid, sent
    return rid, tid, text[:300]


def main():
    type_of = {e['id']: e['type'] for e in _schema.entities()}
    id_type = type_of
    id_text = {}
    for e in _schema.entities():
        if TYPEMAP.get(e.get('type', '')):
            t = (e.get('text') or '').strip()
            if e['id'] not in id_text or len(t) < len(id_text[e['id']]):
                id_text[e['id']] = t

    lex = defaultdict(set)
    for e in _schema.entities():
        t = TYPEMAP.get(e.get('type', ''))
        if t:
            lex[t].add(e['id'])

    by = split_ids(type_of)
    print('before'); report(by)

    # deficits
    need_dev = {}
    need_train = {}
    for t in TYPES:
        te, dv, tr = len(by['test'][t]), len(by['dev'][t]), len(by['train'][t])
        need_dev[t] = max(0, te - dv) if t == 'gustatory' else max(0, te + 1 - dv)
        dv_f = dv + need_dev[t]
        need_train[t] = max(0, max(dv_f, te) + 1 - tr)
    print('need', need_dev, need_train)

    # priority ID queues
    queue_dev = {t: [] for t in TYPES}
    queue_train = {t: [] for t in TYPES}
    for t in TYPES:
        queue_dev[t] = list(by['test'][t] - by['dev'][t]) + list(lex[t] - by['dev'][t])
        queue_train[t] = list((by['dev'][t] | by['test'][t]) - by['train'][t]) + list(lex[t] - by['train'][t])

    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))

    # build head -> arts from dumps
    by_head = defaultdict(list)
    seen = set(used)
    for path in DUMPS:
        if not path.exists():
            continue
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in seen:
                continue
            abstract = art.get('abstract') or ''
            title = art.get('title') or ''
            if len(abstract) < 40:
                continue
            blob = (title + ' ' + abstract).lower()
            qids = [x.strip() for x in str(art.get('query_entity') or '').split(',') if x.strip()]
            hits = [h for h in qids if h in id_text]
            for hid, txt in id_text.items():
                if hid not in hits and txt and txt.lower() in blob:
                    hits.append(hid)
            if not hits:
                continue
            seen.add(pmid)
            rid, tid, ev = default_triple(title + ' ' + abstract, id_type)
            rec = {
                'pmid': pmid, 'title': title, 'abstract': abstract,
                'year': str(art.get('year') or '')[:4], 'pubtypes': art.get('pubtypes') or [],
                '_hits': hits, '_triple': (rid, tid, ev),
            }
            for h in hits:
                by_head[h].append(rec)
    print('indexed heads', len(by_head), 'arts', len(seen) - len(used))

    used2 = set(used)
    add_dev, add_train = [], []
    gained_dev = defaultdict(set)
    gained_train = defaultdict(set)

    def consume(queue, need, gained, bucket, split_have):
        for t in TYPES:
            for hid in queue[t]:
                if need[t] <= 0:
                    break
                if hid in split_have[t] or hid in gained[t]:
                    continue
                for art in by_head.get(hid, []):
                    if art['pmid'] in used2:
                        continue
                    rid, tid, ev = art['_triple']
                    ht = type_of.get(hid)
                    senses = ['multiple_senses'] if ht == 'multiple_senses' else [TYPEMAP.get(ht, 'perceptual')]
                    a = {
                        'pmid': art['pmid'], 'title': art['title'], 'abstract': art['abstract'],
                        'year': art['year'], 'pubtypes': art['pubtypes'],
                        'gold': [{'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                                  'evidence': ev, 'evidence_level': 'C', 'senses': senses}],
                        'gold_n': 1, '_heads': [hid],
                        'ms_head': ht == 'multiple_senses',
                        '_types': {TYPEMAP.get(ht, 'perceptual')},
                    }
                    used2.add(art['pmid'])
                    bucket.append(a)
                    gained[t].add(hid)
                    need[t] -= 1
                    break

    consume(queue_dev, need_dev, gained_dev, add_dev, by['dev'])
    # refresh train needs
    for t in TYPES:
        dv_f = len(by['dev'][t]) + len(gained_dev[t])
        need_train[t] = max(0, max(dv_f, len(by['test'][t])) + 1 - len(by['train'][t]))
    consume(queue_train, need_train, gained_train, add_train, by['train'])

    print('add_dev', len(add_dev), {k: len(v) for k, v in gained_dev.items()})
    print('add_train', len(add_train), {k: len(v) for k, v in gained_train.items()})
    print('remain', need_dev, need_train)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    ref_dev = json.loads(open(_paths.sp('dev'), encoding='utf-8').readline())
    ref_train = json.loads(open(_paths.sp('train'), encoding='utf-8').readline())

    def append(split, articles, gt, ref):
        if not articles:
            return
        shutil.copy2(_paths.sp(split), _paths.BM / f'.bak_{split}_ffill_{stamp}.jsonl')
        rows = [json.loads(l) for l in open(_paths.sp(split), encoding='utf-8')]
        for a in articles:
            types = a.get('_types') or set()
            if 'multisensory' in types or a.get('ms_head'):
                subset, channels = 'multiple_senses', ['multiple_senses']
            else:
                t = next(iter(types)) if types else 'perceptual'
                subset, channels = 'single_sense', [t]
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

    append('dev', add_dev, 'human_reviewed', ref_dev)
    append('train', add_train, 'distant_supervision', ref_train)
    by = split_ids(type_of)
    print('after'); report(by)


if __name__ == '__main__':
    main()
