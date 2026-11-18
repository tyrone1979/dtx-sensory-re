# -*- coding: utf-8 -*-
"""fetch_entity_papers.py — 以 entities.json 的干预/情境实体为关键词检索 PubMed。

做法
----
每个干预类实体（type ≠ outcome）作为**精确短语**检索（`"<phrase>" AND hasabstract`），
按相关度取前 N 条 PMID，再分批 efetch 摘要，落 `tmp/source/pubmed/entity_retrieval.jsonl`。

输出每行：
  {"pmid","title","abstract","journal","year","pubtypes","query_entity": "<实体 id>", "query_text": "<短语>"}

用法
----
  python scripts/pubmed/fetch_entity_papers.py --per-entity 25
  python scripts/pubmed/fetch_entity_papers.py --per-entity 5 --limit 10 --out tmp/source/pubmed/_test.jsonl
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

BASE = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
API_KEY = ''          # 可选：NCBI api_key（10 req/s）；留空按 3 req/s 限速
SLEEP = 0.12 if API_KEY else 0.36


def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def esearch(term, retmax):
    q = {'db': 'pubmed', 'term': term, 'retmax': retmax, 'retmode': 'json', 'sort': 'relevance'}
    if API_KEY:
        q['api_key'] = API_KEY
    d = json.loads(_get(BASE + 'esearch.fcgi?' + urllib.parse.urlencode(q)) or '{}')
    return d.get('esearchresult', {}).get('idlist', [])


def efetch(ids):
    q = {'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml'}
    if API_KEY:
        q['api_key'] = API_KEY
    return _get(BASE + 'efetch.fcgi?' + urllib.parse.urlencode(q))


def parse_xml(xml):
    out = []
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return out
    for art in root.iter('PubmedArticle'):
        pmid = art.findtext('.//PMID') or ''
        title = ''.join(art.find('.//ArticleTitle').itertext()) if art.find('.//ArticleTitle') is not None else ''
        segs = []
        for ab in art.findall('.//Abstract/AbstractText'):
            lab = ab.get('Label')
            txt = ''.join(ab.itertext())
            segs.append(f'{lab}: {txt}' if lab else txt)
        abstract = ' '.join(segs).strip()
        year = (art.findtext('.//JournalIssue/PubDate/Year')
                or art.findtext('.//JournalIssue/PubDate/MedlineDate') or '')
        journal = art.findtext('.//Journal/Title') or ''
        pts = [pt.text for pt in art.findall('.//PublicationTypeList/PublicationType') if pt.text]
        if not pmid:
            continue
        out.append({'pmid': str(pmid), 'title': re.sub(r'\s+', ' ', title).strip(),
                    'abstract': re.sub(r'\s+', ' ', abstract).strip(),
                    'journal': journal, 'year': year[:4], 'pubtypes': pts})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--per-entity', type=int, default=25)
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 个实体（调试）')
    ap.add_argument('--min-len', type=int, default=6, help='实体短语最短字符数，太短不做检索')
    ap.add_argument('--types', default='', help='只查这些 type（逗号分隔，如 outcome,visual）；默认全部非 outcome')
    ap.add_argument('--ids-file', default='', help='只查这个 JSON 里列出的实体 id（list 或 {"ids":[...]}）')
    ap.add_argument('--exclude-pmids', default='', help='排除这些 PMID（逗号分隔或每行一个的文件路径），用于避开 dev/test')
    ap.add_argument('--all-surfaces', action='store_true',
                    help='每个 id 的全部写法都检索并合并结果（补覆盖时用，请求数大幅增加）')
    ap.add_argument('--cue-filter', action='store_true',
                    help='追加结果类动词限定（reduc*/improv*/decreas*/alleviat*/lower*），提高每篇三元组产出率')
    ap.add_argument('--out', default=str(_paths.SOURCE / 'pubmed' / 'entity_retrieval.jsonl'))
    args = ap.parse_args()
    CUE = (' AND (reduc*[tiab] OR improv*[tiab] OR decreas*[tiab] OR alleviat*[tiab] '
           'OR lower*[tiab] OR attenuat*[tiab] OR enhanc*[tiab])')

    want_types = {t.strip() for t in args.types.split(',') if t.strip()}
    if want_types:
        ents = [e for e in _schema.entities() if e['type'] in want_types]
    else:
        ents = [e for e in _schema.entities() if e['type'] != 'outcome']
    only_ids = None
    if args.ids_file:
        raw = json.load(open(args.ids_file, encoding='utf-8'))
        only_ids = set(raw['ids'] if isinstance(raw, dict) else raw)
        ents = [e for e in ents if e['id'] in only_ids]
    skip = set()
    if args.exclude_pmids:
        p = Path(args.exclude_pmids)
        if p.exists():
            skip = {ln.strip() for ln in open(p, encoding='utf-8') if ln.strip()}
        else:
            skip = {x.strip() for x in args.exclude_pmids.split(',') if x.strip()}
    # 默认同一 id 只查一次（用规范写法：slug 与 id 一致的那条，否则用最短写法）
    # --all-surfaces 时该 id 的每条写法都查，结果合并（补覆盖时用）
    by_id, all_surf = {}, {}
    for e in ents:
        all_surf.setdefault(e['id'], []).append(e['text'])
        cur = by_id.get(e['id'])
        if cur is None:
            by_id[e['id']] = e
        else:
            slug = re.sub(r'[^a-z0-9]+', '_', e['text'].lower()).strip('_')
            if slug == e['id'] or len(e['text']) < len(cur['text']):
                by_id[e['id']] = e
    if args.all_surfaces:
        targets = [(eid, t) for eid, ts in sorted(all_surf.items())
                   for t in sorted(set(ts)) if len(t) >= args.min_len]
    else:
        targets = [(eid, e['text']) for eid, e in sorted(by_id.items())
                   if len(e['text']) >= args.min_len]
    if args.limit:
        targets = targets[:args.limit]
    print(f'entities to query: {len(targets)} ({len({t[0] for t in targets})} ids)')

    pmids, owner = {}, {}
    multi = defaultdict(list)      # pmid -> 命中的多个实体 id（all-surfaces 时一个 pmid 可能属于多个实体）
    for i, (eid, text) in enumerate(targets, 1):
        term = f'"{text}" AND hasabstract' + (CUE if args.cue_filter else '')
        try:
            ids = esearch(term, args.per_entity)
        except Exception as ex:
            print('  esearch fail', eid, type(ex).__name__)
            ids = []
        for p in ids:
            if p in skip:
                continue
            if p not in pmids:
                pmids[p] = eid
                owner[p] = text
            if eid not in multi[p]:
                multi[p].append(eid)
        if i % 50 == 0:
            print(f'  {i}/{len(targets)} entities, unique PMIDs {len(pmids)}')
        time.sleep(SLEEP)

    ids = list(pmids)
    print(f'unique PMIDs: {len(ids)}')
    out = open(args.out, 'w', encoding='utf-8')
    n = 0
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        try:
            rows = parse_xml(efetch(batch))
        except Exception as ex:
            print('  efetch fail', i, type(ex).__name__)
            rows = []
        for r in rows:
            r['query_entity'] = ','.join(multi.get(r['pmid'], [pmids.get(r['pmid'], '')]))
            r['query_text'] = owner.get(r['pmid'], '')
            out.write(json.dumps(r, ensure_ascii=False) + '\n')
            n += 1
        print(f'  fetched {i + len(batch)}/{len(ids)} -> rows {n}')
        time.sleep(SLEEP)
    out.close()
    print('written', n, '->', args.out)


if __name__ == '__main__':
    main()
