import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
from _paths import p
# -*- coding: utf-8 -*-
"""按批导出待语义复核的三元组（紧凑格式，供逐条核读）。"""
import json, sys
from pathlib import Path
B = _paths.BM
work = json.loads((p('_sem_work.json')).read_text(encoding='utf-8'))
flags = json.loads((p('_sem_flags.json')).read_text(encoding='utf-8'))
fmap = {}
for k, ids in flags.items():
    for i in ids:
        fmap.setdefault(i, []).append(k.replace('weak_or_limited', 'WEAK').replace('negative', 'NEG')
            .replace('background_citation', 'BG').replace('measurement_as_tail', 'MEAS')
            .replace('nonspecific_head', 'NONSPEC').replace('scale_mismatch', 'SCALE')
            .replace('group_desc_head', 'GROUP').replace('shared_evidence', 'SHARED')
            .replace('near_duplicate_tail', 'DUP'))
start = int(sys.argv[1]); size = int(sys.argv[2]) if len(sys.argv) > 2 else 100
for w in work:
    if not (start <= w['idx'] < start + size):
        continue
    fl = ','.join(fmap.get(w['idx'], [])) or '-'
    ev = ' '.join((w.get('evidence') or '').split())[:155]
    print(f"{w['idx']:4d} [{fl}] {w['pmid']} | {w['head']} --{w['relation']}--> {w['tail']}")
    print(f"      ev: {ev}")
