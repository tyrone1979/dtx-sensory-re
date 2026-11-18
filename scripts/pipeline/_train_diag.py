# -*- coding: utf-8 -*-
"""_train_diag.py — 诊断 train 候选召回的损失环节。

回答：`no_triple` 的论文里，是**根本没有实体**、**没有 outcome 尾实体**、
**没有线索词**，还是**三要素同句但间距超限**（可放宽）？

用法
----
  python scripts/pipeline/_train_diag.py --sample 4000
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402
import build_train_distant as B  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extra-corpus', action='append', default=[])
    ap.add_argument('--sample', type=int, default=0, help='只诊断前 N 篇（0 = 全部）')
    args = ap.parse_args()

    type_of, ent_cues = {}, []
    for e in B._schema.entities():
        type_of[e['id']] = e['type']
        w = tuple(B.toks(e['text']))
        if w:
            ent_cues.append((w, (e['id'], e['type'])))
    ent_idx = B.first_index(ent_cues)
    ent_maxlen = max(len(w) for w, _ in ent_cues)

    rel_cues = []
    for r in B._schema.relations():
        w = tuple(B.toks(r['name']))
        if w:
            rel_cues.append((w, (r['id'], r['name'])))
    for words, rid in B.EXTRA_CUES + B.RARE_CUES:
        rel_cues.append((tuple(words), (rid, ' '.join(words))))
    cue_idx = B.first_index(rel_cues)
    cue_maxlen = max(len(w) for w, _ in rel_cues)

    dev_test = set()
    for split in ('dev', 'test'):
        for line in open(_paths.sp(split), encoding='utf-8'):
            dev_test.add(str(json.loads(line)['pmid']))

    paths = [Path(_paths.LITERATURE)] + [Path(p) for p in args.extra_corpus]
    seen_pid, seen_title = set(), set()
    stats = Counter()
    gap_head, gap_tail = [], []
    examples = []
    n_seen = 0
    for path in paths:
        if not path.exists():
            continue
        for line in open(path, encoding='utf-8'):
            r = json.loads(line)
            pmid = str(r.get('pmid'))
            if pmid in seen_pid:
                continue
            seen_pid.add(pmid)
            if args.sample and n_seen >= args.sample:
                break
            n_seen += 1
            if pmid in dev_test:
                continue
            title, abstract = B.norm(r.get('title')), B.norm(r.get('abstract'))
            if len(abstract) < 150 or B.NEG_TI.search(title):
                continue
            if any(B.BAD_PUBTYPE.match(p.strip()) for p in (r.get('pubtypes') or [])):
                continue
            if B.ANIMAL.search(title + ' ' + abstract[:400]) or B.DRUG.search(title + ' ' + abstract):
                continue
            tk_ = B.re.sub(r'[^a-z0-9]', '', title.lower())[:120]
            if tk_ in seen_title:
                continue
            seen_title.add(tk_)

            sents = [s.strip() for s in B.SENT_SPLIT.split(abstract) if len(s.strip()) > 25]
            any_triple = False
            for s in sents:
                if len(s) > B.MAX_EV:
                    continue
                if B.extract_intra(s, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                    any_triple = True
                    break
            if any_triple:
                stats['has_triple'] += 1
                continue

            # 失败归因
            stats['no_triple'] += 1
            doc_ent = B.find_mentions(B.toks(title + ' ' + abstract), ent_idx, ent_maxlen)
            doc_head = [m for m in doc_ent if type_of.get(m[2][0]) != 'outcome']
            doc_tail = [m for m in doc_ent if type_of.get(m[2][0]) == 'outcome']
            if not doc_ent:
                stats['fail_no_entity'] += 1
                continue
            if not doc_head:
                stats['fail_no_head'] += 1
                continue
            if not doc_tail:
                stats['fail_no_tail'] += 1
                continue
            # 同句三要素？
            best = None
            for s in sents:
                if len(s) > B.MAX_EV:
                    continue
                tk = B.toks(s)
                ents = B.find_mentions(tk, ent_idx, ent_maxlen)
                cues = B.find_mentions(tk, cue_idx, cue_maxlen)
                hs = [m for m in ents if type_of.get(m[2][0]) != 'outcome']
                ts = [m for m in ents if type_of.get(m[2][0]) == 'outcome']
                if not (hs and ts and cues):
                    continue
                for cs, ce, cue in cues:
                    left = [m for m in hs if m[1] <= cs]
                    right = [m for m in ts if m[0] >= ce]
                    if left and right:
                        gh = cs - max(m[1] for m in left)
                        gt = min(m[0] for m in right) - ce
                        cand = (gh, gt, s)
                        if best is None or (gh + gt) < (best[0] + best[1]):
                            best = cand
                        break
            if best is None:
                # 有 head/cue/tail 但顺序或同句不满足
                stats['fail_not_same_sent_or_order'] += 1
                if len(examples) < 12:
                    examples.append((pmid, 'order', sents[0][:200]))
                continue
            stats['fail_gap'] += 1
            gap_head.append(best[0])
            gap_tail.append(best[1])
            if len(examples) < 12:
                examples.append((pmid, f'gap h={best[0]} t={best[1]}', best[2][:260]))

    print(json.dumps(dict(stats), ensure_ascii=False, indent=1))
    if gap_head:
        gh = sorted(gap_head); gt = sorted(gap_tail)
        def pct(a, p):
            return a[min(len(a) - 1, int(len(a) * p))]
        print('gap_head  p50/p75/p90/p95/max:',
              pct(gh, .5), pct(gh, .75), pct(gh, .9), pct(gh, .95), gh[-1],
              f'(当前阈值 {B.GAP_HEAD})')
        print('gap_tail  p50/p75/p90/p95/max:',
              pct(gt, .5), pct(gt, .75), pct(gt, .9), pct(gt, .95), gt[-1],
              f'(当前阈值 {B.GAP_TAIL})')
        for thr in (12, 16, 20, 25, 30):
            print(f'  放宽 gap_head<={thr}: 可救 {sum(1 for g in gap_head if g <= thr)} 篇')
        for thr in (6, 8, 10, 12):
            print(f'  放宽 gap_tail<={thr}: 可救 {sum(1 for g in gap_tail if g <= thr)} 篇')
    print('--- examples ---')
    for pmid, why, txt in examples:
        print(f'[{pmid}] {why} :: {txt}')


if __name__ == '__main__':
    main()
