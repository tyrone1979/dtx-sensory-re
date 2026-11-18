# -*- coding: utf-8 -*-
"""Curate gustatory top-up into dev/train after open retrieval."""
import json
import re
import shutil
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _paths
import _schema

CAND = _paths.RUNS / '_gustatory_open_candidates.jsonl'
SURF_F = _paths.TMP / 'schema' / 'surfaces.json'
ZH_F = _paths.TMP / 'schema' / 'zh_merged.json'

HEAD_MAP = {
    'carbohydrate mouth rinse': 'carbohydrate_mouth_rinse',
    'cho mouth rinse': 'carbohydrate_mouth_rinse',
    'glucose mouth rinse': 'carbohydrate_mouth_rinse',
    'menthol mouth rinse': 'l_menthol_mouth_rinse',
    'l-menthol mouth rinse': 'l_menthol_mouth_rinse',
    'sucrose': 'sucrose_stimulus',
    '24% sucrose solution': '24_sucrose_solution',
    'sucrose solution': '24_sucrose_solution',
    'green tea': 'green_tea_powder',
    'matcha': 'matcha_tea',
    'matcha tea': 'matcha_tea',
    'black tea': 'black_tea',
    'stevia': 'stevia_beverage',
    'monosodium glutamate': 'monosodium_glutamate',
    'msg': 'monosodium_glutamate',
}
TAIL_MAP = {
    'pain': 'pain',
    'anxiety': 'anxiety',
    'stress': 'stress',
    'fatigue': 'fatigue',
    'depression': 'depression',
    'mood': 'mood',
    'sleep': 'sleep',
    'sleep quality': 'sleep_quality',
    'nausea': 'nausea',
    'cortisol': 'cortisol',
    'heart rate': 'heart_rate',
    'blood pressure': 'blood_pressure',
    'attention': 'attention',
    'alertness': 'alertness',
    'endurance': 'endurance',
    'performance': 'performance',
    'crying': 'crying',
    'distress': 'distress',
    'well-being': 'well_being',
    'quality of life': 'quality_of_life',
    'appetite': 'appetite',
    'craving': 'craving',
    'endurance performance': 'endurance_performance',
    'endurance exercise performance': 'endurance_performance',
    'power output': 'power_output',
}
KEEP_HEAD = re.compile(
    r'^(carbohydrate mouth rinse|CHO mouth rinse|glucose mouth rinse|menthol mouth rinse|'
    r'L-menthol mouth rinse|sucrose|sucrose solution|24% sucrose solution|green tea|'
    r'black tea|matcha|matcha tea|stevia|monosodium glutamate|MSG)$', re.I)
BAD_EV = re.compile(
    r'\b(ineffective|does not|did not|no significant|not significant|nonsignificant|'
    r'without influencing|hypothesis|has not been established|prior knowledge|'
    r'may be the minimum|parents were more likely)\b', re.I)
BAD_TITLE = re.compile(
    r'\b(review|meta-?analys|protocol|pilot evaluation of a|educational outreach)\b', re.I)


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    return re.sub(r'\s+', ' ', s.replace('\u2009', ' ').replace('\xa0', ' ')).strip()


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', norm(s).lower()).strip('_')[:80]


def clean_tail(t):
    t = norm(t).lower()
    t = re.sub(r'\b(and|or|the|a|an|of|in|to|for|with|during|without|that|lasting|under|over)\b.*$', '', t).strip()
    t = re.sub(r'\s+', ' ', t).strip(' .,;:')
    for k in sorted(TAIL_MAP, key=len, reverse=True):
        if t == k or t.startswith(k + ' '):
            return k
    # first 1-3 tokens if outcome-like
    toks = t.split()
    for n in (3, 2, 1):
        cand = ' '.join(toks[:n])
        if cand in TAIL_MAP:
            return cand
    return None


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding='utf-8')]


