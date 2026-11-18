import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
from _paths import p
# -*- coding: utf-8 -*-
"""新范式筛选：head 必须可具体化（颜色/形状/具体声音/具体气味/味觉/触觉手法）。
标题命中具体刺激关键词；排除 VR/心理行为/综述/protocol/动物；摘要需设计+结果信号。"""
import json, re, glob
from collections import Counter, defaultdict

NEG_PT = ('Review', 'Meta-Analysis', 'Systematic Review', 'Protocol',
          'Case Reports', 'Scoping Review', 'Narrative Review', 'Comment',
          'Editorial', 'Published Erratum', 'Interview', 'Lecture')
NEG_TITLE = re.compile(
    r'systematic review|meta-?analys|scoping review|narrative review|literature review'
    r'|review of( the)? .*(evidence|studies|literature)|protocol (of|for)|study protocol'
    r'|overview of|evidence mapping|umbrella|guideline|consensus|recommendation', re.I)
NEG_VR = re.compile(r'virtual reality|\bVR\b', re.I)
NEG_PSY = re.compile(r'mindfulness|cognitive(?! performance| function)|meditation|yoga|tai chi|qigong|'
                     r'psychotherapy|cognitive.behavior|hypnosis|relaxation training|guided imagery|'
                     r'biofeedback|breathing exercise|progressive muscle', re.I)
NEG_ANIM = re.compile(r'\b(mice|mouse|rats?\b|zebrafish|drosophila|in vitro|cells?\b|pigs?\b|rabbits?|quail|chickens?)\b', re.I)
RESULT_SIG = re.compile(
    r'significan|p\s*[<=]\s*0?\.0|p\s*=\s*0?\.0\d|improv|reduc|decreas|lower(?:ed)?', re.I)
DESIGN_SIG = re.compile(r'random|RCT|trial|participants|patients|subjects|group|controlled', re.I)

FAM = {
 'vis_color': [r'colou?r', r'blue light', r'red light', r'green light', r'warm light',
               r'amber light', r'light colour', r'colored light', r'coloured'],
 'vis_shape': [r'kaleidoscope', r'fractal', r'mandala', r'geometric', r'\bshapes?\b', r'\bpattern'],
 'vis_img': [r'painting', r'\bart\b', r'artwork', r'photograph', r'aquarium', r'\bplants?\b',
             r'\bflowers?\b', r'nature (?:video|film|scene|image|view|documentary)', r'window view',
             r'\bwindow\b', r'green space', r'greenness', r'forest', r'garden', r'landscape'],
 'aud_nature': [r'bird', r'birdsong', r'water sound', r'ocean sound', r'rain sound', r'nature sound',
                r'white noise', r'pink noise', r'heartbeat', r'maternal voice', r'womb sound'],
 'aud_music': [r'classical music', r'mozart', r'\bbach\b', r'lullaby', r'instrumental music',
               r'live music', r'singing', r'\bsong', r'turkish music', r'chinese (?:traditional|five.elements) music',
               r'hindi', r'kundalini', r'music(?:al)? therapy', r'\bmusic\b', r'tempo', r'\bharp\b',
               r'\bflute\b', r'\bpiano\b', r'percussion', r'drum'],
 'olf_oil': [r'essential oil', r'aroma', r'aromatherap', r'\bscent', r'fragrance', r'olfactory',
             r'lavender', r'\brose\b', r'peppermint', r'chamomile', r'eucalyptus', r'citrus',
             r'\blemon\b', r'\borange\b', r'bergamot', r'jasmine', r'sandalwood', r'rosemary',
             r'vanilla', r'cinnamon', r'geranium', r'marjoram', r'ylang', r'frankincense'],
 'gust': [r'sucrose', r'sweet', r'sugar', r'bitter', r'\bsour\b', r'salt', r'glucose',
          r'chocolate', r'gargle', r'\bmint\b', r'honey', r'tast', r'flavor', r'flavour'],
 'tact_tech': [r'foot reflexology', r'foot bath', r'footbath', r'warm compress', r'hot compress',
               r'cold compress', r'ice massage', r'ice pack', r'moxibustion', r'shiatsu', r'tuina',
               r'heat therapy', r'acupressure', r'acupoint', r'sp6', r'sanyinjiao', r'\bli4\b',
               r'neiguan', r'zusanli', r'kangaroo', r'skin-to-skin', r'thermal therapy',
               r'weighted blanket', r'hot pack', r'warming', r'reflexology'],
}

def has_kw(txt, pats):
    return any(re.search(p, txt, re.I) for p in pats)

# seen set: test + all topup inputs + used pmids
seen = set()
gt = []
for _s in _paths.SPLITS:
    gt += [json.loads(l) for l in open(p(_s + '.jsonl'), encoding='utf-8')]
seen |= {str(x['pmid']) for x in gt}
for f in glob.glob('_topup_input_b0*.jsonl'):
    for l in open(f, encoding='utf-8'):
        seen.add(str(json.loads(l)['pmid']))
try:
    seen |= {str(p) for p in json.load(open(str(_paths.USED_PMIDS), encoding='utf-8'))}
except Exception:
    pass

pool = defaultdict(list)
with open(str(_paths.LITERATURE), encoding='utf-8') as f:
    for line in f:
        d = json.loads(line)
        pm = str(d['pmid'])
        if pm in seen:
            continue
        pts = {str(p) for p in (d.get('pubtypes') or [])}
        if pts & set(NEG_PT):
            continue
        t = d.get('title') or ''
        a = d.get('abstract') or ''
        if len(a) < 200 or NEG_TITLE.search(t):
            continue
        if NEG_VR.search(t) or NEG_PSY.search(t) or NEG_ANIM.search(t + ' ' + a[:400]):
            continue
        if not (DESIGN_SIG.search(a) and RESULT_SIG.search(a)):
            continue
        hits = []
        for fam, pats in FAM.items():
            if has_kw(t, pats):
                hits.append(fam)
        if len(hits) == 1:
            pool[hits[0]].append({'pmid': pm, 'fam': hits[0], 'title': t, 'abstract': a,
                                  'evidence_level': d.get('evidence_level'),
                                  'journal_if': d.get('journal_if'), 'year': d.get('year')})
        elif hits:
            pool['multi:' + '+'.join(hits)].append({'pmid': pm, 'fam': 'multi:' + '+'.join(hits),
                'title': t, 'abstract': a, 'evidence_level': d.get('evidence_level'),
                'journal_if': d.get('journal_if'), 'year': d.get('year')})

out = []
for fam, items in sorted(pool.items()):
    items.sort(key=lambda x: (x.get('evidence_level') in ('A', 'B'), -(x.get('journal_if') or 0)), reverse=True)
    for d in items:
        out.append(d)
with open(p('_spec_pool.jsonl'), 'w', encoding='utf-8') as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + '\n')
print('pool per family:')
for fam, items in sorted(pool.items(), key=lambda kv: -len(kv[1])):
    print(f'  {fam}: {len(items)}')
