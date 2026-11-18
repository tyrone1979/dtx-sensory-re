# -*- coding: utf-8 -*-
"""coverage_ceiling.py — 量化实体覆盖的**理论上限**。

用途
----
回答一个问题：某些实体在 train 里覆盖不到，是因为"检索不够"，还是因为
这篇实体写法本身就是**某篇论文独有的注记产物**（换一篇论文永远不会复现）？

做法
----
1. 载入全部语料（默认 literature.jsonl + 传入的 extra-corpus）；
2. 对每个实体，取其全部写法（entities.json 里同 id 的 text），在语料正文
   （title + abstract，小写、空白归一）里做子串查找；
3. 分三类输出：
   - `reachable`：至少一篇语料正文含该写法 → 检索层面可达，缺的是抽取；
   - `devtest_only`：只在 dev/test 论文里出现 → 覆盖必然造成泄漏，应豁免；
   - `absent`：语料里完全没有 → 需要扩检索。

用法
----
  python scripts/pipeline/coverage_ceiling.py \
      --extra-corpus tmp/source/pubmed/entity_retrieval.jsonl \
      --out tmp/benchmark/runs/_coverage_ceiling.json
"""
import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

WS = re.compile(r'\s+')
TOK = re.compile(r'[a-z0-9]+')


def norm(s):
    return WS.sub(' ', (s or '').lower()).strip()


def toks(s):
    return TOK.findall(s or '')


def load_corpus(extras):
    seen, texts = set(), []
    for path in [_paths.LITERATURE] + list(extras):
        p = Path(path)
        if not p.exists():
            print('  skip missing', path)
            continue
        for line in open(p, encoding='utf-8'):
            try:
                r = json.loads(line)
            except Exception:
                continue
            pmid = str(r.get('pmid') or '')
            if not pmid or pmid in seen:
                continue
            seen.add(pmid)
            texts.append((pmid, norm((r.get('title') or '') + ' ' + (r.get('abstract') or ''))))
    return texts


def load_split_pmids():
    out = {}
    for name in ('dev', 'test', 'train'):
        path = _paths.sp(name)
        s = set()
        if path.exists():
            for line in open(path, encoding='utf-8'):
                try:
                    s.add(str(json.loads(line).get('pmid')))
                except Exception:
                    pass
        out[name] = s
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--extra-corpus', action='append', default=[])
    ap.add_argument('--out', default='tmp/benchmark/runs/_coverage_ceiling.json')
    args = ap.parse_args()

    ents = _schema.entities()
    by_id = defaultdict(list)
    for e in ents:
        by_id[e['id']].append(e['text'])
    types = {e['id']: e['type'] for e in ents}

    corpus = load_corpus(args.extra_corpus)
    split = load_split_pmids()
    devtest_pmids = split['dev'] | split['test']
    print(f'corpus papers: {len(corpus)}  dev/test papers: {len(devtest_pmids)}')

    # 语料里出现的实体：分"非 dev/test 论文出现"与"仅 dev/test 出现"
    # 索引：用每个写法里**最长的 token** 作键（通常最有区分度），
    # 论文端只对命中的 token 做一次完整子串校验，避免 1494×112k 全量扫描。
    index = defaultdict(list)      # token -> [(eid, surface_norm)]
    for eid, surfaces in by_id.items():
        for s in surfaces:
            ns = norm(s)
            if not ns:
                continue
            tk = toks(ns)
            key = max(tk, key=len) if tk else ns
            index[key].append((eid, ns))

    hit_pmids = defaultdict(set)
    for pmid, text in corpus:
        if not text:
            continue
        seen_tok = set(toks(text))
        checked = set()
        for tok in seen_tok:
            for eid, ns in index.get(tok, ()):
                if (eid, ns) in checked:
                    continue
                checked.add((eid, ns))
                if len(hit_pmids[eid]) < 3 and ns in text:
                    hit_pmids[eid].add(pmid)

    reachable, devtest_only, absent = set(), set(), set()
    for eid in by_id:
        hits = hit_pmids.get(eid, set())
        if not hits:
            absent.add(eid)
        elif hits - devtest_pmids:
            reachable.add(eid)
        else:
            devtest_only.add(eid)

    def bucket(names):
        return dict(Counter(types[i] for i in names))

    stats = {
        'entities_total': len(by_id),
        'reachable': len(reachable),
        'devtest_only': len(devtest_only),
        'absent': len(absent),
        'reachable_by_type': bucket(reachable),
        'devtest_only_by_type': bucket(devtest_only),
        'absent_by_type': bucket(absent),
    }
    for k, v in stats.items():
        print(f'{k}: {v}')

    json.dump({
        'stats': stats,
        'reachable': sorted(reachable),
        'devtest_only': sorted(devtest_only),
        'absent': sorted(absent),
        'absent_text': {i: by_id[i] for i in sorted(absent)},
        'devtest_only_text': {i: by_id[i] for i in sorted(devtest_only)},
    }, open(args.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('->', args.out)


if __name__ == '__main__':
    main()
