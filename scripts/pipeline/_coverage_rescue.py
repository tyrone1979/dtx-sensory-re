# -*- coding: utf-8 -*-
"""_coverage_rescue.py — 覆盖救援通道：为未覆盖实体/关系补三元组。

背景
----
build_train_distant.py 的严格口径（GAP_HEAD 12 / GAP_TAIL 3）把很多
"实体在语料里可达、但同句间距略大"的三元组丢掉了。本脚本对**未覆盖的实体**
（和缺失的关系）用放宽口径重扫一遍语料，把能救的三元组并回 train.jsonl：

- 放宽间距：GAP_HEAD 25 / GAP_TAIL 8（正序），反序 6/5；
- 只为"未覆盖实体"或"缺失关系"保留结果，不扩大已覆盖部分的噪音；
- 保留全部护栏：否定、目的/方法句、疑问句、方向归一、复合名词、介词补语。

用法
----
  python scripts/pipeline/_coverage_rescue.py          # 扫描 + 合并落盘（自动备份）
  python scripts/pipeline/_coverage_rescue.py --dry-run
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _paths  # noqa: E402
import _schema  # noqa: E402
import build_train_distant as B  # noqa: E402

GAP_HEAD_LOOSE = 25
GAP_TAIL_LOOSE = 8
GAP_ANY_LOOSE = 5
GAP_TAIL_BEFORE_LOOSE = 6
GAP_HEAD_AFTER_LOOSE = 5
MAX_RESCUE_PER_PAPER = 4
MAX_GOLD_PER_PAPER = 6

EXTRA_CORPUS = [
    'entity_retrieval.jsonl', 'entity_retrieval_cue.jsonl',
    'entity_retrieval_missing.jsonl', 'entity_retrieval_deep.jsonl',
    'entity_retrieval_wide.jsonl', 'entity_retrieval_deep2.jsonl',
    'entity_retrieval_phrase.jsonl', 'entity_retrieval_rescue.jsonl',
]


def build_indexes():
    type_of, ent_cues = {}, []
    for e in _schema.entities():
        type_of[e['id']] = e['type']
        w = tuple(B.toks(e['text']))
        if w:
            ent_cues.append((w, (e['id'], e['type'])))
        B._EN_TEXT.setdefault(e['id'], e['text'])
    ent_idx = B.first_index(ent_cues)
    ent_maxlen = max(len(w) for w, _ in ent_cues)

    rel_cues = []
    for r in _schema.relations():
        w = tuple(B.toks(r['name']))
        if w:
            rel_cues.append((w, (r['id'], r['name'])))
    for words, rid in B.EXTRA_CUES + B.RARE_CUES:
        rel_cues.append((tuple(words), (rid, ' '.join(words))))
    cue_idx = B.first_index(rel_cues)
    cue_maxlen = max(len(w) for w, _ in rel_cues)
    return type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen


def loose_intra(sent, uncovered, missing_rel, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
    """放宽口径的同句抽取，只为未覆盖实体 / 缺失关系保留结果。"""
    if '?' in sent:
        return []
    tk = B.toks(sent)
    if len(tk) < 4:
        return []
    ents = B.find_mentions(tk, ent_idx, ent_maxlen)
    cues = B.find_mentions(tk, cue_idx, cue_maxlen)
    if not ents or not cues:
        return []
    heads = [m for m in ents if type_of.get(m[2][0]) != 'outcome']
    if not heads:
        return []
    got = {}
    for cs, ce, cue in cues:
        rel_id, cue_text = cue
        if rel_id in B.WEAK_REL and rel_id not in B.ALLOW_TAIL_WEAK:
            continue
        if not B.cue_ok(rel_id, cue_text, tk, ce):
            continue
        if cs > 0 and tk[cs - 1] in B.BE_BEFORE:
            continue
        if ce < len(tk) and tk[ce] in B.CUE_BAD_NEXT:
            continue
        if B.has_negation(tk, cs):
            continue
        any_tail = rel_id in B.ANY_TAIL_REL
        if any_tail:
            tail_pool = [m for m in ents if m[0] >= ce]
            tg = GAP_ANY_LOOSE
        else:
            tail_pool = [m for m in ents if type_of.get(m[2][0]) == 'outcome']
            tg = GAP_TAIL_LOOSE
        left = sorted([m for m in heads if m[1] <= cs and cs - m[1] <= GAP_HEAD_LOOSE],
                      key=lambda m: -m[1])[:4]
        right = sorted([m for m in tail_pool if m[0] >= ce and m[0] - ce <= tg],
                       key=lambda m: m[0])[:5]
        right = [m for m in right
                 if m[0] == ce or tk[m[0] - 1] not in B.PREP_BEFORE_TAIL]
        for h in left:
            for t in right:
                if h[2][0] == t[2][0]:
                    continue
                rid = B.normalize_dir(rel_id, t[2][0], type_of)
                if not rid:
                    continue
                if not (h[2][0] in uncovered or t[2][0] in uncovered or rid in missing_rel):
                    continue
                key = (h[2][0], rid, t[2][0])
                score = (B.PRIO.get(rid, 99), cs - h[1], t[0] - ce)
                if key not in got or score < got[key][0]:
                    got[key] = (score, {'head_id': key[0], 'relation_id': rid,
                                        'tail_id': key[2], 'evidence': sent,
                                        'cue': cue_text, 'tier': 'rescue'})
    return sorted(got.values(), key=lambda x: x[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    type_of, ent_idx, ent_maxlen, cue_idx, cue_maxlen = build_indexes()
    all_ent = {e['id'] for e in _schema.entities()}
    all_rel = {r['id'] for r in _schema.relations()}

    rows = [json.loads(l) for l in open(_paths.sp('train'), encoding='utf-8')]
    by_pmid = {str(r['pmid']): r for r in rows}
    covered = {t[k] for r in rows for t in r['gold'] for k in ('head_id', 'tail_id')}
    rel_used = {t['relation_id'] for r in rows for t in r['gold']}
    uncovered = all_ent - covered
    missing_rel = all_rel - rel_used
    print(f'before: papers {len(rows)}  covered_ent {len(covered)}  missing_rel {sorted(missing_rel)}')

    dev_test = set()
    for split in ('dev', 'test'):
        for line in open(_paths.sp(split), encoding='utf-8'):
            dev_test.add(str(json.loads(line)['pmid']))

    ref = json.loads(open(_paths.sp('test'), encoding='utf-8').readline())
    stats = Counter()
    rescued_ent, rescued_rel = set(), set()
    new_rows = {}
    seen_titles = set()

    paths = [Path(_paths.LITERATURE)] + [
        Path(_paths.SOURCE / 'pubmed' / f) for f in EXTRA_CORPUS]
    seen_pid = set()
    for path in paths:
        if not path.exists():
            print('  skip missing', path.name)
            continue
        for line in open(path, encoding='utf-8'):
            try:
                r0 = json.loads(line)
            except Exception:
                stats['bad_json'] += 1
                continue
            pmid = str(r0.get('pmid'))
            if not pmid or pmid in seen_pid:
                continue
            seen_pid.add(pmid)
            if pmid in dev_test:
                stats['skip_devtest'] += 1
                continue
            title, abstract = B.norm(r0.get('title')), B.norm(r0.get('abstract'))
            if len(abstract) < 150:
                stats['skip_short'] += 1
                continue
            tk_ = B.re.sub(r'[^a-z0-9]', '', title.lower())[:120]
            if tk_ in seen_titles:
                stats['skip_duptitle'] += 1
                continue
            seen_titles.add(tk_)
            if B.NEG_TI.search(title):
                stats['skip_negti'] += 1
                continue
            if any(B.BAD_PUBTYPE.match(p.strip()) for p in (r0.get('pubtypes') or [])):
                stats['skip_pubtype'] += 1
                continue
            if B.ANIMAL.search(title + ' ' + abstract[:400]) or B.DRUG.search(title + ' ' + abstract):
                stats['skip_drug_animal'] += 1
                continue

            doc_ent = {m[2][0] for m in B.find_mentions(
                B.toks(title + ' ' + abstract), ent_idx, ent_maxlen)}
            if not (doc_ent & uncovered) and not missing_rel:
                stats['skip_no_target'] += 1
                continue
            sents = [s.strip() for s in B.SENT_SPLIT.split(abstract)
                     if len(s.strip()) > 25]
            found = []
            for s in sents:
                if len(s) > B.MAX_EV or s[0].islower() or B.NONRESULT.search(s):
                    continue
                for _, tri in loose_intra(s, uncovered, missing_rel,
                                          ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                    found.append(tri)
            if not found:
                stats['no_rescue'] += 1
                continue
            found = found[:MAX_RESCUE_PER_PAPER]
            stats['rescued_papers'] += 1
            for t in found:
                rescued_ent.add(t['head_id'])
                rescued_ent.add(t['tail_id'])
                rescued_rel.add(t['relation_id'])
                t['evidence_level'] = 'C'
                st = type_of.get(t['head_id'])
                t['senses'] = [st] if st in B.SENSES else []
            if pmid in by_pmid:
                row = by_pmid[pmid]
                have = {(t['head_id'], t['relation_id'], t['tail_id']) for t in row['gold']}
                add = [t for t in found
                       if (t['head_id'], t['relation_id'], t['tail_id']) not in have]
                row['gold'] = (row['gold'] + add)[:MAX_GOLD_PER_PAPER]
                row['gold_n'] = len(row['gold'])
                stats['merged_into_existing'] += 1
            else:
                chans = sorted({s for t in found for s in t['senses']})
                new_rows[pmid] = {
                    'task_id': f'ds_{pmid}', 'pmid': pmid, 'split': 'train',
                    'gold_type': 'distant_supervision',
                    'input': {'title': title, 'abstract': abstract,
                              'year': r0.get('year'), 'pubtypes': r0.get('pubtypes') or []},
                    'instruction': ref['instruction'],
                    'allowed_relations': ref['allowed_relations'],
                    'channels': chans,
                    'annotation_scheme': 'v3_open_entities', 'verdict': 'keep',
                    'gold': found, 'gold_n': len(found)}
                stats['new_papers'] += 1

    rescued_ent &= all_ent
    still = uncovered - rescued_ent
    print('rescued entities:', len(rescued_ent), ' relations now:', len(rel_used | rescued_rel))
    print('still uncovered:', len(still))
    print(json.dumps(dict(stats), ensure_ascii=False))

    if not args.dry_run:
        bak = _paths.HIST / '.bak_before_train_rescue'
        if not bak.exists():
            bak.write_bytes(_paths.sp('train').read_bytes())
        out_rows = rows + list(new_rows.values())
        with open(_paths.sp('train'), 'w', encoding='utf-8', newline='\n') as f:
            for r in out_rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        json.dump({'rescued_entities': sorted(rescued_ent),
                   'rescued_relations': sorted(rescued_rel),
                   'still_uncovered': sorted(still),
                   'stats': dict(stats)},
                  open(_paths.RUNS / '_train_rescue_report.json', 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        print('written. backup ->', bak.name)


if __name__ == '__main__':
    main()
