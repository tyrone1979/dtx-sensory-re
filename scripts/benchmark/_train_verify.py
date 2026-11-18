# -*- coding: utf-8 -*-
"""_train_verify.py — train split 的硬规则闸门（远监督数据自检）。

校验项
------
1. 结构：每行 task_id/pmid/split=input+gold；gold 非空；gold_n == len(gold)。
2. id 合法：head_id / tail_id ∈ entities.json，relation_id ∈ relations.json（24 个）。
3. 证据：evidence 是 title+abstract 的连续子串（归一化后比较）、≤300 字符、不以小写字母开头。
4. 实体落地：head 的任一写法出现在 title+abstract；tail 的任一写法出现在 evidence。
5. 方向一致性：reduces/lowers/alleviates/impairs/accelerates 等负向关系不得搭配 POS_OUTCOME 尾；
   improves/enhances/promotes 等正向关系不得搭配 NEG_OUTCOME 尾（与 test 闸门同规则）。
6. 泄漏：pmid 不得与 dev/test 重叠。
7. 统计：按关系 / 按 tier / 按篇条数分布，并给出覆盖率（实体与关系）。

用法：python scripts/benchmark/_train_verify.py [--json tmp/benchmark/runs/_train_v3_flags.json]
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

POS_OUTCOME = re.compile(
    r'\b(well-?being|quality\s+of\s+life|sleep\s+quality|positive\s+affect|'
    r'relaxation|restorativeness|mental\s+health|vigour|vigor|'
    r'comfort|satisfaction|attachment|hope|curiosity|creativity|'
    r'cognitive\s+development|working\s+memory|verbal\s+fluency|'
    r'parasympathetic\s+activity|environmental\s+perception)\b', re.I)
NEG_OUTCOME = re.compile(
    r'\b(anxiety|depression|depressive|pain|stress|fatigue|distress|'
    r'agitation|nausea|vomiting|insomnia|cortisol|blood\s+pressure|heart\s+rate|'
    r'inflammation|disability|apathy|anger|tension|fear|burnout|mood\s+disturbance|'
    r'negative\s+affect|inattentiveness)\b', re.I)
DIRECTION_OK = re.compile(
    r'\b(recovery|reduction|relief|control|remission|improvement|tolerance|'
    r'threshold|variability|wellbeing|well-?being|quality\s+of\s+life|positive\s+affect|'
    r'mood\b|relaxation|satisfaction|comfort|function|functioning|'
    r'abstinence|adherence|efficacy|response|capacity|vigour|vigor|'
    r'MCS|PCS|RSES|MoCA|Barthel|range\s+of\s+motion|'
    r'disorders?|risk|incidence|prevalence)\b', re.I)
NEG_CTX = re.compile(r'\b(no|not|without|failed to|did not|non-?significant)\b', re.I)
REDUCE = {'reduces', 'lowers', 'alleviates', 'impairs', 'accelerates'}
IMPROVE = {'improves', 'enhances', 'promotes', 'strengthens', 'stimulates', 'activates',
           'triggers', 'adjunct_improves'}


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').replace('\u2009', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def toks(s):
    return re.sub(r'[^a-z0-9]+', ' ', (s or '').lower()).split()


def toks_in(text_toks, surface):
    """token 级子序列匹配：实体写法 'acupressure (GB30)' 应命中文中 'acupressure GB30'。"""
    pat = toks(surface)
    if not pat:
        return False
    n = len(pat)
    return any(text_toks[i:i + n] == pat for i in range(len(text_toks) - n + 1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', default=None)
    args = ap.parse_args()

    ents = _schema.entities()
    idx = _schema.entity_index()
    forms, toks_forms = {}, {}
    for e in ents:
        forms.setdefault(e['id'], set()).add(norm(e['text']).lower())
        toks_forms.setdefault(e['id'], set()).add(e['text'])
    rels = _schema.rel_ids()

    rows = [json.loads(l) for l in open(_paths.sp('train'), encoding='utf-8')]
    leak = set()
    for split in ('dev', 'test'):
        for line in open(_paths.sp(split), encoding='utf-8'):
            leak.add(str(json.loads(line)['pmid']))

    flags = []
    c = Counter()
    rel_c = Counter()
    tier_c = Counter()
    ent_used = set()
    for r in rows:
        pid = str(r.get('pmid'))
        text = norm(r['input'].get('title', '') + ' ' + r['input'].get('abstract', ''))
        low = text.lower()
        ttoks = toks(text)
        if pid in leak:
            flags.append((pid, 'LEAK', ''))
        if r.get('split') != 'train':
            flags.append((pid, 'SPLIT', r.get('split')))
        if not r.get('gold'):
            flags.append((pid, 'EMPTY_GOLD', ''))
        if r.get('gold_n') != len(r.get('gold') or []):
            flags.append((pid, 'GOLD_N', ''))
        for g in r.get('gold') or []:
            hid, rid, tid = g.get('head_id'), g.get('relation_id'), g.get('tail_id')
            ev = norm(g.get('evidence', ''))
            c['triples'] += 1
            if hid not in idx:
                flags.append((pid, 'HEAD_ID', hid)); continue
            if tid not in idx:
                flags.append((pid, 'TAIL_ID', tid)); continue
            if rid not in rels:
                flags.append((pid, 'REL_ID', rid)); continue
            rel_c[rid] += 1
            tier_c[g.get('tier', '')] += 1
            ent_used.add(hid); ent_used.add(tid)
            if len(ev) > 300:
                flags.append((pid, 'EV_TOO_LONG', f'{len(ev)}'))
            if ev and ev[0].islower():
                flags.append((pid, 'EV_FRAGMENT', ev[:30]))
            if ev and ev.lower() not in low:
                flags.append((pid, 'EV_NOT_SUBSTR', tid))
            if not any(toks_in(ttoks, f) for f in toks_forms.get(hid, set())):
                flags.append((pid, 'HEAD_NOT_IN_TEXT', hid))
            ev_toks = toks(ev)
            if not any(toks_in(ev_toks, f) for f in toks_forms.get(tid, set())):
                flags.append((pid, 'TAIL_NOT_IN_EV', tid))
            tail_txt = norm(idx[tid]['text'])
            if not DIRECTION_OK.search(tail_txt):
                if rid in REDUCE and POS_OUTCOME.search(tail_txt) and not NEG_OUTCOME.search(tail_txt):
                    flags.append((pid, 'DIRECTION_SUSPECT', f'{rid}->{tid}'))
                if rid in IMPROVE and NEG_OUTCOME.search(tail_txt) and not POS_OUTCOME.search(tail_txt):
                    flags.append((pid, 'DIRECTION_SUSPECT', f'{rid}->{tid}'))

    print(f'train papers : {len(rows)}')
    print(f'triples      : {c["triples"]}')
    print(f'flagged      : {len(flags)}')
    print('avg triples  : %.2f' % (c['triples'] / max(len(rows), 1)))
    print('--- flag counts ---')
    for k, v in Counter(f[1] for f in flags).most_common():
        print(f'  {k:20s} {v}')
    print('--- relations ---')
    for k, v in rel_c.most_common():
        print(f'  {k:24s} {v}')
    print('--- tiers ---')
    for k, v in tier_c.most_common():
        print(f'  {str(k):8s} {v}')
    print(f'--- coverage ---\n  entities used {len(ent_used)}/{len(idx)}  relations used {len(rel_c)}/{len(rels)}')
    if flag_cnt := len(flags):
        print('--- sample flags ---')
        for f in flags[:20]:
            print(' ', f)
    if args.json:
        Path(args.json).write_text(json.dumps(
            {'papers': len(rows), 'triples': c['triples'], 'flags': flags,
             'relations': dict(rel_c), 'tiers': dict(tier_c)}, ensure_ascii=False, indent=1),
            encoding='utf-8')


if __name__ == '__main__':
    main()
