# -*- coding: utf-8 -*-
"""Document-level coverage extraction (CDR-style).

For PubMed rows tagged with query_entity in the missing-ID set, pair that
intervention head with any same-abstract effect sentence that mentions an
outcome + relation cue. Evidence is the effect sentence; head need not
co-occur in that sentence.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import _schema
import build_train_distant as btd

CORPORA = [
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing_train.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_ms_entities.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_auditory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_olfactory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad.jsonl',
    _paths.SOURCE / 'literature.jsonl',
]
IDS_FILE = _paths.SOURCE / 'pubmed' / '_missing_coverage_ids.json'
OUT = _paths.RUNS / '_coverage_open_candidates.jsonl'

KEEP_TYPES = {'visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multiple_senses'}
TAIL_RE = re.compile(
    r'\b((?:anxiety|stress|pain|fatigue|depression|depressive symptoms|mood|sleep quality|'
    r'sleep|insomnia|nausea|cortisol|heart rate|blood pressure|attention|alertness|'
    r'agitation|distress|well-being|quality of life|cognitive function|cognition|'
    r'tension|anger|comfort|relaxation|satisfaction)\b)',
    re.I)
CUE_MAP = [
    (re.compile(r'\b(reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|attenuat\w+|lower(?:s|ed|ing)?)\b', re.I), 'reduces'),
    (re.compile(r'\b(alleviat\w+|reliev\w+|mitigat\w+)\b', re.I), 'alleviates'),
    (re.compile(r'\b(improv\w+|beneficial|ameliorat\w+)\b', re.I), 'improves'),
    (re.compile(r'\b(enhanc\w+)\b', re.I), 'enhances'),
    (re.compile(r'\b(promot\w+)\b', re.I), 'promotes'),
]
NEG = re.compile(r'\b(no significant|not significant|did not|nonsignificant|ineffective|without effect)\b', re.I)
ANIMAL_HARD = re.compile(r'\b(rats?|mice|mouse|murine|rodent|in\s+vitro|zebrafish)\b', re.I)


def main():
    unc = json.loads(IDS_FILE.read_text(encoding='utf-8'))
    target = set(unc.get('dev') or []) | set(unc.get('train') or [])
    id_type = {e['id']: e['type'] for e in _schema.entities()}
    text2id = _schema.text2id()
    # canonical surface for each id
    id_text = {}
    for e in _schema.entities():
        if e['id'] in target and e.get('type') in KEEP_TYPES:
            t = (e.get('text') or '').strip()
            if e['id'] not in id_text or len(t) < len(id_text[e['id']]):
                id_text[e['id']] = t

    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))

    rows = []
    seen = set()
    hit_ids = set()
    for path in CORPORA:
        if not path.exists():
            continue
        print('scan', path.name)
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in used or pmid in seen:
                continue
            seen.add(pmid)
            title = art.get('title') or ''
            abstract = art.get('abstract') or ''
            if len(abstract) < 80:
                continue
            blob = title + ' ' + abstract
            if ANIMAL_HARD.search(blob):
                continue
            # heads from query_entity tags intersecting target
            qids = [x.strip() for x in str(art.get('query_entity') or '').split(',') if x.strip()]
            heads = [h for h in qids if h in target and id_type.get(h) in KEEP_TYPES]
            # also alias present in abstract
            blob_l = blob.lower()
            for hid, txt in id_text.items():
                if hid in target and txt and txt.lower() in blob_l and hid not in heads:
                    heads.append(hid)
            if not heads:
                continue
            # find effect sentences
            effect = []
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
                tail = btd.norm(m.group(1)).lower()
                tid = text2id.get(tail) or text2id.get(tail.split()[0])
                if not tid or id_type.get(tid) != 'outcome':
                    # map common outcomes directly
                    tid = {
                        'anxiety': 'anxiety', 'stress': 'stress', 'pain': 'pain',
                        'fatigue': 'fatigue', 'depression': 'depression', 'mood': 'mood',
                        'sleep': 'sleep', 'insomnia': 'insomnia', 'nausea': 'nausea',
                        'cortisol': 'cortisol', 'attention': 'attention',
                        'alertness': 'alertness', 'agitation': 'agitation',
                        'distress': 'distress', 'tension': 'tension',
                        'relaxation': 'relaxation', 'comfort': 'comfort',
                        'cognition': 'cognition',
                    }.get(tail.split()[0])
                    if tid and tid not in id_type:
                        # skip unknown
                        if tid not in text2id.values() and tid not in id_type:
                            # allow if exists as id
                            if tid not in {e['id'] for e in _schema.entities()}:
                                continue
                    if not tid or id_type.get(tid) not in (None, 'outcome') and id_type.get(tid) != 'outcome':
                        if id_type.get(tid) != 'outcome':
                            continue
                if id_type.get(tid) != 'outcome':
                    continue
                rid = rel
                if rid in ('improves', 'enhances', 'promotes') and re.search(
                        r'\b(anxiety|pain|stress|fatigue|depression|nausea|distress|agitation|tension)\b', sent, re.I):
                    rid = 'reduces'
                effect.append((rid, tid, sent[:300]))
            if not effect:
                continue
            # one triple per head (best first effect)
            gold = []
            for hid in heads[:3]:
                ht = id_type[hid]
                rid, tid, ev = effect[0]
                senses = ['multiple_senses'] if ht == 'multiple_senses' else [ht]
                gold.append({
                    'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                    'evidence': ev, 'evidence_level': 'C', 'senses': senses,
                })
                hit_ids.add(hid)
            rows.append({
                'pmid': pmid, 'title': title, 'abstract': abstract,
                'year': str(art.get('year') or '')[:4],
                'pubtypes': art.get('pubtypes') or [],
                'gold': gold, 'gold_n': len(gold),
                '_heads': [g['head_id'] for g in gold],
                'ms_head': any(g['senses'] == ['multiple_senses'] for g in gold),
            })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('wrote', len(rows), 'covering', len(hit_ids), '/', len(target), '->', OUT)
    still = sorted(target - hit_ids)
    print('still', len(still))
    (_paths.SOURCE / 'pubmed' / '_missing_coverage_still.json').write_text(
        json.dumps(still, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
