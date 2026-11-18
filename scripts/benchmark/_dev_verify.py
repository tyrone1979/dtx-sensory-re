import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
# -*- coding: utf-8 -*-
"""dev 分片独立校验闸门：对 dataset/benchmark/dev.jsonl 跑与 test 完全相同的规则集
（_sem_verify.verify），从磁盘重算，不落盘主文件。

dev.jsonl 是自包含的（input + gold），闸门直接读它，无需再拼 answer/input 两份文件。

用法:
  python scripts/benchmark/_dev_verify.py            # 校验 dev 分片
  python scripts/benchmark/_dev_verify.py --json out.json
"""
import json, sys
sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
import _sem_verify
from pathlib import Path

B = _paths.BM


def load_dev():
    return [json.loads(l) for l in open(_paths.sp('dev'), encoding='utf-8')]


if __name__ == '__main__':
    dump = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None
    rows = load_dev()
    # verify 内部用 load_bench() 取原文；dev 行是自包含的，直接按 pmid 提供即可
    _sem_verify.load_bench = lambda: {str(r['pmid']): r for r in rows}
    for r in rows:
        r['split'] = 'test'  # verify 内部只校验 split==test
    out, c, npap, ntri, nflag = _sem_verify.verify(rows=rows)
    print(f'dev(v3) papers : {npap}\ntriples        : {ntri}\nflagged        : {nflag} ({nflag*100//max(ntri,1)}%)')
    print('--- flag counts ---')
    for k, v in c.most_common():
        print(f'  {k:26s} {v}')
    for o in [x for x in out if x['flags']]:
        print(f"  FLAG {o['pmid']} [{'/'.join(o['flags'])}] | {o['head'][:40]} -> {o['tail'][:40]}")
    if dump:
        Path(dump).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
