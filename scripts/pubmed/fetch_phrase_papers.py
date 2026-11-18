# -*- coding: utf-8 -*-
"""fetch_phrase_papers.py — 按任意短语检索 PubMed（补稀有关系的语料）。

`fetch_entity_papers.py` 只能查 entities.json 里的实体；本脚本用于按**关系线索短语**
（如 "multidimensional assessment of"、"supported by evidence"）取语料，
让这些在摘要里极低频的关系也能在 train 里出现。

用法
----
  python scripts/pubmed/fetch_phrase_papers.py \
      --phrase "multidimensional assessment of" --phrase "mediated primarily via" \
      --per-phrase 60 --out tmp/source/pubmed/entity_retrieval_phrase.jsonl
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_entity_papers as F  # noqa: E402
import _paths  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--phrase', action='append', required=True)
    ap.add_argument('--per-phrase', type=int, default=60)
    ap.add_argument('--exclude-pmids', default='')
    ap.add_argument('--out', default=str(_paths.SOURCE / 'pubmed' / 'entity_retrieval_phrase.jsonl'))
    args = ap.parse_args()

    skip = set()
    if args.exclude_pmids:
        p = Path(args.exclude_pmids)
        if p.exists():
            skip = {ln.strip() for ln in open(p, encoding='utf-8') if ln.strip()}
        else:
            skip = {x.strip() for x in args.exclude_pmids.split(',') if x.strip()}

    pmids, owner = {}, {}
    for ph in args.phrase:
        try:
            ids = F.esearch(f'"{ph}" AND hasabstract', args.per_phrase)
        except Exception as ex:
            print('  esearch fail', ph, type(ex).__name__)
            ids = []
        for p in ids:
            if p in skip or p in pmids:
                continue
            pmids[p] = ph
        print(f'  {ph!r}: +{len(ids)} (unique so far {len(pmids)})')
        time.sleep(F.SLEEP)

    ids = list(pmids)
    out = open(args.out, 'w', encoding='utf-8')
    n = 0
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            rows = F.parse_xml(F.efetch(batch))
        except Exception as ex:
            print('  efetch fail', i, type(ex).__name__)
            rows = []
        for r in rows:
            r['query_entity'] = ''
            r['query_text'] = pmids.get(r['pmid'], '')
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
            n += 1
        time.sleep(F.SLEEP)
    out.close()
    print('written', n, '->', args.out)


if __name__ == '__main__':
    main()
