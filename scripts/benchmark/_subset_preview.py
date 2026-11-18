import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
from _paths import p
# -*- coding: utf-8 -*-
"""预览：现有 test 292 篇的 subset/感官自动推导（不落盘）。"""
import json, re, collections

B = _paths.BM
def load(fn): return {str(x['pmid']): x for x in (json.loads(l) for l in open(_paths.p(fn), encoding='utf-8'))}
gt = load('test.jsonl')
SENS = {'visual','auditory','olfactory','gustatory','tactile','perceptual'}

KW = [
 (re.compile(r'music|sound|song|singing|choir|audio|boomwhacker|vibroacoustic', re.I), 'auditory'),
 (re.compile(r'aromatherapy|essential oil|aroma|odor|scent|phytoncide|olfact|citrus|rosemary|peppermint|melissa|chamomile', re.I), 'olfactory'),
 (re.compile(r'acupressure|massage|touch|warming|hydrotherapy|thermal|temperature|ice|footbath|foot bath|reflexology|warm|heat', re.I), 'tactile'),
 (re.compile(r'\blight|color|colou?r|daylight|window|view|visual|glass|plant', re.I), 'visual'),
 (re.compile(r'mindfulness|meditation|cbt|cognitive|psychother|digital therapeutic|spiritual|relaxation|guided imagery|self-management|self-care|acceptance|yoga|qigong|mind.body', re.I), 'perceptual'),
 (re.compile(r'taste|gustatory|flavor|mouth rinse|sucrose', re.I), 'gustatory'),
]

def senses_of(pmid, rec):
    ss = set()
    for g in _schema.expand_gold(rec.get('gold', [])):
        for r, s in KW:
            if r.search(g['head']):
                ss.add(s)
    src = 'head'
    if not ss:
        ch = [c for c in (eb.get(pmid, {}).get('channels') or []) if c in SENS]
        ss = set(ch)
        src = 'channels'
    return sorted(ss), (src if ss else 'none')

# 排除 v3 环境篇（dev，随后迁回）与已定清单的恢复篇
env_pmids = {p for p, x in gt.items() if str(x.get('split')) == 'dev' and x.get('annotation_scheme') == 'v3_open_entities' and x.get('gold')}
RESTORE = {'39610796','37408298','39614857','41758290','40915534','41212507','15514963','34055861','26424362','37332295','35292511',
           '34531801','39657179','31649501','38066232','33737763','37637657','25376753','31601170','30294390','22347856','34897869',
           '42712158','42759616','42430867','40682932','38173167','42849895','16013466','39736896','42058068','35460239','34058560',
           '32861897','40623834','37303921','39228637','32227624','17899351','23383976','35486418','37527546','37358893','31682572',
           '37993984','42240608','38659606'}

test_pmids = sorted(p for p, x in gt.items() if str(x.get('split')) == 'test' and p not in env_pmids)
print('existing test (excl env):', len(test_pmids))
unset = []
for p in test_pmids:
    ss, src = senses_of(p, gt[p])
    if not ss:
        unset.append(p)
        continue
    n_multi = len(ss)
    ss = set(ss)
    if n_multi >= 2 and 'perceptual' in ss and len(ss - {'perceptual'}) == 0:
        sub = 'perception'
    elif n_multi >= 2:
        sub = 'multi'
    elif ss == ['perceptual']:
        sub = 'perception'
    else:
        sub = 'single'
    print(f"{p}|{sub}|{'+'.join(ss)}|{src}|{eb[p]['input']['title'][:58]}")
print('--- UNRESOLVED (no kw hit) ---')
for p in unset:
    heads = sorted(set(g['head_id'] for g in gt[p]['gold']))
    print(p, '|', eb[p]['input']['title'][:70], '| heads:', ','.join(heads))
