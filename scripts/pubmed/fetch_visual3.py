# -*- coding: utf-8 -*-
"""Second-pass shape/spatial-form queries: narrower, aimed at healing outcomes."""
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
ROOT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈"
OUT = f"{ROOT}/tmp/source/pubmed"
STORE = f"{OUT}/papers_visual3.json"

Q = [
    '("curvilinear"[tiab] OR "curved forms"[tiab] OR "curved surfaces"[tiab] OR "curved architecture"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR emotion[tiab] OR "restorative"[tiab] OR "attention"[tiab])',
    '("straight"[tiab] AND ("lines"[tiab] OR "geometry"[tiab])) AND (space[tiab] OR interior[tiab] OR room[tiab]) AND (emotion[tiab] OR preference[tiab] OR stress[tiab] OR anxiety[tiab] OR "heart rate"[tiab])',
    '("organic"[tiab] AND ("design"[tiab] OR "form"[tiab])) AND ("built environment"[tiab] OR interior[tiab] OR landscape[tiab] OR "public space"[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR anxiety[tiab] OR restoration[tiab])',
    '("spatial"[tiab] AND ("arrangement"[tiab] OR "organisation"[tiab] OR "organization"[tiab] OR "layout"[tiab])) AND ("mental health"[tiab] OR "wellbeing"[tiab] OR "well-being"[tiab] OR stress[tiab] OR anxiety[tiab] OR "quality of life"[tiab])',
    '("architecture"[tiab] OR "interior"[tiab] OR "environmental design"[tiab]) AND ("stress reduction"[tiab] OR "stress recovery"[tiab] OR "restorative"[tiab] OR "mental wellbeing"[tiab] OR "mental health"[tiab]) AND ("design features"[tiab] OR characteristics[tiab] OR elements[tiab])',
    '("green space"[tiab] AND (shape[tiab] OR geometry[tiab] OR "spatial"[tiab]) AND (configuration[tiab] OR structure[tiab] OR pattern[tiab])) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "mental health"[tiab])',
    '("biophilic"[tiab] AND design[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR anxiety[tiab] OR "mental health"[tiab] OR health[tiab])',
    '("nature-inspired"[tiab] OR "nature-based"[tiab]) AND (pattern[tiab] OR geometry[tiab] OR form[tiab] OR shape[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "mental health"[tiab] OR "restorative"[tiab])',
    '("chromatic"[tiab] OR "achromatic"[tiab]) AND (space[tiab] OR interior[tiab] OR "visual"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR "affective"[tiab])',
    '("color"[tiab] OR "colour"[tiab]) AND ("art therapy"[tiab] OR mandala[tiab] OR "coloring"[tiab]) AND (anxiety[tiab] OR stress[tiab] OR depression[tiab] OR "posttraumatic"[tiab] OR "quality of life"[tiab])',
    '("visual"[tiab] AND ("stimuli"[tiab] OR "exposure"[tiab]) AND ("nature"[tiab] OR "green"[tiab] OR landscape[tiab])) AND (stress[tiab] OR anxiety[tiab] OR "mental health"[tiab] OR wellbeing[tiab] OR mood[tiab])',
    '("light"[tiab] AND ("intensity"[tiab] OR "brightness"[tiab] OR "daylight"[tiab]]) AND ("color"[tiab] OR "chromaticity"[tiab])) AND (mood[tiab] OR stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR performance[tiab])',
    '("indoor plants"[tiab] OR "green interior"[tiab] OR "biophilic interior"[tiab] OR "vertical greenery"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR "mental health"[tiab] OR productivity[tiab])',
    '("view"[tiab] AND ("outlook"[tiab] OR "landscape"[tiab] OR "nature"[tiab])) AND (hospital[tiab] OR office[tiab] OR "care home"[tiab] OR "long-term care"[tiab]) AND (recovery[tiab] OR wellbeing[tiab] OR "mental health"[tiab] OR stress[tiab] OR anxiety[tiab])',
    '("sense of place"[tiab] OR "therapeutic landscape"[tiab] OR "healing garden"[tiab] OR "restorative garden"[tiab]) AND (design[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab] OR "mental health"[tiab] OR "quality of life"[tiab])',
]


def get(url, retries=4):
    for a in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "kb-graph-builder/1.1"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if a == retries - 1:
                print("  ! fail", e)
                return None
            time.sleep(2.0 * (a + 1))


def esearch(term, retmax=12):
    q = urllib.parse.urlencode({"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json", "sort": "relevance"})
    d = get(BASE + "esearch.fcgi?" + q)
    return json.loads(d)["esearchresult"].get("idlist", []) if d else []


def efetch(ids):
    return get(BASE + "efetch.fcgi?" + urllib.parse.urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}))


def parse(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        if mc is None:
            continue
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
        parts = []
        if a is not None and a.find("Abstract") is not None:
            for at in a.find("Abstract").findall("AbstractText"):
                lab = at.get("Label")
                parts.append((lab + ": " if lab else "") + "".join(at.itertext()).strip())
        pts = []
        if a is not None and a.find("PublicationTypeList") is not None:
            pts = [p.text for p in a.find("PublicationTypeList").findall("PublicationType") if p.text]
        doi = ""
        for aid in art.iter("ArticleId"):
            if aid.get("IdType") == "doi":
                doi = aid.text
        out.append({"pmid": mc.findtext("PMID"), "title": title, "journal": journal, "year": year,
                    "abstract": " ".join(parts), "pubtypes": pts, "doi": doi})
    return out


def main():
    db = json.load(open(STORE, encoding="utf-8")) if os.path.exists(STORE) else {"papers": [], "categories": {}, "queries": {}}
    have = {p["pmid"] for p in db["papers"]}
    ids = []
    for term in Q:
        g = esearch(term)
        ids.extend(g)
        print(f"  -> {len(g):2d}  {term[:60]}...")
        time.sleep(0.45)
    seen, uniq = set(), []
    for i in ids:
        if i not in seen and i not in have:
            seen.add(i)
            uniq.append(i)
    db["queries"]["pass2"] = Q
    db["categories"]["pass2"] = uniq
    for k in range(0, len(uniq), 40):
        x = efetch(uniq[k:k + 40])
        if x:
            db["papers"].extend(parse(x))
        time.sleep(0.9)
    json.dump(db, open(STORE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("pass2 new:", len(uniq), "total:", len(db["papers"]))


if __name__ == "__main__":
    main()