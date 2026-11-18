# -*- coding: utf-8 -*-
"""Fetch PubMed papers on COLOUR + SHAPE (geometry/form) and healing/wellbeing.

Reuses the resilient pattern of fetch_supp.py: retries with backoff, polite
sleeps between E-utilities calls, incremental save after every category so a
mid-run failure never loses already-fetched data.
"""
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
ROOT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈"
OUT = f"{ROOT}/tmp/source/pubmed"
STORE = f"{OUT}/papers_visual2.json"

# ---------------------------------------------------------------- colour ----
COLOR_Q = [
    # ambient / interior colour in built environment
    '"interior color"[tiab] OR "interior colour"[tiab] OR "room color"[tiab]',
    '("color"[tiab] OR "colour"[tiab]) AND ("built environment"[tiab] OR "indoor environment"[tiab]) AND (wellbeing[tiab] OR "well-being"[tiab] OR stress[tiab] OR mood[tiab])',
    '("wall color"[tiab] OR "colour scheme"[tiab] OR "color scheme"[tiab]) AND (mood[tiab] OR emotion[tiab] OR anxiety[tiab] OR stress[tiab])',
    # colour-emotion / affective response
    '"color emotion"[tiab] OR "colour emotion"[tiab] OR "emotional response to color"[tiab]',
    '"color preference"[tiab] AND (environment[tiab] OR "living space"[tiab] OR interior[tiab])',
    '"color psychology"[tiab] AND (health[tiab] OR therapy[tiab] OR wellbeing[tiab] OR stress[tiab])',
    # specific hues with physiological / mental outcomes
    '("blue"[tiab] OR "green"[tiab]) AND "color"[tiab] AND (stress[tiab] OR "heart rate variability"[tiab] OR cortisol[tiab] OR anxiety[tiab]) AND (environment[tiab] OR "visual display"[tiab] OR room[tiab])',
    '("blue room"[tiab] OR "blue light"[tiab]) AND (mood[tiab] OR "blood pressure"[tiab] OR "heart rate"[tiab] OR "mental health"[tiab])',
    '("green"[tiab] AND ("environmental green"[tiab] OR "green color"[tiab] OR "green hue"[tiab])) AND (mental health[tiab] OR wellbeing[tiab] OR stress[tiab])',
    '("warm color"[tiab] OR "warm lighting"[tiab] OR "warm white"[tiab]) AND (sleep[tiab] OR relaxation[tiab] OR "circadian"[tiab] OR comfort[tiab])',
    '("color"[tiab] OR "colour"[tiab]) AND ("art therapy"[tiab] OR "expressive arts therapy"[tiab]) AND (anxiety[tiab] OR depression[tiab] OR stress[tiab] OR PTSD[tiab])',
    '("chromotherapy"[tiab] OR "color therapy"[tiab] OR "colour therapy"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR sleep[tiab] OR "mental health"[tiab])',
    '("biophilic"[tiab] AND color[tiab]) OR ("green infrastructure"[tiab] AND ("mental health"[tiab] OR wellbeing[tiab] OR stress[tiab]))',
    '("visual clutter"[tiab] OR "colour complexity"[tiab]) AND (stress[tiab] OR workload[tiab] OR fatigue[tiab] OR "mental workload"[tiab])',
]

