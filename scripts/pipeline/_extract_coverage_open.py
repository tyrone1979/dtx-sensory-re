# -*- coding: utf-8 -*-
"""Open extraction targeting missing intervention entity IDs for Table-2 coverage."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'pipeline'))
import _paths
import _schema
import build_train_distant as btd

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
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing_train.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_auditory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_olfactory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_ms_entities.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_coverage_fetch.jsonl',
]
IDS_FILE = _paths.SOURCE / 'pubmed' / '_missing_coverage_ids.json'
OUT = _paths.RUNS / '_coverage_open_candidates.jsonl'

KEEP_TYPES = {'visual', 'tactile', 'auditory', 'olfactory', 'gustatory', 'perceptual', 'multiple_senses'}
TAIL_RE = re.compile(
    r'\b((?:anxiety|stress|pain|fatigue|depression|depressive symptoms|mood|sleep quality|'
    r'sleep|insomnia|nausea|cortisol|heart rate|blood pressure|attention|alertness|'
    r'agitation|distress|well-being|quality of life|cognitive function|cognition|'
    r'systolic blood pressure|diastolic blood pressure|fatigue|tension|anger)\b'
    r'(?:\s+[A-Za-z]{2,14}){0,2})',
    re.I)
CUE_MAP = [
    (re.compile(r'\b(reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|attenuat\w+|lower(?:s|ed|ing)?|declin\w+)\b', re.I), 'reduces'),
    (re.compile(r'\b(alleviat\w+|reliev\w+|mitigat\w+|lessen\w+)\b', re.I), 'alleviates'),
    (re.compile(r'\b(improv\w+|beneficial|ameliorat\w+)\b', re.I), 'improves'),
    (re.compile(r'\b(enhanc\w+|increas\w+|boost\w+)\b', re.I), 'enhances'),
    (re.compile(r'\b(promot\w+)\b', re.I), 'promotes'),
    (re.compile(r'\b(significant(?:ly)?\s+(?:reduc|decreas|improv|enhanc)\w+)\b', re.I), 'reduces'),
    (re.compile(r'\b((?:was|were|is|are)\s+associated\s+with)\b', re.I), 'improves'),
    (re.compile(r'\b(resulted\s+in|led\s+to|contributed\s+to)\b', re.I), 'improves'),
]
NEG = re.compile(r'\b(no significant|not significant|did not|nonsignificant|ineffective)\b', re.I)


def build_alias_index(target_ids):
    """Longest-first list of (alias_lower, head_id, type)."""
    id_type = {e['id']: e['type'] for e in _schema.entities()}
    pairs = []
    for e in _schema.entities():
        if e['id'] not in target_ids:
            continue
        if e.get('type') not in KEEP_TYPES:
            continue
        t = (e.get('text') or '').strip()
        if len(t) < 3:
            continue
        pairs.append((t.lower(), e['id'], e['type']))
    pairs.sort(key=lambda x: -len(x[0]))
    return pairs, id_type


def find_head(sent_l, aliases):
    for alias, hid, ht in aliases:
        if alias in sent_l:
            return hid, ht, alias
    return None, None, None


def find_tail(sent, id_type, text2id):
    for m in TAIL_RE.finditer(sent):
        t = btd.norm(m.group(1)).strip(' .,;:')
        if len(t) < 3:
            continue
        tid = text2id.get(t.lower()) or text2id.get(t)
        if tid and id_type.get(tid) == 'outcome':
            return tid
        short = t.lower().split()[0]
        tid2 = text2id.get(short)
        if tid2 and id_type.get(tid2) == 'outcome':
            return tid2
    return None


def main():
    if not IDS_FILE.exists():
        raise SystemExit(f'missing {IDS_FILE}')
    unc = json.loads(IDS_FILE.read_text(encoding='utf-8'))
    target = set(unc.get('dev') or []) | set(unc.get('train') or [])
    print('target missing ids', len(target))
    aliases, id_type = build_alias_index(target)
    print('aliases', len(aliases))
    text2id = _schema.text2id()

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
            if len(abstract) < 100:
                continue
            blob = title + ' ' + abstract
            if btd.NEG_TI.search(title) or btd.ANIMAL.search(blob):
                continue
            pts = art.get('pubtypes') or []
            if any(btd.BAD_PUBTYPE.match(p or '') for p in pts):
                continue
            gold = []
            for sent in [title] + btd.SENT_SPLIT.split(abstract):
                sent = btd.norm(sent)
                if len(sent) < 20 or len(sent) > 450 or NEG.search(sent):
                    continue
                rel = None
                for cre, rid in CUE_MAP:
                    if cre.search(sent):
                        rel = rid
                        break
                if not rel:
                    continue
                hid, ht, _ = find_head(sent.lower(), aliases)
                if not hid:
                    continue
                tid = find_tail(sent, id_type, text2id)
                if not tid:
                    continue
                rid = rel
                if rid in ('improves', 'enhances', 'promotes') and re.search(
                        r'\b(anxiety|pain|stress|fatigue|depression|nausea|distress|agitation)\b', sent, re.I):
                    rid = 'reduces'
                senses = ['multiple_senses'] if ht == 'multiple_senses' else [ht]
                gold.append({
                    'head_id': hid, 'relation_id': rid, 'tail_id': tid,
                    'evidence': sent[:300], 'evidence_level': 'C', 'senses': senses,
                })
                hit_ids.add(hid)
            # dedupe
            seen_g = set()
            uniq = []
            for g in gold:
                k = (g['head_id'], g['relation_id'], g['tail_id'])
                if k in seen_g:
                    continue
                seen_g.add(k)
                uniq.append(g)
            if not uniq:
                continue
            rows.append({
                'pmid': pmid, 'title': title, 'abstract': abstract,
                'year': str(art.get('year') or '')[:4],
                'pubtypes': pts if isinstance(pts, list) else [],
                'gold': uniq[:4], 'gold_n': min(len(uniq), 4),
                '_heads': sorted({g['head_id'] for g in uniq}),
                'ms_head': any(g['senses'] == ['multiple_senses'] for g in uniq),
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('wrote', len(rows), 'candidates covering', len(hit_ids), '/', len(target), '->', OUT)
    still = sorted(target - hit_ids)
    Path(str(IDS_FILE).replace('.json', '_still.json')).write_text(
        json.dumps(still, ensure_ascii=False, indent=2), encoding='utf-8')
    print('still uncovered after open extract', len(still))


if __name__ == '__main__':
    main()
