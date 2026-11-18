# -*- coding: utf-8 -*-
"""fetch_topup.py — 定向补抓：用高命中率领域检索式补齐命中池缺口。

背景：S6/E3/S5 收紧后命中量 10629 < 11000（test 只剩 129 篇）。
本脚本只跑新增的 15 条领域检索式（不走全量 QUERIES，故耗时短），增量并入 large_pool.json。
"""
import json
import time
import urllib.parse
from pathlib import Path

import fetch_papers_large as FL
import auto_mine_top as base

OUT_PATH = FL.OUT_PATH
RETMAX = 1200
PAGES = 2

TOPUP = [
    '("sauna"[tiab] OR "hot spring"[tiab] OR onsen[tiab]) AND (stress[tiab] OR relaxation[tiab] OR sleep[tiab] OR wellbeing[tiab])',
    '("cold water immersion"[tiab] OR "winter swimming"[tiab] OR "cold exposure"[tiab]) AND (mood[tiab] OR stress[tiab] OR wellbeing[tiab])',
    '("horticultural therapy"[tiab] OR gardening[tiab] OR "therapeutic garden"[tiab]) AND (depression[tiab] OR anxiety[tiab] OR wellbeing[tiab])',
    '("animal-assisted"[tiab] OR "pet therapy"[tiab] OR "equine-assisted"[tiab] OR "dog-assisted"[tiab]) AND (anxiety[tiab] OR depression[tiab] OR stress[tiab])',
    '("aquarium"[tiab] OR "fish tank"[tiab]) AND (anxiety[tiab] OR relaxation[tiab] OR mood[tiab] OR agitation[tiab])',
    '("sunlight exposure"[tiab] OR "sun exposure"[tiab] OR "daylight exposure"[tiab]) AND (sleep[tiab] OR mood[tiab] OR depression[tiab])',
    '("circadian lighting"[tiab] OR "light exposure"[tiab]) AND (sleep[tiab] OR circadian[tiab] OR mood[tiab]) AND (trial[tiab] OR intervention[tiab] OR study[tiab])',
    '("binaural beats"[tiab] OR "sound therapy"[tiab] OR "singing bowl"[tiab]) AND (anxiety[tiab] OR relaxation[tiab] OR sleep[tiab])',
    'reflexology[tiab] AND (anxiety[tiab] OR sleep[tiab] OR pain[tiab] OR fatigue[tiab])',
    '("mud therapy"[tiab] OR pelotherapy[tiab] OR fango[tiab] OR thalassotherapy[tiab]) AND (pain[tiab] OR stress[tiab] OR "quality of life"[tiab])',
    '("nature walk"[tiab] OR "forest walk"[tiab] OR "walking in nature"[tiab] OR "green walk"[tiab]) AND (stress[tiab] OR mood[tiab] OR rumination[tiab])',
    '("park prescription"[tiab] OR "nature prescription"[tiab] OR "green prescription"[tiab]) AND ("mental health"[tiab] OR wellbeing[tiab] OR stress[tiab])',
    '("outdoor recreation"[tiab] OR "outdoor activity"[tiab]) AND (wellbeing[tiab] OR depression[tiab] OR anxiety[tiab] OR stress[tiab])',
    '("view of nature"[tiab] OR "nature window"[tiab] OR "green view"[tiab] OR "window view"[tiab]) AND (recovery[tiab] OR stress[tiab] OR hospital[tiab])',
    '("mindfulness-based stress reduction"[tiab] OR "mindfulness-based cognitive therapy"[tiab]) AND (anxiety[tiab] OR depression[tiab] OR stress[tiab])',
    'qigong[tiab] AND (depression[tiab] OR anxiety[tiab] OR sleep[tiab] OR fatigue[tiab])',
]


def main():
    old = json.loads(OUT_PATH.read_text(encoding="utf-8")) if OUT_PATH.exists() else {}
    existing = {p["pmid"]: p for p in old.get("papers", [])}
    print("已有池:", len(existing), "篇")

    new_ids, per_q = [], []
    for term in TOPUP:
        ids = []
        for pg in range(PAGES):
            got, count = FL.esearch_page(term, retstart=pg * RETMAX)
            if not got:
                break
            ids += got
        hit = [i for i in ids if i not in existing]
        new_ids += hit
        per_q.append((term[:48], len(ids), len(hit)))
        print("  +%4d 新 / %4d 命中  %s" % (len(hit), len(ids), term[:60]))
        time.sleep(0.35)

    new_ids = list(dict.fromkeys(new_ids))
    print("待抓摘要:", len(new_ids))
    # 断点续抓：已抓到的摘要落盘缓存，中断后不重复请求 PubMed
    cache = OUT_PATH.parent / ".topup_cache.jsonl"  # Windows 下 /tmp 不可写
    added = 0
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                a = json.loads(line)
            except json.JSONDecodeError:
                continue  # 上一进程被杀时留下的截断行，跳过
            if a["pmid"] not in existing:
                existing[a["pmid"]] = a
                added += 1
        print("  从缓存恢复 %d 篇" % added)
    done = set()
    if cache.exists():
        for l in cache.read_text(encoding="utf-8").splitlines():
            try:
                done.add(json.loads(l)["pmid"])
            except (json.JSONDecodeError, KeyError):
                continue
    new_ids = [i for i in new_ids if i not in done]
    print("  仍需抓取:", len(new_ids))

    fcache = open(cache, "a", encoding="utf-8")
    for i in range(0, len(new_ids), 200):
        chunk = new_ids[i:i + 200]
        xml = base.get(base.BASE + "efetch.fcgi?" + urllib.parse.urlencode(
            {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml",
             **({"api_key": base.API_KEY} if base.API_KEY else {})}))
        arts = FL.parse_large(xml or "")
        for a in arts:
            if a["pmid"] not in existing:
                existing[a["pmid"]] = a
                added += 1
                fcache.write(json.dumps(a, ensure_ascii=False) + "\n")
        fcache.flush()
        print("  efetch %d/%d → 累计新增 %d" % (min(i + 200, len(new_ids)), len(new_ids), added))
        time.sleep(0.35)
    fcache.close()

    papers = list(existing.values())
    cats = old.get("categories", {})
    known = {x for v in cats.values() for x in v}  # 先建集合，避免每篇重复构建（O(n·m) 卡死）
    cats["topup"] = cats.get("topup", []) + [p["pmid"] for p in papers if p["pmid"] not in known]
    OUT_PATH.write_text(json.dumps({"papers": papers, "categories": cats}, ensure_ascii=False),
                        encoding="utf-8")
    print("完成: large_pool.json 共 %d 篇（新增 %d）" % (len(papers), added))


if __name__ == "__main__":
    main()
