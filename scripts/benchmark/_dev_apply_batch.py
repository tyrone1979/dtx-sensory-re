# -*- coding: utf-8 -*-
"""把一批人工裁定过的三元组落盘到 dataset/benchmark/dev.jsonl。

输入 decisions JSON（通常写在 tmp/benchmark/runs/_dec_bNN.json）:
{
  "41709613": {"subset": "single_sense", "senses": ["tactile"], "gold": [
      {"head": "self-administered acupressure", "tail": "pain",
       "relation": "reduces", "si": 1, "reason": "…"}]},
  ...
}
  si = 该篇 pack 里 sents 的下标（证据句）；evidence 由脚本从原句精确切出（≤300 字、止于词边界）
  可选 "ev": 显式给证据片段（必须是原文连续子串），用于整句含 "did not affect" 之类干扰措辞时
  可选 "head_zh" / "tail_zh": 新实体的中文名（旧实体已在词表里则可省）

落盘口径：gold 只写 id（head_id / relation_id / tail_id），不存实体文本；
实体写法追加进 tmp/schema/surfaces.json，中文名/类型追加进 tmp/schema/zh_merged.json，
再由 build_entity_schema.py 合成 dataset/schema/entities.json。

用法:
  python scripts/benchmark/_dev_apply_batch.py --pack tmp/benchmark/runs/_pack_b01.jsonl \
      --dec tmp/benchmark/runs/_dec_b01.json --tag b01

落盘后必须再跑一次 schema 构建与闸门（新篇会带来新实体）:
  python scripts/pipeline/build_entity_schema.py && python scripts/benchmark/_dev_verify.py
"""
import argparse
import json
import re
import shutil
import sys
import pathlib
import unicodedata
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _paths

import _schema  # noqa: E402  实体/关系 schema 统一入口
REL = _schema.rel_ids()
T2I = _schema.text2id()

# 实体词表的两个中间文件（build_entity_schema.py 的输入）
SURF_F = _paths.TMP / 'schema' / 'surfaces.json'    # {id: [原文写法...]}
ZH_F = _paths.TMP / 'schema' / 'zh_merged.json'     # {id: [中文名, type]}


