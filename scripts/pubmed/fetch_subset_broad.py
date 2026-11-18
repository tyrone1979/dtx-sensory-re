# -*- coding: utf-8 -*-
"""Broad PubMed retrieval for auditory / olfactory / multisensory Table-1 top-up."""
import argparse
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
import _schema

BASE = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
SLEEP = 0.36
EXCLUDE = _paths.SOURCE / 'pubmed' / '_exclude_used_pmids.txt'

QUERIES = {
    'auditory': [
        '(music therapy[tiab] OR "music intervention"[tiab] OR "listening to music"[tiab]) AND (anxiety OR pain OR stress OR sleep OR mood) AND hasabstract',
        '("nature sounds"[tiab] OR "white noise"[tiab] OR "pink noise"[tiab] OR soundscape[tiab]) AND (sleep OR anxiety OR stress OR agitation) AND hasabstract',
        '("auditory stimulation"[tiab] OR "binaural beats"[tiab] OR "sound therapy"[tiab]) AND (anxiety OR pain OR sleep OR cognition) AND hasabstract',
        '(singing[tiab] OR choir[tiab] OR "vocal music"[tiab]) AND (anxiety OR depression OR mood OR stress) AND (trial OR randomized OR participants) AND hasabstract',
    ],
    'olfactory': [
        '(aromatherapy[tiab] OR "essential oil"[tiab] OR lavender[tiab] OR "orange oil"[tiab] OR peppermint[tiab]) AND (anxiety OR pain OR stress OR sleep OR nausea) AND hasabstract',
        '("olfactory stimulation"[tiab] OR "odor exposure"[tiab] OR "scent intervention"[tiab]) AND (anxiety OR mood OR cognition OR sleep) AND hasabstract',
        '("lavender oil"[tiab] OR "bergamot oil"[tiab] OR "rose oil"[tiab] OR "jasmine oil"[tiab]) AND (anxiety OR sleep OR stress OR pain) AND hasabstract',
        '(inhalation[tiab] AND (aromatherapy[tiab] OR "essential oil"[tiab])) AND (anxiety OR nausea OR pain OR sleep) AND hasabstract',
    ],
    'multisensory': [
        '(aromatherapy massage[tiab] OR "aroma massage"[tiab] OR "aromatherapy with massage"[tiab]) AND (anxiety OR pain OR stress OR sleep) AND hasabstract',
        '("forest bathing"[tiab] OR shinrin[tiab] OR "green exercise"[tiab] OR "nature-based"[tiab]) AND (anxiety OR stress OR mood OR cortisol) AND hasabstract',
        '("audio-visual"[tiab] OR audiovisual[tiab] OR "virtual reality"[tiab]) AND (music[tiab] OR aromatherapy[tiab] OR nature[tiab]) AND (anxiety OR pain OR stress) AND hasabstract',
        '(multisensory[tiab] OR "multi-sensory"[tiab]) AND (therapy OR intervention OR stimulation) AND (anxiety OR pain OR dementia OR agitation OR sleep) AND hasabstract',
        '("guided imagery"[tiab] AND (music[tiab] OR aroma[tiab] OR massage[tiab])) AND hasabstract',
        '("foot bath"[tiab] OR footbath[tiab]) AND (aroma OR aromatherapy OR lavender) AND hasabstract',
        '("combined intervention"[tiab] OR "multimodal sensory"[tiab]) AND (anxiety OR pain OR stress) AND hasabstract',
    ],
}

OUT = {
    'auditory': _paths.SOURCE / 'pubmed' / 'entity_retrieval_auditory_broad.jsonl',
    'olfactory': _paths.SOURCE / 'pubmed' / 'entity_retrieval_olfactory_broad.jsonl',
    'multisensory': _paths.SOURCE / 'pubmed' / 'entity_retrieval_multisensory_broad2.jsonl',
}


def get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def esearch(term, retmax=250):
    q = {'db': 'pubmed', 'term': term, 'retmax': retmax, 'retmode': 'json', 'sort': 'relevance'}
    d = json.loads(get(BASE + 'esearch.fcgi?' + urllib.parse.urlencode(q)) or '{}')
    return d.get('esearchresult', {}).get('idlist', [])


