# -*- coding: utf-8 -*-
"""Open-ish extraction for gustatory top-up: taste heads + outcome tails + effect cues."""
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import _schema
import build_train_distant as btd

CORPORA = [
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_topup.jsonl',
]
OUT = _paths.RUNS / '_gustatory_open_candidates.jsonl'

HEAD_RE = re.compile(
    r'\b((?:carbohydrate|CHO|menthol|L-menthol|sucrose|glucose|fructose|sweet|bitter|umami|'
    r'salty|sour|stevia|green tea|black tea|matcha|herbal tea|rose tea|chamomile tea|'
    r'peppermint tea|monosodium glutamate|MSG|mouth rinse|oral rinse|taste stimulus|'
    r'taste stimulation|gustatory stimulation|savory preload|sugary drink|wagyu|'
    r'chocolate|cocoa|coffee|caffeine[- ]free coffee)\b'
    r'(?:[-\s]+[A-Za-z%]{2,18}){0,4})',
    re.I)
TAIL_RE = re.compile(
    r'\b((?:anxiety|stress|pain|fatigue|depression|depressive symptoms|mood|sleep quality|'
    r'sleep|insomnia|nausea|cortisol|heart rate|blood pressure|attention|alertness|'
    r'endurance|performance|power output|rating of perceived exertion|RPE|'
    r'crying|distress|agitation|well-being|quality of life|appetite|craving)\b'
    r'(?:\s+[A-Za-z]{2,14}){0,2})',
    re.I)
CUE_MAP = [
    (re.compile(r'\b(reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|attenuat\w+|lower(?:s|ed|ing)?)\b', re.I), 'reduces'),
    (re.compile(r'\b(alleviat\w+|reliev\w+)\b', re.I), 'alleviates'),
    (re.compile(r'\b(improv\w+|beneficial)\b', re.I), 'improves'),
    (re.compile(r'\b(enhanc\w+|increas\w+|boost\w+)\b', re.I), 'enhances'),
    (re.compile(r'\b(promot\w+)\b', re.I), 'promotes'),
]
NEG_TI = btd.NEG_TI
ANIMAL = btd.ANIMAL
DRUG = re.compile(
    r'\b(capsule|tablet|injection|infusion|intravenous|i\.v\.|pharmacolog|antidepressant|'
    r'analgesic drug|chemotherapy drug)\b', re.I)
STOP_HEAD = re.compile(r'^(the|a|an|this|these|those|our|their)\s+', re.I)


def slug(s):
    s = unicodedata.normalize('NFKD', s or '')
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')[:80]


def norm(s):
    return btd.norm(s)


def main():
    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))
    text2id = _schema.text2id()
    id_type = {e['id']: e['type'] for e in _schema.entities()}

    rows = []
    seen_pmid = set()
    for path in CORPORA:
        if not path.exists():
            continue
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in used or pmid in seen_pmid:
                continue
            seen_pmid.add(pmid)
            title = art.get('title') or ''
            abstract = art.get('abstract') or ''
            if len(abstract) < 150:
                continue
            blob = title + ' ' + abstract
            if NEG_TI.search(title) or ANIMAL.search(blob) or DRUG.search(title):
                continue
            pts = art.get('pubtypes') or []
            if any(btd.BAD_PUBTYPE.match(p or '') for p in pts):
                continue
            gold = []
            for sent in [title] + btd.SENT_SPLIT.split(abstract):
                sent = norm(sent)
                if len(sent) < 25 or len(sent) > 420:
                    continue
                if re.search(r'\b(no significant|not significant|did not|nonsignificant)\b', sent, re.I):
                    continue
                rel = None
                for cre, rid in CUE_MAP:
                    if cre.search(sent):
                        rel = rid
                        break
                if not rel:
                    continue
                heads = []
                for m in HEAD_RE.finditer(sent):
                    h = STOP_HEAD.sub('', norm(m.group(1))).strip(' .,;:')
                    if 3 <= len(h) <= 60:
                        heads.append(h)
                tails = []
                for m in TAIL_RE.finditer(sent):
                    t = STOP_HEAD.sub('', norm(m.group(1))).strip(' .,;:')
                    if 3 <= len(t) <= 40:
                        tails.append(t)
                if not heads or not tails:
                    continue
                # require head before cue-ish region roughly: keep first head and first compatible tail
                head = heads[0]
                # prefer outcome-like short tails
                tail = None
                for t in tails:
                    if t.lower() not in head.lower():
                        tail = t
                        break
                if not tail:
                    continue
                # direction normalize
                rid = rel
                if rid in ('improves', 'enhances', 'promotes') and re.search(
                        r'\b(anxiety|pain|stress|fatigue|depression|nausea|distress|crying)\b', tail, re.I):
                    rid = 'reduces'
                if rid in ('reduces', 'alleviates', 'lowers') and re.search(
                        r'\b(well-being|quality of life|performance|alertness|endurance|attention)\b', tail, re.I):
                    continue
                hid = text2id.get(head.lower()) or text2id.get(head) or slug(head)
                tid = text2id.get(tail.lower()) or text2id.get(tail) or slug(tail)
                # if known id but wrong type, skip head
                if hid in id_type and id_type[hid] not in ('gustatory', 'multiple_senses') and id_type[hid] != 'outcome':
                    # allow unknown new heads; if known non-gustatory intervention skip
                    if id_type[hid] in ('visual', 'auditory', 'olfactory', 'tactile', 'perceptual', 'context'):
                        continue
                if tid in id_type and id_type[tid] not in ('outcome',):
                    # force outcome-only tails when known
                    if id_type[tid] != 'outcome':
                        continue
                gold.append({
                    'head_id': hid if hid in id_type or hid == slug(head) else slug(head),
                    'head_text': head,
                    'relation_id': rid,
                    'tail_id': tid if tid in id_type else slug(tail),
                    'tail_text': tail,
                    'evidence': sent[:300],
                    'evidence_level': 'C',
                    'senses': ['gustatory'],
                    'new_head': hid not in id_type,
                    'new_tail': tid not in id_type,
                })
            # dedupe
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
                'pmid': pmid,
                'title': title,
                'abstract': abstract,
                'year': art.get('year') or '',
                'pubtypes': pts,
                'journal': art.get('journal') or '',
                'gold': uniq[:4],
                'gold_n': min(len(uniq), 4),
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('candidates', len(rows), 'triples', sum(r['gold_n'] for r in rows))
    print('new heads', sum(1 for r in rows for g in r['gold'] if g.get('new_head')))
    print('top heads', Counter(g['head_text'].lower() for r in rows for g in r['gold']).most_common(15))
    print('wrote', OUT)


if __name__ == '__main__':
    main()