def slug(s):
    s = unicodedata.normalize('NFKD', s or '')
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = s.replace('\u2009', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def load(p):
    return [json.loads(l) for l in open(p, encoding='utf-8')]


def dump(p, rows):
    with open(p, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')


def slice_ev(sent, tail):
    """证据句整句；超 300 字则从尾部往回找词边界切，且必须保住 tail。"""
    sent = norm(sent)
    if len(sent) <= 300:
        return sent
    tl = tail.lower()
    pos = sent.lower().find(tl)
    lo = max(300 - 80, (pos + len(tl)) if pos >= 0 else 200)
    for cut in range(300, max(lo, 60), -1):
        if sent[cut - 1] == ' ' or not sent[cut].isalnum():
            ev = sent[:cut].rstrip()
            if pos < 0 or pos + len(tl) <= len(ev):
                return ev
    raise SystemExit('cannot slice evidence for tail: %r' % tail)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pack', required=True)
    ap.add_argument('--dec', required=True)
    ap.add_argument('--tag', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    pack = {r['pmid']: r for r in load(args.pack)}
    pool = {str(json.loads(l)['pmid']): json.loads(l)
            for l in open(_paths.RUNS / '_topup_pool.jsonl', encoding='utf-8')}
    dec = json.loads(pathlib.Path(args.dec).read_text(encoding='utf-8'))
    dev = load(_paths.sp('dev'))
    ref = dev[0]
    have = {str(r['pmid']) for r in dev}

    surf = {k: list(v) for k, v in json.load(open(SURF_F, encoding='utf-8')).items()}
    zh = json.load(open(ZH_F, encoding='utf-8'))
    new_ent, missing_zh = [], []

    new, log = [], []
    for pmid, d in dec.items():
        assert pmid in pack, pmid
        if pmid in have:
            print('skip (already in dev):', pmid)
            continue
        pr = pack[pmid]
        po = pool[pmid]
        full = norm(po['title'] + ' ' + po['abstract'])          # 权威原文，evidence 必须是它的子串
        g, bad = [], []
        for t in d['gold']:
            head, tail, rel = norm(t['head']), norm(t['tail']), t['relation']
            si = int(t.get('si', 0))
            if rel not in REL:
                bad.append(('REL', rel, head, tail))
                continue
            if si >= len(pr['sents']):
                bad.append(('SI', si, head, tail))
                continue
            ev = norm(t['ev']) if t.get('ev') else slice_ev(pr['sents'][si], tail)
            if ev not in full:
                bad.append(('EV_NOT_IN_TEXT', head, tail, ev[:60]))
                continue
            if head.lower() not in ev.lower() and head.lower() not in full.lower():
                bad.append(('HEAD_NOT_IN_EV', head, tail, ev[:60]))
                continue
            if tail.lower() not in ev.lower():
                bad.append(('TAIL_NOT_IN_EV', head, tail, ev[:60]))
                continue
            hid = T2I.get(head.lower()) or slug(head)
            tid = T2I.get(tail.lower()) or slug(tail)
            # 新实体：写法进 surfaces，中文名/类型进 zh_merged（缺中文名先记下，稍后统一报错）
            for eid, text_s, tzh, slot in ((hid, head, t.get('head_zh'), 'intervention'),
                                           (tid, tail, t.get('tail_zh'), 'outcome')):
                if eid not in surf:
                    surf[eid] = []
                    new_ent.append((eid, text_s))
                if text_s not in surf[eid]:
                    surf[eid].append(text_s)
                T2I.setdefault(text_s.lower(), eid)     # 同批后续条目复用同一 id
                if eid not in zh:
                    if not tzh:
                        missing_zh.append((pmid, eid, text_s))
                    else:
                        zh[eid] = [tzh, slot]
            g.append({'head_id': hid, 'relation_id': rel, 'tail_id': tid,
                      'evidence_level': d.get('level') or pr.get('level') or 'C',
                      'evidence': ev, 'reason': t.get('reason', ''),
                      'check': 'keep', 'check_reason': t.get('reason', ''),
                      'senses': list(d['senses'])})
        if bad:
            for b in bad:
                print('REJECT', pmid, b)
        if not g:
            continue
        new.append({
            'task_id': 'ds_%s' % pmid, 'pmid': pmid, 'split': 'dev',
            'gold_type': 'human_reviewed',
            'input': {'title': norm(po['title']), 'abstract': norm(po['abstract']),
                      'year': po.get('year'), 'pubtypes': po.get('pubtypes') or []},
            'instruction': ref['instruction'],
            'allowed_relations': ref['allowed_relations'],
            'channels': [],
            'annotation_scheme': 'v3_open_entities', 'verdict': 'keep',
            'dev_subset': d['subset'],
            'gold': g, 'gold_n': len(g),
        })
        log.append({'pmid': pmid, 'subset': d['subset'], 'senses': d['senses'], 'n': len(g)})

    print('accepted papers:', len(new), 'triples:', sum(r['gold_n'] for r in new),
          '| 新实体:', len(new_ent))
    if missing_zh:
        print('缺中文名（在 decisions 里补 head_zh / tail_zh 后重跑，本次不落盘）:')
        for x in missing_zh:
            print('  MISSING_ZH', x)
        raise SystemExit(1)
    if args.dry_run:
        return
    if not new:
        return

    bak = _paths.HIST / ('.bak_before_dev_%s' % args.tag)
    shutil.copy(_paths.sp('dev'), bak)
    dump(_paths.sp('dev'), sorted(dev + new, key=lambda r: str(r['task_id'])))
    dump(_paths.RUNS / ('_dev_%s_log.jsonl' % args.tag), log)

    # 实体词表中间文件：写法 + 中文名/类型，供 build_entity_schema.py 重建 entities.json
    json.dump(surf, open(SURF_F, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
    json.dump(zh, open(ZH_F, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, sort_keys=True)
    print('surfaces/zh_merged 已更新:', len(surf), 'ids /', len(zh), 'ids')

    used = set(map(str, json.load(open(_paths.RUNS / '_dev_used_pmids.json', encoding='utf-8'))))
    used |= {r['pmid'] for r in new}
    json.dump(sorted(used), open(_paths.RUNS / '_dev_used_pmids.json', 'w', encoding='utf-8'))
    allused = set(map(str, json.load(open(_paths.USED_PMIDS, encoding='utf-8'))))
    allused |= {r['pmid'] for r in new}
    json.dump(sorted(allused), open(_paths.USED_PMIDS, 'w', encoding='utf-8'))
    print('backup:', bak.name)


if __name__ == '__main__':
    main()
