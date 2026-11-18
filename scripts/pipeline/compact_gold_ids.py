# -*- coding: utf-8 -*-
"""把 dev/test 的 gold 压成纯 id 三元组：删掉 head/tail 实体文本，relation → relation_id。

压缩前:
  {"head": "acupressure wristband", "head_id": "acupressure_wristband",
   "relation": "reduces", "tail": "duration of symptoms", "tail_id": "duration_of_symptoms", ...}
压缩后:
  {"head_id": "acupressure_wristband", "relation_id": "reduces", "tail_id": "duration_of_symptoms", ...}

实体文本不会丢：tmp/schema/surfaces.json 记 {id: [原文写法...]}，entities.json 由它 +
中文名/类型生成（scripts/pipeline/build_entity_schema.py）。后续新增批次由
_dev_apply_batch.py 往里追加。

用法:
  python scripts/pipeline/compact_gold_ids.py --dry-run
  python scripts/pipeline/compact_gold_ids.py
"""
import argparse
import collections
import json
import shutil
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _paths
import _schema

SURF = _paths.TMP / 'schema' / 'surfaces.json'
ORDER = ['head_id', 'relation_id', 'tail_id', 'evidence_level', 'evidence',
         'reason', 'check', 'check_reason', 'senses']


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    t2i = _schema.text2id()
    surfaces = collections.defaultdict(set)
    if SURF.exists():                                   # 保留历史批次登记过的写法
        for k, v in json.load(open(SURF, encoding='utf-8')).items():
            surfaces[k] |= set(v)

    out, stats = {}, collections.Counter()
    for sp in ('dev', 'test'):
        rows = [json.loads(l) for l in open(_paths.sp(sp), encoding='utf-8')]
        for r in rows:
            for g in r['gold']:
                for role in ('head', 'tail'):
                    text, eid = g[role], g[role + '_id']
                    assert t2i.get(text.lower()) == eid, (r['pmid'], text, eid)
                    surfaces[eid].add(text)
                stats['gold'] += 1
        out[sp] = rows
        stats[sp] = len(rows)

    # 压缩
    for sp, rows in out.items():
        for r in rows:
            new = []
            for g in r['gold']:
                d = {'head_id': g['head_id'],
                     'relation_id': g['relation'],
                     'tail_id': g['tail_id']}
                for k in ('evidence_level', 'evidence', 'reason', 'check', 'check_reason', 'senses'):
                    if k in g:
                        d[k] = g[k]
                new.append({k: d[k] for k in ORDER if k in d})
            r['gold'] = new

    print('papers:', {k: stats[k] for k in ('dev', 'test')}, '| gold:', stats['gold'])
    print('实体 id:', len(surfaces), '| 写法:', sum(len(v) for v in surfaces.values()))
    print('样例:', json.dumps(out['test'][0]['gold'][0], ensure_ascii=False)[:220])

    if args.dry_run:
        return

    SURF.parent.mkdir(parents=True, exist_ok=True)
    json.dump({k: sorted(v) for k, v in sorted(surfaces.items())},
              open(SURF, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    print('wrote', SURF.relative_to(_paths.ROOT))

    for sp, rows in out.items():
        bak = _paths.HIST / ('.bak_before_gold_ids_%s' % sp)
        shutil.copy(_paths.sp(sp), bak)
        with open(_paths.sp(sp), 'w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('wrote', sp, len(rows), 'papers | backup', bak.name)


if __name__ == '__main__':
    main()
