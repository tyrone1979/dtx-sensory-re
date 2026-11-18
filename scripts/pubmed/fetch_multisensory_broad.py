# -*- coding: utf-8 -*-
"""Broad PubMed retrieval for multisensory combined interventions."""
import json
import re
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
OUT = _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad.jsonl'
EXCLUDE = _paths.SOURCE / 'pubmed' / '_exclude_used_pmids.txt'

QUERIES = [
    '(aromatherapy massage[tiab] OR "aroma massage"[tiab] OR "aromatherapy with massage"[tiab]) AND (anxiety OR pain OR stress OR sleep OR mood) AND hasabstract',
    '("forest bathing"[tiab] OR "forest therapy"[tiab] OR shinrin[tiab] OR "green exercise"[tiab]) AND (anxiety OR stress OR mood OR blood pressure OR cortisol) AND hasabstract',
    '("guided imagery"[tiab] AND music[tiab]) AND (anxiety OR pain OR stress OR sleep) AND hasabstract',
    '("audio-visual"[tiab] OR audiovisual[tiab] OR "audio visual"[tiab]) AND (relaxation OR distraction) AND (anxiety OR pain OR stress) AND hasabstract',
    '("nature sounds"[tiab] AND (video[tiab] OR VR[tiab] OR "virtual reality"[tiab])) AND hasabstract',
    '("healing touch"[tiab] AND ("guided imagery"[tiab] OR meditation[tiab])) AND hasabstract',
    '(multisensory[tiab] OR "multi-sensory"[tiab] OR "multi sensory"[tiab]) AND (intervention OR therapy OR stimulation) AND (anxiety OR pain OR stress OR dementia OR agitation) AND hasabstract',
    '("foot bath"[tiab] OR footbath[tiab]) AND (aroma OR aromatherapy OR "essential oil") AND hasabstract',
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
                'query_entity': 'multisensory_broad', 'query_text': 'broad',
            })
    return out


def main():
    skip = set(EXCLUDE.read_text(encoding='utf-8').split()) if EXCLUDE.exists() else set()
    ids, seen = [], set()
    for q in QUERIES:
        time.sleep(SLEEP)
        for pmid in esearch(q, 250):
            if pmid in skip or pmid in seen:
                continue
            seen.add(pmid)
            ids.append(pmid)
        print('unique so far', len(ids))
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
