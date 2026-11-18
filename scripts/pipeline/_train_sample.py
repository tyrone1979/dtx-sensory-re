# -*- coding: utf-8 -*-
"""_train_sample.py — 抽样出可读的三元组清单，供人工核读精度。

按 tier × relation 分层抽样，把 head/cue/tail 与证据句并排打印，
并标出实体在证据句里的位置，便于快速判断归属与方向是否正确。

用法
----
  python scripts/pipeline/_train_sample.py --n 40
  python scripts/pipeline/_train_sample.py --n 20 --tier doc --rel improves
"""
import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', default=str(_paths.sp('train')))
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--tier', default='')
    ap.add_argument('--rel', default='')
    ap.add_argument('--seed', type=int, default=13)
    args = ap.parse_args()

    txt = {}
    typ = {}
    for e in _schema.entities():
        txt.setdefault(e['id'], e['text'])
        typ[e['id']] = e['type']

    pool = defaultdict(list)
    for line in open(args.path, encoding='utf-8'):
        r = json.loads(line)
        for t in r['gold']:
            if args.tier and t.get('tier') != args.tier:
                continue
            if args.rel and t['relation_id'] != args.rel:
                continue
            pool[(t.get('tier'), t['relation_id'])].append((r['pmid'], t))

    keys = sorted(pool, key=lambda k: -len(pool[k]))
    random.seed(args.seed)
    out = []
    i = 0
    while len(out) < args.n and keys:
        k = keys[i % len(keys)]
        if pool[k]:
            out.append((k, pool[k].pop(random.randrange(len(pool[k])))))
        i += 1
        if i > args.n * 40:
            break

    for (tier, rid), (pmid, t) in out:
        h, tl = t['head_id'], t['tail_id']
        print(f"--- {pmid}  [{tier}/{rid}]  {typ.get(h)}->{typ.get(tl)}")
        print(f"    H: {h}  ({txt.get(h, '')})")
        print(f"    T: {tl}  ({txt.get(tl, '')})")
        print(f"    cue: {t.get('cue')}")
        print(f"    EV: {t['evidence']}")
    print(f'\nrows: {len(out)}  strata: {len(pool)}')


if __name__ == '__main__':
    main()
