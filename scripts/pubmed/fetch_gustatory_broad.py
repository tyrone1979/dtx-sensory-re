# -*- coding: utf-8 -*-
"""Broad PubMed retrieval for taste / gustatory non-drug interventions."""
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths

BASE = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
SLEEP = 0.36
OUT = _paths.SOURCE / 'pubmed' / 'entity_retrieval_gustatory_broad.jsonl'
EXCLUDE = _paths.SOURCE / 'pubmed' / '_exclude_used_pmids.txt'

QUERIES = [
    '("mouth rinse"[tiab] OR "mouth rinsing"[tiab] OR "oral rinse"[tiab]) AND (taste OR carbohydrate OR menthol OR sucrose) AND (performance OR fatigue OR endurance OR pain OR anxiety)',
    '(taste OR gustatory OR flavor OR flavour) AND (intervention OR therapy OR stimulus OR exposure) AND (anxiety OR stress OR pain OR mood OR sleep OR fatigue) AND (human[mh] OR participants[tiab] OR patients[tiab]) AND hasabstract',
    '("green tea"[tiab] OR "black tea"[tiab] OR "matcha"[tiab] OR "herbal tea"[tiab] OR stevia[tiab]) AND (anxiety OR stress OR mood OR sleep OR cognition OR attention) AND (trial OR randomized OR randomised OR participants) AND hasabstract',
    '(sucrose[tiab] OR "sweet taste"[tiab] OR umami[tiab] OR "monosodium glutamate"[tiab]) AND (pain OR stress OR mood OR crying OR soothing) AND (infant OR neonat* OR adult OR participants) AND hasabstract',
    '("carbohydrate mouth rinse"[tiab] OR "menthol mouth rinse"[tiab] OR "taste stimulation"[tiab] OR "gustatory stimulation"[tiab]) AND hasabstract',
]


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def esearch(term, retmax=200):
    q = {'db': 'pubmed', 'term': term, 'retmax': retmax, 'retmode': 'json', 'sort': 'relevance'}
    d = json.loads(get(BASE + 'esearch.fcgi?' + urllib.parse.urlencode(q)) or '{}')
    return d.get('esearchresult', {}).get('idlist', [])


def efetch(ids):
    q = {'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml'}
    return get(BASE + 'efetch.fcgi?' + urllib.parse.urlencode(q))


def parse_xml(xml):
    import re
    out = []
    root = ET.fromstring(xml)
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
        if pmid and abstract:
            out.append({
                'pmid': str(pmid),
                'title': re.sub(r'\s+', ' ', title).strip(),
                'abstract': re.sub(r'\s+', ' ', abstract).strip(),
                'journal': journal, 'year': str(year)[:4], 'pubtypes': pts,
                'query_entity': 'gustatory_broad', 'query_text': 'broad',
            })
    return out


def main():
    skip = set(EXCLUDE.read_text(encoding='utf-8').split()) if EXCLUDE.exists() else set()
    ids = []
    seen = set()
    for q in QUERIES:
        time.sleep(SLEEP)
        for pmid in esearch(q, 200):
            if pmid in skip or pmid in seen:
                continue
            seen.add(pmid)
            ids.append(pmid)
        print(f'query hits unique so far: {len(ids)}')
    rows = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        time.sleep(SLEEP)
        rows.extend(parse_xml(efetch(batch)))
        print(f'fetched {min(i+200,len(ids))}/{len(ids)} -> {len(rows)}')
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as fo:
        for r in rows:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print('written', len(rows), '->', OUT)


if __name__ == '__main__':
    main()