# ----------------------------------------------------------------- shape ----
SHAPE_Q = [
    # spatial geometry / form and psychological response
    '("spatial form"[tiab] OR "spatial geometry"[tiab] OR "architectural form"[tiab]) AND (emotion[tiab] OR mood[tiab] OR "aesthetic"[tiab] OR "perceived quality"[tiab])',
    '("curved"[tiab] AND ("architecture"[tiab] OR "interior"[tiab] OR "space"[tiab])) AND (stress[tiab] OR anxiety[tiab] OR "wellbeing"[tiab] OR "well-being"[tiab] OR "favorability"[tiab])',
    '("rectilinear"[tiab] OR "angular"[tiab] OR "rounded"[tiab]) AND (space[tiab] OR interior[tiab] OR form[tiab]) AND (preference[tiab] OR emotion[tiab] OR "heart rate"[tiab] OR stress[tiab])',
    '"spatial configuration"[tiab] AND ("restoration"[tiab] OR "attention restoration"[tiab] OR "stress recovery"[tiab] OR "mental health"[tiab])',
    '("environmental complexity"[tiab] OR "visual complexity"[tiab] OR "geodesic"[tiab] OR "fractal"[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR anxiety[tiab] OR preference[tiab])',
    '"geometry"[tiab] AND ("natural environment"[tiab] OR "built environment"[tiab] OR "interior"[tiab]) AND (stress[tiab] OR restoration[tiab] OR anxiety[tiab] OR wellbeing[tiab])',
    '("shape"[tiab] AND ("landscape"[tiab] OR "garden"[tiab] OR "urban"[tiab])) AND (preference[tiab] OR aesthetics[tiab] OR "aesthetic quality"[tiab] OR wellbeing[tiab])',
    '("nature-inspired"[tiab] AND ("form"[tiab] OR "geometry"[tiab] OR "pattern"[tiab])) AND (stress[tiab] OR recovery[tiab] OR wellbeing[tiab] OR anxiety[tiab])',
    '("organic forms"[tiab] OR "biomorphic"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR preference[tiab])',
    '("spatial"[tiab] AND ("privacy"[tiab] OR "prospect-refuge"[tiab] OR "prospect and refuge"[tiab])) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab])',
    '("enclosure"[tiab] OR "visual enclosure"[tiab]) AND (preference[tiab] OR stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab])',
    '("wayfinding"[tiab] OR "legibility"[tiab] OR "orientation"[tiab]) AND ("wayfinding"[tiab] OR legibility[tiab]) AND (stress[tiab] OR anxiety[tiab] OR cognitive load[tiab] OR "mental workload"[tiab])',
    '("window"[tiab] AND (shape[tiab] OR geometry[tiab] OR "aspect ratio"[tiab])) AND (view[tiab] OR daylight[tiab]) AND (stress[tiab] OR recovery[tiab] OR wellbeing[tiab] OR "well-being"[tiab])',
    '("healing garden"[tiab] OR "therapeutic garden"[tiab]) AND (design[tiab] OR "design features"[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR "mental health"[tiab] OR preference[tiab])',
    '("concave"[tiab] OR "convex"[tiab]) AND (space[tiab] OR surface[tiab]) AND (emotion[tiab] OR anxiety[tiab] OR "heart rate"[tiab] OR preference[tiab])',
]

QUERIES = {"color": COLOR_Q, "shape": SHAPE_Q}


def get(url, retries=4):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kb-graph-builder/1.1"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if attempt == retries - 1:
                print("  ! failed:", e)
                return None
            time.sleep(2.0 * (attempt + 1))


def esearch(term, retmax=12):
    q = urllib.parse.urlencode({
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": "relevance",
    })
    d = get(BASE + "esearch.fcgi?" + q)
    if not d:
        return []
    try:
        return json.loads(d)["esearchresult"].get("idlist", [])
    except Exception:
        return []


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
    if os.path.exists(STORE):
        db = json.load(open(STORE, encoding="utf-8"))
    else:
        db = {"papers": [], "categories": {}, "queries": {}}
    have = {p["pmid"] for p in db["papers"]}

    for cat, qs in QUERIES.items():
        ids = []
        for term in qs:
            got = esearch(term)
            ids.extend(got)
            print(f"  [{cat}] {term[:58]}... -> {len(got)}")
            time.sleep(0.45)
        seen, uniq = set(), []
        for i in ids:
            if i not in seen and i not in have:
                seen.add(i)
                uniq.append(i)
        db["queries"][cat] = qs
        db["categories"][cat] = uniq
        for k in range(0, len(uniq), 40):
            x = efetch(uniq[k:k + 40])
            if x:
                db["papers"].extend(parse_articles(x))
            time.sleep(0.9)
        with open(STORE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=1)
        print(f"== {cat}: {len(uniq)} new pmids (total papers {len(db['papers'])})")

    by = {p["pmid"]: p for p in db["papers"]}
    with open(f"{OUT}/digest_visual2.txt", "w", encoding="utf-8") as f:
        for cat, pmids in db["categories"].items():
            f.write(f"\n{'=' * 24} {cat.upper()} {'=' * 24}\n")
            for pid in pmids:
                p = by.get(pid)
                if not p:
                    continue
                f.write(f"[{pid}] {p['year']} | {p['journal']} | {'/'.join(p['pubtypes'][:3])}\n")
                f.write(f"T: {p['title']}\n")
                f.write(f"A: {p['abstract'][:620]}\n\n")
    print("total:", len(db["papers"]))


if __name__ == "__main__":
    main()