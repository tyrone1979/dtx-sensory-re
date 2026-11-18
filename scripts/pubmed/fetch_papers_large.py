# -*- coding: utf-8 -*-
"""fetch_papers_large.py — 大规模抓取六通道文献池（目标 ≥12,000 篇，含摘要）。"""
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import auto_mine_top as base  # 复用 QUERIES / esearch / efetch / parse_articles

OUT_PATH = Path(r"D:/projects/digital-therapeutics/tmp/source/pubmed/large_pool.json")
RETMAX = 1200
PAGES = 9  # 每个 query 翻 PAGES 页（retstart 递增），深挖检索结果


def esearch_page(term, retmax=RETMAX, retstart=0):
    params = {
        "db": "pubmed", "term": term, "retmax": retmax, "retstart": retstart,
        "retmode": "json", "sort": "relevance",
    }
    if base.API_KEY:
        params["api_key"] = base.API_KEY
    data = json.loads(base.get(base.BASE + "esearch.fcgi?" + urllib.parse.urlencode(params)) or "{}")
    r = data.get("esearchresult", {})
    return r.get("idlist", []), int(r.get("count", "0") or 0)


def parse_large(xml_text):
    root = ET.fromstring(xml_text)
    arts = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        if mc is None:
            continue
        pmid = mc.findtext("PMID") or ""
        a = mc.find("Article")
        title, journal, year, abstract, doi = "", "", "", "", ""
        if a is not None:
            t = a.find("ArticleTitle")
            if t is not None:
                title = "".join(t.itertext()).strip()
            ab = a.find("Abstract")
            if ab is not None:
                abstract = " ".join("".join(at.itertext()).strip() for at in ab.findall("AbstractText"))
            j = a.find("Journal")
            if j is not None:
                journal = j.findtext("Title") or ""
                ji = j.find("JournalIssue")
                if ji is not None:
                    year = ji.findtext("PubDate/Year") or (ji.findtext("PubDate/MedlineDate") or "")[:4]
            el = a.find("ELocationID[@IdType='doi']")
            if el is not None and el.text:
                doi = el.text
        pubtypes = []
        pl = a.find("PublicationTypeList") if a is not None else None
        if pl is not None:
            pubtypes = [p.text for p in pl.findall("PublicationType") if p.text]
        if title or abstract:
            arts.append({"pmid": pmid, "title": title, "abstract": abstract,
                         "journal": journal, "year": year, "doi": doi, "pubtypes": pubtypes})
    return arts


def main():
    # 增量模式：跳过已抓取的 PMID
    existing = {}
    if OUT_PATH.exists():
        old = json.loads(OUT_PATH.read_text(encoding="utf-8"))
        existing = {p["pmid"]: p for p in old["papers"]}
        print("已有池:", len(existing), "篇，增量抓取中...")

    cat_pmids = {}
    all_ids = []
    for cat, qs in base.QUERIES.items():
        ids = []
        for term in qs:
            got, count = [], 0
            for pg in range(PAGES):
                ids_pg, count = esearch_page(term, retstart=pg * RETMAX)
                got.extend(ids_pg)
                if len(ids_pg) < RETMAX:
                    break
                time.sleep(0.35)
            ids.extend(got)
            print("[%s] %6d 命中 / %4d 取回  %s" % (cat, count, len(got), term[:55]))
            time.sleep(0.35)
        seen, uniq = set(), []
        for i in ids:
            if i not in seen:
                seen.add(i)
                uniq.append(i)
        cat_pmids[cat] = uniq
        all_ids.extend(uniq)
        print("== %s 小计: %d" % (cat, len(uniq)))

    seen, uniq = set(), []
    for i in all_ids:
        if i not in seen:
            seen.add(i)
            uniq.append(i)
    todo = [i for i in uniq if i not in existing]
    print("总去重 PMID:", len(uniq), "待抓取:", len(todo))

    papers = dict(existing)
    batches = (len(todo) + 99) // 100
    for bi, i in enumerate(range(0, len(todo), 100)):
        batch = todo[i:i + 100]
        try:
            for p in parse_large(base.efetch(batch)):
                papers[p["pmid"]] = p
        except Exception as e:
            print("  batch %d 失败: %s" % (bi, str(e)[:100]))
        if bi % 20 == 0:
            print("  efetch %d/%d, 已取 %d" % (bi + 1, batches, len(papers)))
        time.sleep(0.4)

    OUT_PATH.write_text(json.dumps({"categories": cat_pmids, "papers": list(papers.values())},
                                   ensure_ascii=False), encoding="utf-8")
    print("完成: large_pool.json 共 %d 篇" % len(papers))


if __name__ == "__main__":
    main()
