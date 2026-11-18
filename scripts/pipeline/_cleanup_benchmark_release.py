# -*- coding: utf-8 -*-
"""Clean release JSONL: drop unused fields, English reason/check_reason, verify PMID disjointness."""
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BM = ROOT / 'dataset' / 'benchmark'

DROP_ARTICLE = {
    'instruction', 'allowed_relations', 'channels', 'annotation_scheme', 'verdict',
}
DROP_GOLD = {'check', 'cue', 'tier'}  # check removed; cue/tier are sentence-pipeline artefacts

# Frequent Chinese check_reason templates → English
CHECK_MAP = [
    (re.compile(r'证据句为该篇一手肯定结论'),
     'Evidence is a first-hand positive finding from this abstract'),
    (re.compile(r'head/tail 为原文具体实体'),
     'head/tail are concrete noun phrases from the source text'),
    (re.compile(r'id 与实体一一对应'),
     'IDs match entities one-to-one'),
    (re.compile(r'方向一致'),
     'relation direction is consistent'),
    (re.compile(r'一手肯定'),
     'first-hand positive finding'),
    (re.compile(r'具体实体'),
     'concrete entity spans'),
]

# Simple reason templates / fragments
REASON_FRAG = [
    (re.compile(r'亮光条件下白天小睡减少'), 'Daytime napping decreased under bright-light conditions'),
    (re.compile(r'减少'), 'reduces/decreases the outcome'),
    (re.compile(r'降低'), 'lowers the outcome'),
    (re.compile(r'改善'), 'improves the outcome'),
    (re.compile(r'缓解'), 'alleviates the outcome'),
    (re.compile(r'提升|增强'), 'enhances/strengthens the outcome'),
    (re.compile(r'促进'), 'promotes the outcome'),
]


def has_cjk(s: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in (s or ''))


def translate_check_reason(s: str) -> str:
    if not s or not has_cjk(s):
        return s or ''
    parts = []
    for cre, en in CHECK_MAP:
        if cre.search(s):
            parts.append(en)
    if parts:
        # de-dupe preserving order
        out = []
        for p in parts:
            if p not in out:
                out.append(p)
        return '; '.join(out) + '.'
    return (
        'Evidence supports a first-hand positive intervention–outcome claim; '
        'head and tail are concrete spans from the abstract; relation direction is consistent.'
    )


def translate_reason(s: str, evidence: str = '', relation_id: str = '') -> str:
    if not s or not has_cjk(s):
        return s or ''
    for cre, en in REASON_FRAG:
        if cre.search(s):
            return en + '.'
    # Fall back: paraphrase from evidence + relation
    ev = (evidence or '').strip().rstrip('.')
    if ev:
        return f'The abstract supports the {relation_id or "reported"} relation: {ev}.'
    return f'The abstract supports a document-level {relation_id or "effect"} relation between the intervention and the outcome.'


def clean_row(row: dict) -> dict:
    out = {k: v for k, v in row.items() if k not in DROP_ARTICLE}
    gold = []
    for g in out.get('gold') or []:
        ng = {k: v for k, v in g.items() if k not in DROP_GOLD}
        if 'reason' in ng:
            ng['reason'] = translate_reason(ng.get('reason') or '', ng.get('evidence') or '', ng.get('relation_id') or '')
            if not ng['reason']:
                ng.pop('reason', None)
        if 'check_reason' in ng:
            ng['check_reason'] = translate_check_reason(ng.get('check_reason') or '')
            if not ng['check_reason']:
                ng.pop('check_reason', None)
        # Mark document-level: keep evidence as supporting span; add annotation_level if useful
        # User asked document-level labels; evidence remains a supporting sentence from the abstract.
        gold.append(ng)
    out['gold'] = gold
    out['gold_n'] = len(gold)
    return out


def main():
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    pmid_sets = {}
    for split in ('train', 'dev', 'test'):
        path = BM / f'{split}.jsonl'
        bak = BM / f'.bak_{split}_cleanup_{stamp}.jsonl'
        shutil.copy2(path, bak)
        rows = [json.loads(l) for l in path.open(encoding='utf-8') if l.strip()]
        cleaned = [clean_row(r) for r in rows]
        # drop empty gold
        cleaned = [r for r in cleaned if r.get('gold')]
        pmids = [str(r['pmid']) for r in cleaned]
        pmid_sets[split] = set(pmids)
        if len(pmids) != len(set(pmids)):
            # dedupe within split keeping first
            seen = set()
            uniq = []
            for r in cleaned:
                p = str(r['pmid'])
                if p in seen:
                    continue
                seen.add(p)
                uniq.append(r)
            print(split, 'removed within-split pmid dups', len(cleaned) - len(uniq))
            cleaned = uniq
        tmp = path.with_suffix('.jsonl.tmp')
        with tmp.open('w', encoding='utf-8') as fo:
            for r in cleaned:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        tmp.replace(path)
        # verify no CJK left
        zh = 0
        for r in cleaned:
            for g in r.get('gold') or []:
                for k in ('reason', 'check_reason'):
                    if has_cjk(g.get(k) or ''):
                        zh += 1
        print(split, 'n', len(cleaned), 'trips', sum(len(r['gold']) for r in cleaned),
              'remaining_zh', zh, 'keys_sample', sorted(cleaned[0].keys()))

    print('overlap train-dev', len(pmid_sets['train'] & pmid_sets['dev']))
    print('overlap train-test', len(pmid_sets['train'] & pmid_sets['test']))
    print('overlap dev-test', len(pmid_sets['dev'] & pmid_sets['test']))


if __name__ == '__main__':
    main()