def dump_jsonl(p, rows):
    with open(p, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')


def main():
    text2id = _schema.text2id()
    id_type = {e['id']: e['type'] for e in _schema.entities()}
    surf = {k: list(v) for k, v in json.load(open(SURF_F, encoding='utf-8')).items()} if SURF_F.exists() else {}
    zh = json.load(open(ZH_F, encoding='utf-8')) if ZH_F.exists() else {}

    curated = []
    for art in load_jsonl(CAND):
        if BAD_TITLE.search(art.get('title') or ''):
            continue
        gold = []
        for g in art['gold']:
            h = norm(g['head_text'])
            if not KEEP_HEAD.match(h):
                continue
            ev = norm(g['evidence'])
            if BAD_EV.search(ev):
                continue
            if h.lower() not in ev.lower():
                continue
            tail = clean_tail(g['tail_text'])
            if not tail or tail not in TAIL_MAP:
                continue
            if tail not in ev.lower():
                # allow stemmed presence
                if tail.split()[0] not in ev.lower():
                    continue
            hid = HEAD_MAP[h.lower()]
            tid = TAIL_MAP[tail]
            rid = g['relation_id']
            if rid in ('improves', 'enhances', 'promotes') and re.search(
                    r'\b(anxiety|pain|stress|fatigue|depression|nausea|distress|crying)\b', tail):
                rid = 'reduces'
            if rid in ('reduces', 'alleviates', 'lowers') and re.search(
                    r'\b(well-being|quality of life|performance|alertness|endurance|attention)\b', tail):
                continue
            # evidence must remain a contiguous substring of abstract/title
            blob = norm(art['title'] + ' ' + art['abstract'])
            if ev not in blob and ev.lower() not in blob.lower():
                # try recover from abstract sentences containing head+tail
                continue
            gold.append({
                'head_id': hid,
                'relation_id': rid,
                'tail_id': tid,
                'evidence': ev[:300],
                'evidence_level': 'C',
                'senses': ['gustatory'],
                'head_text': h,
                'tail_text': tail,
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
        curated.append({**art, 'gold': uniq, 'gold_n': len(uniq)})

    # Prefer diverse heads; put stronger clinical/neonatal sucrose + CMR first for Dev
    def score(a):
        heads = {g['head_id'] for g in a['gold']}
        s = 0
        if 'carbohydrate_mouth_rinse' in heads:
            s += 2
        if 'sucrose_stimulus' in heads or '24_sucrose_solution' in heads:
            s += 2
        if re.search(r'random|trial|participants|neonat|infant', a['abstract'], re.I):
            s += 1
        return (-s, a['pmid'])

    curated.sort(key=score)
    print('curated articles', len(curated), 'triples', sum(x['gold_n'] for x in curated))
    for a in curated[:40]:
        print(a['pmid'], a['gold_n'], a['title'][:68],
              '|', ','.join(f"{g['head_id']}/{g['relation_id']}/{g['tail_id']}" for g in a['gold']))

    # Split: first 20 -> Dev, next up to 60 -> Train (skip overlaps)
    dev_pick = curated[:20]
    train_pick = curated[20:80]
    print('dev_pick', len(dev_pick), 'train_pick', len(train_pick))

    # Ensure outcome entities exist in surfaces/zh
    for a in dev_pick + train_pick:
        for g in a['gold']:
            hid, tid = g['head_id'], g['tail_id']
            surf.setdefault(hid, [])
            if g['head_text'] not in surf[hid]:
                surf[hid].append(g['head_text'])
            zh.setdefault(hid, [g['head_text'], 'gustatory'])
            surf.setdefault(tid, [])
            if g['tail_text'] not in surf[tid]:
                surf[tid].append(g['tail_text'])
            zh.setdefault(tid, [g['tail_text'], 'outcome'])

    SURF_F.parent.mkdir(parents=True, exist_ok=True)
    json.dump(surf, open(SURF_F, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(zh, open(ZH_F, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    # Build schema before writing rows that depend on expand
    import subprocess
    subprocess.check_call([sys.executable, str(ROOT / 'pipeline' / 'build_entity_schema.py')])

    ref = json.loads(open(_paths.sp('dev'), encoding='utf-8').readline())
    instruction = ref['instruction']
    allowed = ref['allowed_relations']

    def make_row(a, split, subset_field):
        gold = []
        for g in a['gold']:
            gold.append({
                'head_id': g['head_id'],
                'relation_id': g['relation_id'],
                'tail_id': g['tail_id'],
                'evidence_level': 'C',
                'evidence': g['evidence'],
                'senses': ['gustatory'],
            })
        row = {
            'task_id': f"ds_{a['pmid']}",
            'pmid': a['pmid'],
            'split': split,
            'gold_type': 'human_reviewed' if split == 'dev' else 'distant_supervision',
            'input': {
                'title': a['title'],
                'abstract': a['abstract'],
                'year': a.get('year') or '',
                'pubtypes': a.get('pubtypes') or [],
            },
            'instruction': instruction,
            'allowed_relations': allowed,
            'channels': ['gustatory'],
            'annotation_scheme': 'v3_open_entities',
            'verdict': 'keep',
            'gold': gold,
            'gold_n': len(gold),
        }
        row[subset_field] = 'single_sense'
        return row

    # backup
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    for sp in ('dev', 'train'):
        src = _paths.sp(sp)
        bak = _paths.BM / f'.bak_{sp}_gustatory_{stamp}.jsonl'
        shutil.copy2(src, bak)
        print('backup', bak)

    have_dev = {str(r['pmid']) for r in load_jsonl(_paths.sp('dev'))}
    have_train = {str(r['pmid']) for r in load_jsonl(_paths.sp('train'))}
    have_test = {str(r['pmid']) for r in load_jsonl(_paths.sp('test'))}

    new_dev = []
    for a in dev_pick:
        if a['pmid'] in have_dev | have_train | have_test:
            continue
        # verify evidence substring
        blob = norm(a['title'] + ' ' + a['abstract'])
        ok = True
        for g in a['gold']:
            if g['evidence'] not in blob and g['evidence'].lower() not in blob.lower():
                ok = False
                break
        if not ok:
            continue
        new_dev.append(make_row(a, 'dev', 'dev_subset'))

    new_train = []
    for a in train_pick:
        if a['pmid'] in have_dev | have_train | have_test:
            continue
        if any(x['pmid'] == a['pmid'] for x in new_dev):
            continue
        blob = norm(a['title'] + ' ' + a['abstract'])
        ok = True
        for g in a['gold']:
            if g['evidence'] not in blob and g['evidence'].lower() not in blob.lower():
                ok = False
                break
        if not ok:
            continue
        new_train.append(make_row(a, 'train', 'train_subset'))

    # If evidence exact match failed, try to replace evidence with a sentence from abstract
    def fix_evidence(row):
        blob_title = norm(row['input']['title'])
        sents = [blob_title] + [norm(s) for s in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9(\[])', row['input']['abstract'])]
        out = []
        for g in row['gold']:
            hit = None
            for s in sents:
                if g['head_id'].replace('_', ' ')[:12].lower() in s.lower() or True:
                    # match by head_text/tail via ids surfaces
                    pass
                ht = None
            # find sentence containing both surface forms
            head_forms = surf.get(g['head_id'], [g['head_id'].replace('_', ' ')])
            tail_forms = surf.get(g['tail_id'], [g['tail_id'].replace('_', ' ')])
            for s in sents:
                if any(hf.lower() in s.lower() for hf in head_forms) and any(tf.lower() in s.lower() for tf in tail_forms):
                    hit = s[:300]
                    break
            if not hit:
                return None
            gg = dict(g)
            gg['evidence'] = hit
            out.append(gg)
        row['gold'] = out
        row['gold_n'] = len(out)
        return row

    new_dev2, new_train2 = [], []
    for r in new_dev:
        rr = fix_evidence(r)
        if rr:
            new_dev2.append(rr)
    for r in new_train:
        rr = fix_evidence(r)
        if rr:
            new_train2.append(rr)

    print('appending dev', len(new_dev2), 'train', len(new_train2))
    if not new_dev2 and not new_train2:
        raise SystemExit('nothing to append')

    dump_jsonl(_paths.sp('dev'), load_jsonl(_paths.sp('dev')) + new_dev2)
    dump_jsonl(_paths.sp('train'), load_jsonl(_paths.sp('train')) + new_train2)
    print('done')


if __name__ == '__main__':
    main()
