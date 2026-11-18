# -*- coding: utf-8 -*-
"""Supplementary PubMed fetch: forest bathing, wellness tourism, digital therapeutics, spa/thermal."""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OUT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈/tmp/source/pubmed"

QUERIES = {
    "forest": [
        '"forest bathing"[tiab] OR "shinrin-yoku"[tiab] OR "forest therapy"[tiab]',
        'phytoncide[tiab] OR "forest environment"[tiab] AND (immune[tiab] OR "natural killer"[tiab] OR cortisol[tiab])',
    ],
    "wellness_tourism": [
        '"wellness tourism"[tiab] OR "health tourism"[tiab]',
        '"therapeutic landscape"[tiab] OR "therapeutic landscapes"[tiab]',
    ],
    "digital": [
        '("digital therapeutic"[tiab] OR "digital mental health"[tiab]) AND (anxiety[tiab] OR stress[tiab] OR depression[tiab])',
        '"mobile app"[tiab] AND (mindfulness[tiab] OR meditation[tiab]) AND (stress[tiab] OR anxiety[tiab])',
    ],
    "spa_thermal": [
        '(spa[tiab] OR onsen[tiab] OR "thermal spring"[tiab] OR "hot spring"[tiab]) AND (health[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR relaxation[tiab])',
        '"nature-based therapy"[tiab] OR "ecotherapy"[tiab] OR "green exercise"[tiab]',
    ],
}


def get(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kb-graph-builder/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2.0 * (attempt + 1))


def esearch(term, retmax=8):
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    })
    return json.loads(get(BASE + "esearch.fcgi?" + q))["esearchresult"].get("idlist", [])


def efetch(ids):
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
        journal, year = "", ""
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
        arts.append({
            "pmid": pmid, "title": title, "journal": journal, "year": year,
            "abstract": " ".join(abstract_parts), "pubtypes": pubtypes, "doi": doi,
        })
    return arts


def main():
    existing = json.load(open(f"{OUT}/papers_raw.json", encoding="utf-8"))
    have = {p["pmid"] for p in existing["papers"]}
    new_papers, cat_map = [], {}
    for cat, qs in QUERIES.items():
        ids = []
        for term in qs:
            ids.extend(esearch(term))
            time.sleep(0.4)
        seen, uniq = set(), []
        for i in ids:
            if i not in seen and i not in have:
                seen.add(i)
                uniq.append(i)
        cat_map[cat] = uniq[:10]
        for i in range(0, len(uniq), 40):
            new_papers.extend(parse_articles(efetch(uniq[i:i + 40])))
            time.sleep(0.8)
        # incremental save so a mid-run failure never loses fetched data
        existing["categories"].update({cat: cat_map[cat]})
        existing["papers"].extend(new_papers)
        with open(f"{OUT}/papers_raw.json", "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=1)
        new_papers = []
        print(f"{cat}: {len(cat_map[cat])} new pmids")

    existing["categories"].update(cat_map)
    with open(f"{OUT}/papers_raw.json", "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=1)

    by_pmid = {p["pmid"]: p for p in existing["papers"]}
    with open(f"{OUT}/digest_supp.txt", "w", encoding="utf-8") as f:
        for cat, pmids in cat_map.items():
            f.write(f"\n===== {cat.upper()} =====\n")
            for pid in pmids:
                p = by_pmid.get(pid)
                if not p:
                    continue
                f.write(f"[{pid}] {p['year']} | {p['journal']} | {'/'.join(p['pubtypes'][:3])}\n")
                f.write(f"T: {p['title']}\n")
                f.write(f"A: {p['abstract'][:520]}\n\n")
    print(f"total papers now: {len(existing['papers'])}")


if __name__ == "__main__":
    main()
