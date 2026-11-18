# -*- coding: utf-8 -*-
"""Open extraction for multisensory Table-1 top-up using lexicon MS phrases."""
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
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad2.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_ms_entities.jsonl',
    _paths.SOURCE / 'pubmed' / 'entity_retrieval_missing_train.jsonl',
    _paths.SOURCE / 'literature.jsonl',
]
OUT = _paths.RUNS / '_ms_open_candidates.jsonl'

TAIL_RE = re.compile(
    r'\b((?:anxiety|stress|pain|fatigue|depression|depressive symptoms|mood|sleep quality|'
    r'sleep|insomnia|nausea|cortisol|heart rate|blood pressure|attention|alertness|'
    r'agitation|distress|well-being|quality of life|cognitive function|cognition|'
    r'blood pressure|systolic blood pressure|diastolic blood pressure)\b'
    r'(?:\s+[A-Za-z]{2,14}){0,2})',
    re.I)
CUE_MAP = [
    (re.compile(r'\b(reduc(?:e|es|ed|ing)|decreas(?:e|es|ed|ing)|attenuat\w+|lower(?:s|ed|ing)?)\b', re.I), 'reduces'),
    (re.compile(r'\b(alleviat\w+|reliev\w+)\b', re.I), 'alleviates'),
    (re.compile(r'\b(improv\w+|beneficial)\b', re.I), 'improves'),
    (re.compile(r'\b(enhanc\w+)\b', re.I), 'enhances'),
    (re.compile(r'\b(promot\w+)\b', re.I), 'promotes'),
]
NEG = re.compile(r'\b(no significant|not significant|did not|nonsignificant|ineffective)\b', re.I)
# Broader multi-sensory phrase patterns when lexicon miss
EXTRA_PHRASES = [
    ('aromatherapy massage', 'aromatherapy_massage'),
    ('aroma massage', 'aromatherapy_massage'),
    ('forest bathing', 'forest_therapy'),
    ('forest therapy', 'forest_therapy'),
    ('shinrin-yoku', 'forest_therapy'),
    ('green exercise', 'green_exercise'),
    ('guided imagery and music', 'guided_imagery_and_music_gim'),
    ('music and imagery', 'group_music_and_imagery'),
    ('audio-visual relaxation', 'audio_visual_relaxation_training'),
    ('audiovisual distraction', 'aromatherapy_mixed_with_audiovisual_distraction'),
    ('multisensory virtual reality', 'multisensory_virtual_reality'),
    ('multi-sensory stimulation', 'multisensory_virtual_reality'),
    ('multisensory stimulation', 'multisensory_virtual_reality'),
    ('nature walk', 'nature_walk'),
    ('virtual reality', 'virtual_reality_games'),
    ('VR nature', 'virtual_reality_headset_simulating_a_nature_environment'),
    ('healing touch', 'healing_touch_with_guided_imagery'),
    ('lavender oil massage', 'aromatherapy_massage_with_lavender_oil'),
    ('massage with lavender', 'aromatherapy_massage_with_lavender_oil'),
    ('foot bath', 'aroma_massage_and_foot_bath'),
    ('footbath', 'aroma_massage_and_foot_bath'),
    ('PMR and music', 'pmr_and_music_therapy'),
    ('progressive muscle relaxation and music', 'pmr_and_music_therapy'),
    ('music therapy combined', 'five_element_music_therapy_combined_with_baduanjin_qigong'),
    ('touch-music-aroma', 'touch_music_aroma_therapy'),
    ('nature sounds', 'nature_sounds'),
]


def build_phrase_map():
    pairs = []
    id_type = {e['id']: e['type'] for e in _schema.entities()}
    for e in _schema.entities():
        if e.get('type') != 'multiple_senses':
            continue
        t = (e.get('text') or '').strip()
        if len(t) >= 4:
            pairs.append((t.lower(), e['id']))
    for phrase, hid in EXTRA_PHRASES:
        if hid in id_type:
            pairs.append((phrase.lower(), hid))
    # longest first
    pairs.sort(key=lambda x: -len(x[0]))
    # dedupe phrases
    seen = set()
    out = []
    for p, hid in pairs:
        if p in seen:
            continue
        seen.add(p)
        out.append((p, hid))
    return out, id_type


def find_head(sent_l, phrases):
    for phrase, hid in phrases:
        if phrase in sent_l:
            return hid, phrase
    return None, None


def find_tail(sent, id_type, text2id):
    for m in TAIL_RE.finditer(sent):
        t = btd.norm(m.group(1)).strip(' .,;:')
        if len(t) < 3:
            continue
        tid = text2id.get(t.lower()) or text2id.get(t)
        if tid and id_type.get(tid) == 'outcome':
            return tid, t
        # common short outcomes
        short = t.lower().split()[0]
        tid2 = text2id.get(short)
        if tid2 and id_type.get(tid2) == 'outcome':
            return tid2, short
    return None, None


def main():
    used = set()
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(line)['pmid']))
    phrases, id_type = build_phrase_map()
    text2id = _schema.text2id()
    rows = []
    seen_pmid = set()
    for path in CORPORA:
        if not path.exists():
            continue
        print('scan', path.name)
        for line in open(path, encoding='utf-8'):
            art = json.loads(line)
            pmid = str(art.get('pmid') or '')
            if not pmid or pmid in used or pmid in seen_pmid:
                continue
            seen_pmid.add(pmid)
            title = art.get('title') or ''
            abstract = art.get('abstract') or ''
            if len(abstract) < 120:
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
                hid, hphrase = find_head(sent.lower(), phrases)
                if not hid:
                    continue
                tid, ttext = find_tail(sent, id_type, text2id)
                if not tid:
                    continue
                # polarity fix
                rid = rel
                if rid in ('improves', 'enhances', 'promotes') and re.search(
                        r'\b(anxiety|pain|stress|fatigue|depression|nausea|distress|agitation)\b', ttext, re.I):
                    rid = 'reduces'
                if rid in ('reduces', 'alleviates') and re.search(
                        r'\b(well-being|quality of life|attention|alertness|cognition)\b', ttext, re.I):
                    continue
                gold.append({
                    'head_id': hid,
                    'relation_id': rid,
                    'tail_id': tid,
                    'evidence': sent[:300],
                    'evidence_level': 'C',
                    'senses': ['multiple_senses'],
                    'cue': hphrase,
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
                'pmid': pmid,
                'title': title,
                'abstract': abstract,
                'year': str(art.get('year') or '')[:4],
                'pubtypes': pts if isinstance(pts, list) else [],
                'gold': uniq[:3],
                'gold_n': min(len(uniq), 3),
                'ms_head': True,
            })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('wrote', len(rows), '->', OUT)


if __name__ == '__main__':
    main()
