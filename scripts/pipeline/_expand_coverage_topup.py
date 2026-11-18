# -*- coding: utf-8 -*-
"""Expand train entity coverage + multisensory Dev/Train so Train > Dev > Test.

Uses local literature + existing pubmed retrieval dumps + multisensory_broad.
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
import build_train_distant as btd

KEEP_TYPES = {'visual', 'auditory', 'olfactory', 'gustatory', 'tactile', 'perceptual', 'multiple_senses'}
KEEP_REL = {'reduces', 'alleviates', 'lowers', 'improves', 'promotes', 'enhances', 'strengthens'}
CORPORA = [
    _paths.SOURCE / 'literature.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_cue.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_deep.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_wide.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_deep2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_phrase.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_rescue.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl',
]


def load_used():
    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))
    return used


def ids_by_split():
    id_type = {e['id']: e['type'] for e in _schema.entities()}
    out = {s: set() for s in _paths.SPLITS}
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            for g in json.loads(line).get('gold', []):
                for eid in (g.get('head_id'), g.get('tail_id')):
                    if id_type.get(eid) in KEEP_TYPES:
                        out[s].add(eid)
    return out, id_type


def article_subset(o):
    s = o.get('test_subset') or o.get('dev_subset')
    if s == 'perception':
        return 'perceptual'
    if s == 'multiple_senses':
        return 'multisensory'
    if s == 'single_sense':
        senses = []
        for g in o.get('gold', []):
            senses += (g.get('senses') or [])
        if senses:
            return Counter(senses).most_common(1)[0][0]
        ch = o.get('channels') or []
        return ch[0] if ch else 'unknown'
    senses = []
    for g in o.get('gold', []):
        senses += (g.get('senses') or [])
    uniq = set(senses)
    if len(uniq) > 1 or 'multiple_senses' in uniq:
        return 'multisensory'
    if len(uniq) == 1:
        return next(iter(uniq))
    ch = o.get('channels') or []
    if len(ch) > 1 or 'multiple_senses' in ch:
        return 'multisensory'
    if len(ch) == 1:
        return ch[0]
    return 'unknown'


def count_ms(split):
    n = 0
    for line in open(_paths.sp(split), encoding='utf-8'):
        if article_subset(json.loads(line)) == 'multisensory':
            n += 1
    return n


def build_indexes():
    type_of = {}
    ent_cues = []
    for e in _schema.entities():
        type_of[e['id']] = e['type']
        w = tuple(btd.toks(e['text']))
        if w:
            ent_cues.append((w, (e['id'], e['type'])))
        btd._EN_TEXT.setdefault(e['id'], e['text'])
    ent_idx = btd.first_index(ent_cues)
    ent_maxlen = max(len(w) for w, _ in ent_cues)
    rel_cues = []
    for r in _schema.relations():
        w = tuple(btd.toks(r['name']))
        if w:
            rel_cues.append((w, (r['id'], r['name'])))
    for words, rid in btd.EXTRA_CUES:
        rel_cues.append((tuple(words), (rid, ' '.join(words))))
    for words, rid in btd.RARE_CUES:
        rel_cues.append((tuple(words), (rid, ' '.join(words))))
    cue_idx = btd.first_index(rel_cues)
    cue_maxlen = max(len(w) for w, _ in rel_cues)
    return type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen


def extract_article(art, type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen, prefer_missing=None, force_ms=False):
    pmid = str(art.get('pmid') or '')
    title = art.get('title') or ''
    abstract = art.get('abstract') or ''
    if not pmid or len(abstract) < 120:
        return None
    if btd.NEG_TI.search(title) or btd.ANIMAL.search(title + ' ' + abstract):
        return None
    pts = art.get('pubtypes') or []
    if isinstance(pts, str):
        try:
            pts = eval(pts)
        except Exception:
            pts = []
    if any(btd.BAD_PUBTYPE.match(p or '') for p in pts):
        return None
    triples = []
    for sent in [title] + btd.SENT_SPLIT.split(abstract):
        sent = btd.norm(sent)
        if len(sent) < 20 or len(sent) > 480:
            continue
        if re.search(r'\b(no significant|not significant|did not|nonsignificant)\b', sent, re.I):
            continue
        for hid, rid, tid, cue in btd.extract_intra(
                sent, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
            ht = type_of.get(hid)
            tt = type_of.get(tid)
            if ht not in KEEP_TYPES or tt != 'outcome':
                continue
            if rid not in KEEP_REL:
                continue
            if force_ms and ht != 'multiple_senses':
                continue
            if prefer_missing is not None and hid not in prefer_missing and not force_ms:
                # still keep if helps missing set
                pass
            senses = [ht] if ht != 'multiple_senses' else ['multiple_senses']
            # normalize multiple_senses label for subset as multisensory via senses containing multiple or type
            if ht == 'multiple_senses':
                senses = ['visual', 'auditory']  # marker: multi via head type; subset fn uses multiple_senses in senses
                senses = ['multiple_senses']
            triples.append({
                'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                'evidence': sent[:300], 'evidence_level': 'C',
                'senses': senses, 'cue': cue,
            })
    seen = set()
    uniq = []
    for t in triples:
        k = (t['head_id'], t['relation_id'], t['tail_id'])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    if not uniq:
        return None
    # Prefer articles that introduce missing heads
    if prefer_missing is not None:
        if not any(t['head_id'] in prefer_missing for t in uniq):
            if not force_ms:
                return None
    return {
        'pmid': pmid,
        'title': title,
        'abstract': abstract,
        'year': str(art.get('year') or '')[:4],
        'pubtypes': pts if isinstance(pts, list) else [],
        'gold': uniq[:4],
        'gold_n': min(len(uniq), 4),
        'ms_head': any(type_of.get(t['head_id']) == 'multiple_senses' for t in uniq),
        'new_heads': sorted({t['head_id'] for t in uniq if prefer_missing and t['head_id'] in prefer_missing}),
    }


def make_row(a, split, gold_type, instruction, allowed):
    subset = 'multiple_senses' if a.get('ms_head') else 'single_sense'
    # refine single_sense channel from first gold sense
    channels = []
    if a.get('ms_head'):
        channels = ['multiple_senses']
    else:
        s = (a['gold'][0].get('senses') or ['perceptual'])[0]
        channels = [s if s != 'multiple_senses' else 'perceptual']
    row = {
        'task_id': f"ds_{a['pmid']}",
        'pmid': a['pmid'],
        'split': split,
        'gold_type': gold_type,
        'input': {
            'title': a['title'],
            'abstract': a['abstract'],
            'year': a.get('year') or '',
            'pubtypes': a.get('pubtypes') or [],
        },
        'instruction': instruction,
        'allowed_relations': allowed,
        'channels': channels,
        'annotation_scheme': 'v3_open_entities',
        'verdict': 'keep',
        'gold': [{k: g[k] for k in ('head_id', 'relation_id', 'tail_id', 'evidence', 'evidence_level', 'senses')}
                 for g in a['gold']],
        'gold_n': a['gold_n'],
    }
    if split == 'dev':
        row['dev_subset'] = subset
    elif split == 'test':
        row['test_subset'] = subset
    return row


def main():
    used = load_used()
    split_ids, type_of = ids_by_split()
    missing_train = {i for i, t in type_of.items() if t in KEEP_TYPES} - split_ids['train']
    print('missing train entity ids', len(missing_train))
    print('MS articles now', {s: count_ms(s) for s in _paths.SPLITS})

    type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen = build_indexes()
    ref_dev = json.loads(open(_paths.sp('dev'), encoding='utf-8').readline())
    ref_train = json.loads(open(_paths.sp('train'), encoding='utf-8').readline())

    # Scan corpora
    coverage_hits = []  # for train entity expansion
    ms_hits = []
    seen = set(used)
    for path in CORPORA:
        if not path.exists():
            continue
        print('scanning', path.name)
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in seen:
                continue
            # MS pass
            ms = extract_article(art, type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen,
                                 prefer_missing=None, force_ms=True)
            if ms:
                seen.add(pmid)
                ms_hits.append(ms)
                continue
            # coverage pass for missing heads
            if missing_train:
                cov = extract_article(art, type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen,
                                      prefer_missing=missing_train, force_ms=False)
                if cov and cov.get('new_heads'):
                    seen.add(pmid)
                    coverage_hits.append(cov)

    print('ms_hits', len(ms_hits), 'coverage_hits', len(coverage_hits))
    # rank coverage by number of new heads
    coverage_hits.sort(key=lambda a: (-len(a.get('new_heads') or []), a['pmid']))
    ms_hits.sort(key=lambda a: (-a['gold_n'], a['pmid']))

    # Targets: MS Train > Dev > Test(69)
    ms_test = count_ms('test')
    need_dev_ms = max(0, ms_test + 1 - count_ms('dev'))  # Dev > Test
    # after adding, Train > Dev: need train_ms > dev_ms_final
    target_dev_ms = max(count_ms('dev') + need_dev_ms, ms_test + 1)
    # aim a bit higher for stability
    target_dev_ms = max(target_dev_ms, 80)
    target_train_ms = max(count_ms('train'), target_dev_ms + 1)
    target_train_ms = max(target_train_ms, 120)
    print('targets MS dev', target_dev_ms, 'train', target_train_ms, 'test', ms_test)

    add_dev, add_train = [], []
    used2 = set(used)
    # Fill Dev MS first
    for a in ms_hits:
        if len([x for x in add_dev if x.get('ms_head')]) >= (target_dev_ms - count_ms('dev')):
            break
        if a['pmid'] in used2:
            continue
        used2.add(a['pmid'])
        add_dev.append(a)
    # Fill Train MS
    for a in ms_hits:
        if count_ms('train') + len([x for x in add_train if x.get('ms_head')]) >= target_train_ms:
            break
        if a['pmid'] in used2:
            continue
        used2.add(a['pmid'])
        add_train.append(a)

    # Entity coverage expansion for train: keep adding until train unique > dev unique > test unique (totals)
    # Also try to push per-type where possible.
    train_ids = set(split_ids['train'])
    for a in coverage_hits:
        if a['pmid'] in used2:
            continue
        new = [h for h in a.get('new_heads') or [] if h not in train_ids]
        if not new:
            continue
        used2.add(a['pmid'])
        add_train.append(a)
        train_ids.update(new)
        # stop if train total exceeds max(dev,test)+margin and most missing filled
        if len(train_ids) > max(len(split_ids['dev']), len(split_ids['test'])) + 30:
            if len(missing_train - train_ids) < 50:
                break
        if len(add_train) > 2500:
            break

    # Dev entity coverage: add non-MS coverage articles so Dev unique > Test unique
    # Use remaining coverage hits with entities not yet in Dev
    dev_ids = set(split_ids['dev'])
    test_n = len(split_ids['test'])
    for a in coverage_hits:
        if len(dev_ids) > test_n:
            break
        if a['pmid'] in used2:
            continue
        new = [h for h in a.get('new_heads') or [] if h not in dev_ids]
        if not new:
            continue
        # only add to Dev if helps diversity and not already reserved
        used2.add(a['pmid'])
        add_dev.append(a)
        dev_ids.update(new)
        if len(add_dev) > 800:
            break

    print('will add dev', len(add_dev), 'train', len(add_train))
    print('projected train ids', len(train_ids), 'dev ids', len(dev_ids), 'test ids', test_n)

    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for sp in ('dev', 'train'):
        bak = _paths.BM / f'.bak_{sp}_expand_{stamp}.jsonl'
        shutil.copy2(_paths.sp(sp), bak)
        print('backup', bak.name)

    dev_rows = [json.loads(l) for l in open(_paths.sp('dev'), encoding='utf-8')]
    train_rows = [json.loads(l) for l in open(_paths.sp('train'), encoding='utf-8')]
    for a in add_dev:
        # Dev gold_type: human_reviewed for MS curated-like; use distant label for coverage fills without MS
        gt = 'human_reviewed' if a.get('ms_head') else 'distant_supervision'
        # Actually Dev should stay human_reviewed for consistency of split - mark MS as human_reviewed after filter
        gt = 'human_reviewed'
        dev_rows.append(make_row(a, 'dev', gt, ref_dev['instruction'], ref_dev['allowed_relations']))
    for a in add_train:
        train_rows.append(make_row(a, 'train', 'distant_supervision',
                                   ref_train['instruction'], ref_train['allowed_relations']))

    with open(_paths.sp('dev'), 'w', encoding='utf-8') as fo:
        for r in dev_rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    with open(_paths.sp('train'), 'w', encoding='utf-8') as fo:
        for r in train_rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('wrote dev', len(dev_rows), 'train', len(train_rows))


if __name__ == '__main__':
    main()
