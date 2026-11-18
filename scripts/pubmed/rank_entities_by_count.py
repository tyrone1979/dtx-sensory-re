# -*- coding: utf-8 -*-
"""rank_entities_by_count.py — 统计每个干预实体在 PubMed 的检索总量，取 top-N。

用途：深检索前先知道"哪些实体有量"，把 efetch 预算花在刀刃上。

用法
----
  python scripts/pubmed/rank_entities_by_count.py --top 150
  # 产物
  #   tmp/source/pubmed/_entity_counts.json      全部实体计数
  #   tmp/benchmark/runs/_train_topN_ids.json    top-N id 清单（喂给 fetch_entity_papers --ids-file）
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

B = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'


def count(text):
    q = {'db': 'pubmed', 'term': f'"{text}" AND hasabstract', 'retmax': 0, 'retmode': 'json'}
    for i in range(3):
        try:
            with urllib.request.urlopen(B + 'esearch.fcgi?' + urllib.parse.urlencode(q), timeout=30) as r:
                return int(json.loads(r.read())['esearchresult']['count'])
        except Exception:
            time.sleep(1.5 * (i + 1))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=150)
    args = ap.parse_args()
    ents = [e for e in _schema.entities() if e['type'] != 'outcome']
    by = {}
    for e in ents:
        c = by.get(e['id'])
        if c is None or len(e['text']) < len(c['text']):
            by[e['id']] = e
    print('ids', len(by), flush=True)
    res = []
    for i, (eid, e) in enumerate(sorted(by.items()), 1):
        res.append({'id': eid, 'text': e['text'], 'n': count(e['text'])})
        if i % 100 == 0:
            print(i, len(by), flush=True)
        time.sleep(0.34)
    res.sort(key=lambda x: -x['n'])
    json.dump(res, open(_paths.SOURCE / 'pubmed' / '_entity_counts.json', 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    top = [r['id'] for r in res[:args.top]]
    json.dump({'ids': top},
              open(_paths.RUNS / f'_train_top{args.top}_ids.json', 'w'), indent=1)
    print('top10:', [(r['text'], r['n']) for r in res[:10]])
    print('sum top%d: %d   sum all: %d' % (args.top, sum(r['n'] for r in res[:args.top]),
                                           sum(r['n'] for r in res)))


if __name__ == '__main__':
    main()
