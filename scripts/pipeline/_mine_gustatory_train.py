# -*- coding: utf-8 -*-
"""Mine unused literature.jsonl rows for additional gustatory train articles."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import build_train_distant as btd

LIT = _paths.SOURCE / 'literature.jsonl'
OUT_APPEND = _paths.RUNS / '_gustatory_train_mined.jsonl'

HEADS = {
    'carbohydrate mouth rinse': 'carbohydrate_mouth_rinse',
    'cho mouth rinse': 'carbohydrate_mouth_rinse',
    'menthol mouth rinse': 'l_menthol_mouth_rinse',
    'l-menthol mouth rinse': 'l_menthol_mouth_rinse',
    'sucrose': 'sucrose_stimulus',
    '24% sucrose': '24_sucrose_solution',
    '24% sucrose solution': '24_sucrose_solution',
    'green tea': 'green_tea_powder',
    'matcha': 'matcha_tea',
    'black tea': 'black_tea',
}
TAILS = {
    'pain': 'pain', 'crying': 'crying', 'anxiety': 'anxiety', 'stress': 'stress',
    'fatigue': 'fatigue', 'performance': 'performance', 'endurance': 'endurance_performance',
    'endurance performance': 'endurance_performance', 'sleep quality': 'sleep_quality',
    'mood': 'mood', 'distress': 'distress', 'alertness': 'alertness',
}
CUE = [
    (re.compile(r'\b(reduc(?:e|es|ed|ing)|decreas\w+|lower(?:s|ed|ing)?)\b', re.I), 'reduces'),
    (re.compile(r'\b(alleviat\w+|reliev\w+)\b', re.I), 'alleviates'),
    (re.compile(r'\b(improv\w+)\b', re.I), 'improves'),
    (re.compile(r'\b(enhanc\w+)\b', re.I), 'enhances'),
]
BAD = re.compile(r'\b(no significant|did not|does not|ineffective|review|meta-?analys|protocol)\b', re.I)


def main():
    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))
    ref = json.loads(open(_paths.sp('train'), encoding='utf-8').readline())
    rows = []
    for line in open(LIT, encoding='utf-8'):
        art = json.loads(line)
        pmid = str(art.get('pmid') or '')
        if not pmid or pmid in used:
            continue
        title = art.get('title') or ''
        abstract = art.get('abstract') or ''
        if len(abstract) < 150:
            continue
        blob = (title + ' ' + abstract).lower()
        if not any(h in blob for h in HEADS):
            continue
        if btd.NEG_TI.search(title) or btd.ANIMAL.search(title + ' ' + abstract):
            continue
        gold = []
        for sent in [title] + btd.SENT_SPLIT.split(abstract):
            sent = btd.norm(sent)
            if len(sent) < 25 or BAD.search(sent):
                continue
            rid = None
            for cre, r in CUE:
                if cre.search(sent):
                    rid = r
                    break
            if not rid:
                continue
            sl = sent.lower()
            head = None
            hid = None
            for h, i in sorted(HEADS.items(), key=lambda x: -len(x[0])):
                if h in sl:
                    head, hid = h, i
                    break
            if not head:
                continue
            tail = None
            tid = None
            for t, i in sorted(TAILS.items(), key=lambda x: -len(x[0])):
                if t in sl:
                    tail, tid = t, i
                    break
            if not tail:
                continue
            if rid in ('improves', 'enhances') and tid in ('pain', 'anxiety', 'stress', 'fatigue', 'crying', 'distress'):
                rid = 'reduces'
            if rid in ('reduces', 'alleviates') and tid in ('performance', 'endurance_performance', 'alertness', 'sleep_quality', 'mood'):
                continue
            gold.append({
                'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                'evidence': sent[:300], 'evidence_level': 'C', 'senses': ['gustatory'],
            })
        seen = set()
        uniq = []
        for g in gold:
            k = (g['head_id'], g['relation_id'], g['tail_id'])
            if k in seen:
                continue
            seen.add(k)
            uniq.append(g)
        if not uniq:
            continue
        rows.append({
            'task_id': f"ds_{pmid}",
            'pmid': pmid,
            'split': 'train',
            'gold_type': 'distant_supervision',
            'input': {
                'title': title,
                'abstract': abstract,
                'year': str(art.get('year') or '')[:4],
                'pubtypes': art.get('pubtypes') if isinstance(art.get('pubtypes'), list) else [],
            },
            'instruction': ref['instruction'],
            'allowed_relations': ref['allowed_relations'],
            'channels': ['gustatory'],
            'annotation_scheme': 'v3_open_entities',
            'verdict': 'keep',
            'gold': uniq[:3],
            'gold_n': min(len(uniq), 3),
        })
        if len(rows) >= 80:
            break
    with open(OUT_APPEND, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    # append to train
    with open(_paths.sp('train'), 'a', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('appended train gustatory', len(rows), 'triples', sum(r['gold_n'] for r in rows))
    print('wrote', OUT_APPEND)


if __name__ == '__main__':
    main()