def efetch(ids):
    q = {'db': 'pubmed', 'id': ','.join(ids), 'retmode': 'xml'}
    return get(BASE + 'efetch.fcgi?' + urllib.parse.urlencode(q))


def parse_xml(xml, tag):
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
                'query_entity': f'{tag}_broad', 'query_text': 'broad',
            })
    return out


def fetch_queries(tag, skip):
    ids, seen = [], set()
    for q in QUERIES[tag]:
        time.sleep(SLEEP)
        for pmid in esearch(q, 250):
            if pmid in skip or pmid in seen:
                continue
            seen.add(pmid)
            ids.append(pmid)
        print(f'  {tag} unique so far: {len(ids)}')
    rows = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        time.sleep(SLEEP)
        rows.extend(parse_xml(efetch(batch), tag))
        print(f'  fetched {min(i+200,len(ids))}/{len(ids)} -> {len(rows)}')
    return rows


def fetch_ms_entities(skip, per_entity=25):
    """Phrase search for multiple_senses entity aliases."""
    ids, seen, qmap = [], set(), {}
    for e in _schema.entities():
        if e.get('type') != 'multiple_senses':
            continue
        phrase = (e.get('text') or '').strip()
        if len(phrase) < 4:
            continue
        term = f'"{phrase}"[tiab] AND hasabstract'
        time.sleep(SLEEP)
        for pmid in esearch(term, per_entity):
            if pmid in skip or pmid in seen:
                continue
            seen.add(pmid)
            ids.append(pmid)
            qmap[pmid] = e['id']
        if len(ids) % 100 < per_entity:
            print(f'  ms-entity unique so far: {len(ids)} (last {e["id"]})')
    rows = []
    for i in range(0, len(ids), 200):
        batch = ids[i:i + 200]
        time.sleep(SLEEP)
        parsed = parse_xml(efetch(batch), 'ms_entity')
        for r in parsed:
            r['query_entity'] = qmap.get(r['pmid'], 'multiple_senses')
        rows.extend(parsed)
        print(f'  ms-entity fetched {min(i+200,len(ids))}/{len(ids)} -> {len(rows)}')
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subsets', default='auditory,olfactory,multisensory,ms_entities')
    args = ap.parse_args()
    skip = set()
    if EXCLUDE.exists():
        skip = {ln.strip() for ln in open(EXCLUDE, encoding='utf-8') if ln.strip()}
    # also exclude already used benchmark PMIDs
    for s in _paths.SPLITS:
        for line in open(_paths.sp(s), encoding='utf-8'):
            skip.add(str(json.loads(line)['pmid']))
    print('exclude', len(skip))
    wanted = {x.strip() for x in args.subsets.split(',') if x.strip()}
    if 'auditory' in wanted:
        rows = fetch_queries('auditory', skip)
        OUT['auditory'].parent.mkdir(parents=True, exist_ok=True)
        with open(OUT['auditory'], 'w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('written auditory', len(rows), '->', OUT['auditory'])
        skip.update(r['pmid'] for r in rows)
    if 'olfactory' in wanted:
        rows = fetch_queries('olfactory', skip)
        with open(OUT['olfactory'], 'w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('written olfactory', len(rows), '->', OUT['olfactory'])
        skip.update(r['pmid'] for r in rows)
    if 'multisensory' in wanted:
        rows = fetch_queries('multisensory', skip)
        with open(OUT['multisensory'], 'w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('written multisensory', len(rows), '->', OUT['multisensory'])
        skip.update(r['pmid'] for r in rows)
    if 'ms_entities' in wanted:
        rows = fetch_ms_entities(skip, per_entity=30)
        out = _paths.SOURCE / 'pubmed' / 'entity_retrieval_ms_entities.jsonl'
        with open(out, 'w', encoding='utf-8') as fo:
            for r in rows:
                fo.write(json.dumps(r, ensure_ascii=False) + '\n')
        print('written ms_entities', len(rows), '->', out)


if __name__ == '__main__':
    main()
