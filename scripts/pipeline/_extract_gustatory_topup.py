# -*- coding: utf-8 -*-
"""Extract same-sentence distant-supervision triples from gustatory top-up PubMed fetch."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import _schema
import build_train_distant as btd

CORPUS = _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_topup.jsonl'
OUT = _paths.RUNS / '_gustatory_topup_candidates.jsonl'
KEEP_REL = {
    'reduces', 'alleviates', 'lowers', 'improves', 'promotes', 'enhances', 'strengthens',
}


def main():
    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))

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

    rows_out = []
    n_papers = 0
    for line in open(CORPUS, encoding='utf-8'):
        art = json.loads(line)
        pmid = str(art.get('pmid') or '')
        if not pmid or pmid in used:
            continue
        title = art.get('title') or ''
        abstract = art.get('abstract') or ''
        if len(abstract) < 120:
            continue
        if btd.NEG_TI.search(title) or btd.ANIMAL.search(title + ' ' + abstract):
            continue
        pts = art.get('pubtypes') or []
        if any(btd.BAD_PUBTYPE.match(p or '') for p in pts):
            continue
        n_papers += 1
        triples = []
        for sent in [title] + btd.SENT_SPLIT.split(abstract):
            sent = btd.norm(sent)
            if len(sent) < 20 or len(sent) > 500:
                continue
            for hid, rid, tid, cue in btd.extract_intra(
                    sent, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                if type_of.get(hid) != 'gustatory':
                    continue
                if rid not in KEEP_REL:
                    continue
                if type_of.get(tid) != 'outcome':
                    continue
                triples.append({
                    'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                    'evidence': sent[:300], 'evidence_level': 'C',
                    'senses': ['gustatory'], 'cue': cue, 'tier': 'intra',
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
            continue
        rows_out.append({
            'pmid': pmid,
            'title': title,
            'abstract': abstract,
            'year': art.get('year') or '',
            'pubtypes': pts,
            'journal': art.get('journal') or '',
            'gold': uniq[:5],
            'gold_n': min(len(uniq), 5),
            'query_entity': art.get('query_entity'),
            'query_text': art.get('query_text'),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        for r in rows_out:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    heads = Counter(t['head_id'] for r in rows_out for t in r['gold'])
    rels = Counter(t['relation_id'] for r in rows_out for t in r['gold'])
    print(f'scanned papers (unused): {n_papers}')
    print(f'articles with gustatory triples: {len(rows_out)}')
    print(f'triples: {sum(r["gold_n"] for r in rows_out)}')
    print('top heads', heads.most_common(10))
    print('rels', dict(rels))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
