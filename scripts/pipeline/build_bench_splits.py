# -*- coding: utf-8 -*-
"""把「题面」与「答案」合并成每个 split 一个自包含文件。

产出（dataset/benchmark/）：
    train.jsonl / dev.jsonl / test.jsonl
    每行 = 一篇论文的完整记录：
        input（title / abstract / year / pubtypes）+ instruction + allowed_relations
        + gold（三元组答案）+ gold_n + annotation_scheme / verdict / test_subset / dev_subset

数据来源（一次性迁移用；迁移后这两个合并版被删除）：
    gold_truth.jsonl           答案侧（gold、annotation_scheme、verdict、test_subset）
    extraction_benchmark.jsonl 题面侧（input、instruction、allowed_relations、channels）
    tmp/benchmark/legacy/*_review.jsonl  补 dev_subset / test_subset（只存在于台账，可选）

用法：
    python scripts/pipeline/build_bench_splits.py            # 生成三个 split 并删除旧合并版
    python scripts/pipeline/build_bench_splits.py --keep     # 只生成，不删旧文件
"""
import json
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _paths
from _paths import BM, SPLITS, sp

FIELDS = ['task_id', 'pmid', 'split', 'gold_type', 'input', 'instruction', 'allowed_relations',
          'channels', 'annotation_scheme', 'verdict', 'test_subset', 'dev_subset',
          'gold', 'gold_n']


def load(p):
    return [json.loads(l) for l in open(p, encoding='utf-8')]


def main():
    keep_old = '--keep' in sys.argv
    eb = {r['task_id']: r for r in load(BM / 'extraction_benchmark.jsonl')}
    gt = {r['task_id']: r for r in load(BM / 'gold_truth.jsonl')}
    assert set(eb) == set(gt), (len(eb), len(gt))

    # dev_subset 只在复核台账里
    sub = {}
    for path, field in ((_paths.DEV_REVIEW, 'dev_subset'), (_paths.TEST_REVIEW, 'test_subset')):
        if not path.exists():            # 台账仅历史留档，缺失不影响迁移
            continue
        for r in load(path):
            if r.get(field):
                sub.setdefault(str(r['pmid']), {})[field] = r[field]

    merged = {}
    for tid, e in eb.items():
        g = gt[tid]
        row = {}
        for f in FIELDS:
            if f in ('gold', 'gold_n'):
                continue
            if f in g:
                row[f] = g[f]
            elif f in e:
                row[f] = e[f]
        for f, v in sub.get(str(g.get('pmid')), {}).items():
            row.setdefault(f, v)
        row['gold'] = g.get('gold') or []
        row['gold_n'] = len(row['gold'])
        merged[tid] = {k: row[k] for k in FIELDS if k in row}

    for split in SPLITS:
        part = [r for r in merged.values() if r.get('split') == split]
        part.sort(key=lambda r: str(r['task_id']))
        with open(sp(split), 'w', encoding='utf-8') as fo:
            for r in part:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        print(f'{split}.jsonl: {len(part)} 篇 / {sum(len(r["gold"]) for r in part)} 条')

    # 校验：行内自洽
    total = 0
    for split in SPLITS:
        rows = load(sp(split))
        for r in rows:
            assert r['split'] == split, (split, r['task_id'])
            assert r['gold_n'] == len(r['gold'])
            assert isinstance(r['input'], dict) and r['input'].get('title'), r['task_id']
            assert r['input'].get('abstract'), r['task_id']
            assert r['instruction'] and r['allowed_relations']
        total += len(rows)
        print(f'  {split}: 字段 OK（{len(rows)} 篇）')
    print('合计篇数:', total)
    assert total == len(merged), (total, len(merged))

    if not keep_old:
        for f in ('gold_truth.jsonl', 'extraction_benchmark.jsonl',
                  'train_inputs.jsonl', 'dev_inputs.jsonl', 'test_inputs.jsonl'):
            p = BM / f
            if p.exists():
                os.remove(p)
                print('removed', p.name)


if __name__ == '__main__':
    main()
