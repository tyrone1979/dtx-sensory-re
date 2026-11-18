# -*- coding: utf-8 -*-
"""Fetch PubMed papers for digital-healing knowledge graph via NCBI E-utilities."""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OUT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈/tmp/source/pubmed"

QUERIES = {
    "visual": [
        '("green space"[tiab] OR "green spaces"[tiab]) AND (restoration[tiab] OR "attention restoration"[tiab] OR recovery[tiab])',
        '("window view"[tiab] OR "natural view"[tiab] OR "views of nature"[tiab]) AND (stress[tiab] OR recovery[tiab] OR restoration[tiab])',
        '"blue space"[tiab] AND (health[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR restoration[tiab])',
        'color[tiab] AND (mood[tiab] OR emotion[tiab] OR anxiety[tiab]) AND (preference[tiab] OR psychology[tiab] OR "heart rate"[tiab])',
    ],
    "auditory": [
        'music therapy[tiab] AND (anxiety[tiab] OR depression[tiab] OR "cortisol"[tiab])',
        '"nature sounds"[tiab] AND (stress[tiab] OR recovery[tiab] OR restoration[tiab])',
        'soundscape[tiab] AND (health[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR restoration[tiab])',
        'noise[tiab] AND health[tiab] AND (sleep[tiab] OR stress[tiab] OR annoyance[tiab])',
    ],
    "gustatory": [
        'taste[tiab] AND (emotion[tiab] OR mood[tiab] OR pleasure[tiab])',
        'food[tiab] AND ("mental health"[tiab] OR depression[tiab]) AND (diet[tiab] OR nutrition[tiab] OR "dietary pattern"[tiab])',
        'tea[tiab] AND (anxiety[tiab] OR stress[tiab] OR mood[tiab] OR relaxation[tiab])',
        '("umami"[tiab] OR "bitter"[tiab] OR "sweet taste"[tiab]) AND (appetite[tiab] OR satisfaction[tiab] OR emotion[tiab])',
    ],
    "olfactory": [
        'aromatherapy[tiab] AND (anxiety[tiab] OR sleep[tiab] OR stress[tiab])',
        'lavender[tiab] AND (sleep[tiab] OR anxiety[tiab] OR stress[tiab])',
        '"essential oil"[tiab] AND (anxiety[tiab] OR stress[tiab] OR "cortisol"[tiab] OR sleep[tiab])',
        'olfactory[tiab] AND (memory[tiab] OR emotion[tiab]) AND (wellbeing[tiab] OR "well-being"[tiab] OR preference[tiab])',
    ],
    "tactile": [
        'massage[tiab] AND (anxiety[tiab] OR pain[tiab] OR "cortisol"[tiab] OR depression[tiab])',
        'balneotherapy[tiab] OR ("thermal bath"[tiab] AND health[tiab]) OR ("hot spring"[tiab] AND health[tiab])',
        'touch[tiab] AND (wellbeing[tiab] OR "well-being"[tiab] OR stress[tiab] OR "social support"[tiab])',
        'hydrotherapy[tiab] OR ("water immersion"[tiab]) AND (sleep[tiab] OR relaxation[tiab] OR recovery[tiab])',
    ],
    "perceptual": [
        'mindfulness meditation[tiab] AND (anxiety[tiab] OR stress[tiab]) AND (randomized[tiab] OR trial[tiab] OR meta-analysis[tiab])',
        '"virtual reality"[tiab] AND (pain[tiab] OR anxiety[tiab] OR "mental health"[tiab]) AND (therapy[tiab] OR intervention[tiab])',
        '"forest bathing"[tiab] OR "shinrin-yoku"[tiab] OR "forest therapy"[tiab]',
        '("wellness tourism"[tiab] OR "health tourism"[tiab]) AND (wellbeing[tiab] OR "well-being"[tiab] OR health[tiab])',
        '"digital therapeutic"[tiab] OR "digital mental health"[tiab] OR "digital intervention"[tiab]',
    ],
}


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "kb-graph-builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def esearch(term, retmax=10):
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    })
    data = json.loads(get(BASE + "esearch.fcgi?" + q))
    return data["esearchresult"].get("idlist", [])


def efetch(ids):
    if not ids:
        return ""
    q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"})
    return get(BASE + "efetch.fcgi?" + q)


def parse_articles(xml_text):
    root = ET.fromstring(xml_text)
    arts = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        if mc is None:
            continue
        pmid = mc.findtext("PMID")
        a = mc.find("Article")
        title = "".join(a.find("ArticleTitle").itertext()) if a is not None and a.find("ArticleTitle") is not None else ""
        journal = ""
        year = ""
        if a is not None:
            j = a.find("Journal")
            if j is not None:
                journal = j.findtext("Title") or j.findtext("ISOAbbreviation") or ""
                ji = j.find("JournalIssue")
                if ji is not None:
                    year = ji.findtext("PubDate/Year") or (ji.findtext("PubDate/MedlineDate") or "")[:4]
        abstract_parts = []
        if a is not None:
            ab = a.find("Abstract")
            if ab is not None:
                for at in ab.findall("AbstractText"):
                    label = at.get("Label")
                    txt = "".join(at.itertext()).strip()
                    abstract_parts.append((label + ": " if label else "") + txt)
        pubtypes = []
        if a is not None:
            pl = a.find("PublicationTypeList")
            if pl is not None:
                pubtypes = [p.text for p in pl.findall("PublicationType") if p.text]
        doi = ""
        for aid in art.iter("ArticleId"):
            if aid.get("IdType") == "doi":
                doi = aid.text
        mesh = [mh.findtext("DescriptorName") for mh in mc.iter("MeshHeading") if mh.findtext("DescriptorName")]
        arts.append({
            "pmid": pmid, "title": title, "journal": journal, "year": year,
            "abstract": " ".join(abstract_parts), "pubtypes": pubtypes,
            "doi": doi, "mesh": mesh[:12],
        })
    return arts


def main():
    cat_pmids = {}
    all_ids = []
    for cat, qs in QUERIES.items():
        ids = []
        for term in qs:
            got = esearch(term)
            ids.extend(got)
            time.sleep(0.4)
        seen, uniq = set(), []
        for i in ids:
            if i not in seen:
                seen.add(i)
                uniq.append(i)
        cat_pmids[cat] = uniq[:14]
        all_ids.extend(cat_pmids[cat])
        print(f"{cat}: {len(cat_pmids[cat])} pmids")

    seen, uniq = set(), []
    for i in all_ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)

    papers = []
    for i in range(0, len(uniq), 40):
        batch = uniq[i:i + 40]
        xml_text = efetch(batch)
        papers.extend(parse_articles(xml_text))
        time.sleep(0.5)

    by_pmid = {p["pmid"]: p for p in papers}
    with open(f"{OUT}/papers_raw.json", "w", encoding="utf-8") as f:
        json.dump({"categories": cat_pmids, "papers": papers}, f, ensure_ascii=False, indent=1)
    print(f"total unique pmids: {len(uniq)}, fetched: {len(papers)}")

    with open(f"{OUT}/digest.txt", "w", encoding="utf-8") as f:
        for cat, pmids in cat_pmids.items():
            f.write(f"\n===== {cat.upper()} =====\n")
            for pid in pmids:
                p = by_pmid.get(pid)
                if not p:
                    continue
                f.write(f"[{pid}] {p['year']} | {p['journal']} | {'/'.join(p['pubtypes'][:3])}\n")
                f.write(f"T: {p['title']}\n")
                f.write(f"A: {p['abstract'][:520]}\n\n")


if __name__ == "__main__":
    main()
