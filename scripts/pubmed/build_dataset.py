# -*- coding: utf-8 -*-
"""
build_dataset.py — 大规模结构化文本数据集 + 知识抽取 benchmark（train 10000 / dev 500 / test 500）

⚠️ 遗留脚本（v2.0，2026-11-11 起仅供 annotate() 复用与历史追溯）。
   它产出的 benchmark/gold_truth.jsonl + extraction_benchmark.jsonl 两个合并版已废弃，
   现行数据集是 dataset/benchmark/{train,dev,test}.jsonl（每行自包含 input + gold）。
   直接运行会被 main() 的守门断言拦下；确需重建旧文件请显式加 --legacy-ok。

输出（dataset/）：
  literature.jsonl                 全量文献：pmid/标题/摘要/出处/DOI/IF/分区/收录/证据等级/通道
  knowledge_triples.jsonl          图谱三元组知识：头实体+关系+尾实体+必要属性(等级/依据/备注/效应)
  dataset_stats.json               数据集统计
  benchmark/entity_aliases.json    实体词典（远程监督依据，可审计）
  benchmark/relations.json         关系类型集合（来自图谱）
  benchmark/extraction_benchmark.jsonl   抽取任务（输入=标题+摘要，不含答案）
  benchmark/gold_truth.jsonl             gold truth（split: train/dev/test 为远程监督标注，
                                          gold_type=distant_supervision；另含 test_core）
  benchmark/gold_core_human.jsonl        87 篇人工循证 gold（最高可信度，gold_type=human_curated）
  evaluate_extraction.py           评测脚本（严格/宽松 P/R/F1 + 证据等级准确率）

gold truth 两层构造：
  1) human_curated：knowledge_graph.json 中人工循证整理的「摘要→三元组」对（87 篇）。
  2) distant_supervision：用 entity_aliases.json 词典 + 触发词在句内共现确定性标注，
     关系类型取图谱中该 benefit 节点的主导关系，证据等级由文献类型规则判定。
     规则完全确定性、可审计、可复现（seed=42 抽样）。
"""
import json
import random
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:/projects/digital-therapeutics")
KG_PATH = ROOT / "output" / "data" / "knowledge_graph.json"
MINED_PATH = ROOT / "data" / "pubmed" / "mined_papers.json"
POOL_PATH = ROOT / "data" / "pubmed" / "large_pool.json"
ALIAS_PATH = ROOT / "dataset" / "benchmark" / "entity_aliases.json"
RULINGS_PATH = ROOT / "dataset" / "review_rulings.json"
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
OUT = ROOT / "dataset"
BENCH = OUT / "benchmark"

N_TRAIN, N_DEV, N_TEST = 10000, 500, 500
SEED = 42


def load_jsonl_local(p):
    if not Path(p).exists():
        return []
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]

# 期刊 IF（sciei-journals 数据库逐刊核实 + 白名单约值），键=期刊名小写特征子串
JOURNAL_META = {
    "science (new york": {"if": 47.3, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "world psychiatry": {"if": 79.5, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "jama internal medicine": {"if": 26.3, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "jama pediatrics": {"if": 17.1, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "psychological bulletin": {"if": 19.9, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "cell reports. medicine": {"if": 14.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "phytomedicine": {"if": 11.3, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "environmental research": {"if": 8.2, "quartile": "Q1", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "journal of medical internet research": {"if": 8.2, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "jmir mhealth": {"if": 6.3, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "current opinion in psychology": {"if": 7.4, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "british medical bulletin": {"if": 7.5, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "neuroscience bulletin": {"if": 6.8, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "excli journal": {"if": 6.2, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "value in health": {"if": 6.2, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "nutrients": {"if": 5.8, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "journal of affective disorders": {"if": 5.7, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "psychological science": {"if": 5.4, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "european journal of public health": {"if": 5.2, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "scientific reports": {"if": 4.9, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "complementary therapies in medicine": {"if": 4.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "bjpsych open": {"if": 4.0, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "journal of epidemiology and global health": {"if": 4.0, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "addictive behaviors": {"if": 4.1, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "frontiers in public health": {"if": 4.1, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "sensors": {"if": 4.0, "quartile": "Q2", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "epidemiology (cambridge": {"if": 4.4, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "frontiers in psychology": {"if": 3.8, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "frontiers in psychiatry": {"if": 3.8, "quartile": "Q2", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "international journal of mental health nursing": {"if": 3.9, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "british journal of psychology": {"if": 3.6, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "frontiers in medicine": {"if": 3.6, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "clinics in dermatology": {"if": 3.5, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "rheumatology international": {"if": 3.5, "quartile": "Q2", "indexes": ["SCIE"], "source": "sciei-db"},
    "complementary therapies in clinical practice": {"if": 3.4, "quartile": "Q2", "indexes": ["SCIE"], "source": "sciei-db"},
    "supportive care in cancer": {"if": 3.4, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "brain sciences": {"if": 3.4, "quartile": "Q2", "indexes": ["SCIE"], "source": "sciei-db"},
    "journal of psychosomatic research": {"if": 3.3, "quartile": "Q2", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "psychophysiology": {"if": 3.2, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "sports (basel": {"if": 3.2, "quartile": "Q1", "indexes": ["ESCI"], "source": "sciei-db"},
    "nursing in critical care": {"if": 2.8, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "neurologia": {"if": 2.8, "quartile": "Q2", "indexes": ["SCIE"], "source": "sciei-db"},
    "environmental health and preventive medicine": {"if": 2.9, "quartile": "Q2", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "international journal of biometeorology": {"if": 3.0, "quartile": "Q2", "indexes": ["SCIE"], "source": "sciei-db"},
    "ssm - population health": {"if": 3.7, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "bmc complementary": {"if": 4.4, "quartile": "Q1", "indexes": ["SCIE"], "source": "sciei-db"},
    "geriatrics (basel": {"if": 2.4, "quartile": "Q3", "indexes": ["ESCI"], "source": "sciei-db"},
    "herd": {"if": 2.3, "quartile": "Q2", "indexes": ["SSCI"], "source": "sciei-db"},
    "vision research": {"if": 2.2, "quartile": "Q2", "indexes": ["SCIE"], "source": "sciei-db"},
    "international journal of environmental health research": {"if": 2.0, "quartile": "Q3", "indexes": ["SCIE"], "source": "sciei-db"},
    "dermatologic therapy": {"if": 1.0, "quartile": "Q4", "indexes": ["SCIE"], "source": "sciei-db"},
    "international journal of neuroscience": {"if": 1.7, "quartile": "Q4", "indexes": ["SCIE"], "source": "sciei-db"},
    "journal of environmental psychology": {"if": 7.3, "quartile": "Q1", "indexes": ["SSCI"], "source": "sciei-db"},
    "health & place": {"if": 4.2, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
    "npj digital medicine": {"if": 18.0, "quartile": "Q1", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "lancet digital health": {"if": 25.5, "quartile": "Q1", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "plos digital health": {"if": 7.7, "quartile": "Q1", "indexes": ["ESCI"], "source": "sciei-db"},
    "frontiers in digital health": {"if": 5.2, "quartile": "Q1", "indexes": ["ESCI"], "source": "sciei-db"},
    "intelligent medicine": {"if": 7.8, "quartile": "Q1", "indexes": ["ESCI", "EI"], "source": "sciei-db"},
    "journal of biomedical informatics": {"if": 5.9, "quartile": "Q2", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "artificial intelligence in medicine": {"if": 7.8, "quartile": "Q1", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "ieee journal of biomedical and health informatics": {"if": 7.7, "quartile": "Q1", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    "computer methods and programs in biomedicine": {"if": 6.4, "quartile": "Q1", "indexes": ["SCIE", "EI"], "source": "sciei-db"},
    # —— 白名单约值（2024 JCR 估算，标注 approx）——
    "bmj (clinical research": {"if": 93.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "the lancet.": {"if": 25.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "nature medicine": {"if": 58.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "nature human behaviour": {"if": 22.0, "quartile": "Q1", "indexes": ["SSCI"], "source": "whitelist-approx"},
    "nature mental health": {"if": 15.0, "quartile": "Q1", "indexes": ["ESCI"], "source": "whitelist-approx"},
    "jama network open": {"if": 10.5, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "eclinicalmedicine": {"if": 15.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "plos medicine": {"if": 11.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "sleep medicine reviews": {"if": 11.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "science of the total environment": {"if": 9.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "environment international": {"if": 11.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "landscape and urban planning": {"if": 9.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "neuroscience and biobehavioral reviews": {"if": 8.2, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "brain, behavior, and immunity": {"if": 8.8, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "trends in cognitive sciences": {"if": 16.0, "quartile": "Q1", "indexes": ["SSCI"], "source": "whitelist-approx"},
    "international journal of nursing studies": {"if": 8.0, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "\\bsleep\\b": {"if": 5.6, "quartile": "Q1", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "annals of behavioral medicine": {"if": 4.9, "quartile": "Q2", "indexes": ["SCIE"], "source": "whitelist-approx"},
    "jmir mental health": {"if": 5.0, "quartile": "Q1", "indexes": ["ESCI"], "source": "whitelist-approx"},
    "digital health (london": {"if": 3.9, "quartile": "Q1", "indexes": ["SCIE", "SSCI"], "source": "sciei-db"},
}


def match_journal(name):
    s = (name or "").lower().strip()
    best, bkey = None, ""
    for k, m in JOURNAL_META.items():
        kk = k.strip("\\b")
        if kk in s and len(kk) > len(bkey):
            best, bkey = m, kk
    if best:
        return dict(best)
    return {"if": None, "quartile": None, "indexes": [], "source": "unmatched"}


# ---------- PubMed 摘要抓取（图谱 101 篇） ----------
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dt-kg-dataset/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_abstracts(xml_text):
    root = ET.fromstring(xml_text)
    out = {}
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        if mc is None:
            continue
        pmid = mc.findtext("PMID")
        a = mc.find("Article")
        title = abstract = journal = year = doi = ""
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
        out[pmid] = {"title": title, "abstract": abstract, "journal": journal, "year": year, "doi": doi}
    return out


def fetch_graph_abstracts(pmids):
    got = {}
    for i in range(0, len(pmids), 40):
        try:
            q = urllib.parse.urlencode({"db": "pubmed", "id": ",".join(pmids[i:i + 40]), "retmode": "xml"})
            got.update(parse_abstracts(get(BASE + "efetch.fcgi?" + q)))
        except Exception as e:
            print("  摘要批次失败:", str(e)[:100])
        time.sleep(0.5)
    return got


# ---------- 证据等级 ----------
def suggest_level(pubtypes):
    pt = [p.lower() for p in pubtypes]
    if any("meta-analysis" in p or "systematic review" in p for p in pt):
        return "A", "高（系统评价/Meta分析）"
    if any("randomized controlled trial" in p for p in pt):
        return "B", "中高（RCT/类实验）"
    if any("clinical trial" in p or "comparative study" in p for p in pt):
        return "B", "中高（RCT/类实验）"
    if any("review" in p for p in pt):
        return "D", "参考（综述/机制/共识）"
    return "C", "中（观察性研究）"


def lit_text(r):
    return ("[PMID:%s] %s | %s, %s | DOI:%s | IF:%s | 证据等级:%s | 摘要: %s" % (
        r["pmid"], r["title"], r["journal"], r["year"], r["doi"] or "N/A",
        r["journal_if"] if r["journal_if"] is not None else "N/A",
        r["evidence_level"] or "N/A", r["abstract"][:800]))


def make_lit(pmid, title, abstract, journal, year, doi, pubtypes, channels, source, concl_zh=""):
    jm = match_journal(journal)
    lvl, lname = suggest_level(pubtypes)
    rec = {
        "id": "lit_%s" % pmid, "pmid": pmid, "title": title, "abstract": abstract,
        "journal": journal, "year": year, "doi": doi,
        "url": "https://pubmed.ncbi.nlm.nih.gov/%s/" % pmid,
        "pubtypes": pubtypes, "evidence_level": lvl, "level_name": lname,
        "channels": channels, "concl_zh": concl_zh,
        "journal_if": jm["if"], "journal_quartile": jm["quartile"],
        "journal_indexes": jm["indexes"], "journal_meta_source": jm["source"],
        "source": source,
    }
    rec["text"] = lit_text(rec)
    return rec


# ---------- 远程监督标注 ----------
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
# 论文级排除（用户裁定）：动物/体外/临床前实验，未在人身上论证 → 整篇不标注
ANIMAL_RE = re.compile(
    r"\b(rats?|mice|mouse|murine|rodents?|porcine|rabbits?|zebrafish|hamsters?|guinea pigs?)\b"
    r"|\b(lambs?|sheep|ewes?|calves?|cattle|cows?|piglets?|pigs?|horses?|foals?)\b"
    r"|\b(chicks?|chickens?|hens?|broilers?|piglets?|beagles?|primates?|macaques?|marmosets?)\b"
    r"|\b(animal|preclinical)\s+(model|study|experiment)s?\b"
    r"|\bin vitro\b|\bcell (culture|line)s?\b|\bex vivo\b", re.I)

# E3 论文级排除（设计类型）：无干预的观察性/流行病学研究，以及无一手结局的文献计量。
# 知识图谱表达的是「疗愈刺激 → 改善」的干预性因果，观察性研究只能给相关性，
# 且常把风险因子（噪声、交通污染）误读成疗法（S6 极性错误的根源）。
OBS_RE = re.compile(
    r"\b(prevalence|incidence|cohort|cross-?sectional|case-?control|epidemiolog\w*)\b"
    r"|\b(population-based|nationwide|national)\s+(survey|study|sample)\b"
    r"|\bquestionnaire survey\b|\bhealth examination survey\b", re.I)
INTERV_RE = re.compile(
    r"\b(randomi[sz]ed|randomly assigned|randomly divided|controlled trial|intervention group"
    r"|we (administered|recruited|randomi[sz]ed)|participants were (assigned|randomly)"
    r"|pre-?post|crossover|cross-over|quasi-experiment\w*)\b", re.I)
NO_PRIMARY_RE = re.compile(
    r"\bbibliometric\b|\bscientometric\b|\b(Scopus|Web of Science)\s+database\b"
    r"|\bliterature\s+(search|retrieval)\b[^.]{0,40}\bretrieved\b", re.I)
EXCLUDE_OBSERVATIONAL = False  # 见 excluded_by_design() 注释：开启需先扩池


def excluded_by_design(text):
    """E3：返回命中理由，或 None。有干预设计的一律放行。

    EXCLUDE_OBSERVATIONAL 默认关闭：全量开启会剔除 8200 篇观察性研究，
    使命中池从 11000+ 掉到 9416（< 10000 train + 1000 dev/test 的需求）。
    开启前必须先扩池。当前极性错误由 S6 句级守卫 + review 裁定兜底。
    """
    if NO_PRIMARY_RE.search(text):
        return "no_primary_data"
    if EXCLUDE_OBSERVATIONAL and OBS_RE.search(text) and not INTERV_RE.search(text):
        return "observational"
    return None


def build_routing(nodes, edges):
    """head 节点 → 所属疗愈通道（category）。直接连通道的用直连边；
    未直连的 stimulus 从包含它的 modality 继承路由（如 stim_vr_* 从 mod_vr 继承）。"""
    ch_ids = {nid for nid, n in nodes.items() if n.get("type") == "channel"}
    route = defaultdict(set)
    for e in edges:
        if e["target"] in ch_ids:
            route[e["source"]].add(e["target"])
    for e in edges:
        if e["relation"] in ("包含", "采用") and e["source"] in route and e["target"] not in ch_ids:
            route[e["target"]] |= route[e["source"]]
    return route


def annotate(paper, head_res, tail_res, node_name, benefit_relation, trigger_res, global_trigger,
             neg_res=None, route=None, child_of=None):
    """返回 [(head_id, head_name, relation, tail_id, tail_name)]；每条带 category（疗愈通道类）。

    Granularity（全文级）：若论文任一处命中某 modality 的子 stimulus，
    则该 modality 类别整体让位，不做头实体（用户裁定 ds_41672150）。
    """
    text = (paper.get("title", "") + ". ") * 1 + paper.get("abstract", "")
    text = re.sub(r"\s+", " ", text)
    if ANIMAL_RE.search(text):
        return []  # 动物/体外/临床前研究：未在人身上论证，整篇不产三元组
    if excluded_by_design(text):
        return []  # E3：观察性流行病学 / 文献计量，无干预或无一手指标
    sents = SENT_SPLIT.split(text) if text else []
    sent_hits = []
    for sid, sent in enumerate(sents):
        if not global_trigger.search(sent):
            continue
        if neg_res is not None and neg_res.search(sent):
            continue  # 句级负向守卫：综述性提及 / in vitro / 非哺乳类实验系统 / 修辞引号
        heads = {h for h, rxs in head_res.items() if any(rx.search(sent) for rx in rxs)}
        tails = {t for t, rxs in tail_res.items() if any(rx.search(sent) for rx in rxs)}
        # 列举/背景句守卫（用户裁定 ds_32742639）：多逗号 + 多个干预并列 → 非证据句
        if len(heads) >= 2 and sent.count(",") >= 3:
            continue
        if heads and tails:
            sent_hits.append((sid, heads, tails))
    # 协议 E1：只保留句内共现（禁止跨句兜底配对）
    found = {}
    for sid, heads, tails in sent_hits:
        for h in heads:
            for t in tails:
                if h != t and (h, t) not in found:
                    found[(h, t)] = sid
    # 配对级 Granularity：父 modality 的 (m,t) 在其子 stimulus 已有成对证据时让位
    if child_of:
        child_with_pairs = {h for (h, _t) in found if h in child_of}
        drop = {(m, t) for (m, t) in found
                if m in child_of.values() and any(child_of.get(c) == m for c in child_with_pairs)}
        for k in drop:
            found.pop(k, None)
    out = []
    for (h, t) in found:
        rel = benefit_relation.get(t, "改善")
        out.append({
            "head": node_name[h]["name"], "head_id": h,
            "relation": rel,
            "tail": node_name[t]["name"], "tail_id": t,
            "evidence_level": suggest_level(paper.get("pubtypes", []))[0],
            "category": sorted(route.get(h, [])) if route else [],
        })
    return out


def main():
    import sys as _sys
    if "--legacy-ok" not in _sys.argv:
        raise SystemExit(
            "build_dataset.py 是 v2.0 遗留构建器，会重写已废弃的 benchmark/gold_truth.jsonl 与\n"
            "benchmark/extraction_benchmark.jsonl，并覆盖现行 dataset/benchmark/{train,dev,test}.jsonl\n"
            "的设计前提。现行数据请用 scripts/pipeline/build_bench_splits.py 维护。\n"
            "确需重建旧合并版请显式加 --legacy-ok。")
    OUT.mkdir(parents=True, exist_ok=True)
    BENCH.mkdir(parents=True, exist_ok=True)
    kg = json.loads(KG_PATH.read_text(encoding="utf-8"))
    nodes = {n["id"]: n for n in kg["nodes"]}
    edges = kg["edges"]
    route = build_routing(nodes, edges)
    evidence = kg["evidence"]

    # ---- 1. literature.jsonl ----
    print("抓取图谱文献摘要...")
    graph_meta = fetch_graph_abstracts(sorted(evidence.keys()))
    print("  取回 %d/%d" % (len(graph_meta), len(evidence)))

    lit = {}
    for pmid, ev in evidence.items():
        m = graph_meta.get(pmid, {})
        rec = make_lit(pmid, m.get("title") or ev.get("title", ""), m.get("abstract", ""),
                       m.get("journal") or ev.get("journal", ""), m.get("year") or ev.get("year", ""),
                       m.get("doi") or ev.get("doi", ""), ev.get("types", []), [],
                       "graph_v1.1", ev.get("concl", ""))
        rec["title"] = rec["title"] or ev.get("title", "")
        lit[pmid] = rec

    # 挖掘候选 365 篇（已有摘要）
    mined = json.loads(MINED_PATH.read_text(encoding="utf-8"))["papers"]
    for p in mined:
        if p["pmid"] in lit:
            continue
        lit[p["pmid"]] = make_lit(p["pmid"], p["title"], p["abstract"], p["journal"], p["year"],
                                  p["doi"], p["pubtypes"], p.get("channels", []), "mined_20261109")

    # 大规模文献池
    pool = json.loads(POOL_PATH.read_text(encoding="utf-8"))["papers"]
    print("大规模文献池:", len(pool))
    cat_map = {}
    for ch, ids in json.loads(POOL_PATH.read_text(encoding="utf-8"))["categories"].items():
        for i in ids:
            cat_map.setdefault(i, []).append(ch)
    n_new = 0
    for p in pool:
        if p["pmid"] in lit:
            continue
        lit[p["pmid"]] = make_lit(p["pmid"], p["title"], p["abstract"], p["journal"], p["year"],
                                  p["doi"], p["pubtypes"], cat_map.get(p["pmid"], []), "pool_20261109")
        n_new += 1
    print("literature 总量:", len(lit), "(池新增 %d)" % n_new)

    with open(OUT / "literature.jsonl", "w", encoding="utf-8") as f:
        for r in lit.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # ---- 2. knowledge_triples.jsonl ----
    pmid2edges = defaultdict(list)
    for e in edges:
        for pmid in e.get("evidence", []):
            pmid2edges[pmid].append(e)
    triples = []
    for e in edges:
        h, t = nodes.get(e["source"], {}), nodes.get(e["target"], {})
        rec = {
            "triple_id": e["id"],
            "head": {"id": e["source"], "name": h.get("name", e["source"]), "type": h.get("type", "")},
            "relation": e["relation"],
            "tail": {"id": e["target"], "name": t.get("name", e["target"]), "type": t.get("type", "")},
            "note": e.get("note", ""), "effect": e.get("effect", ""),
            "population": e.get("population", ""), "n": e.get("n", ""),
            "evidence_level": e.get("level", ""), "level_name": e.get("level_name", ""),
            "evidence_pmids": e.get("evidence", []),
            "category": sorted(route.get(e["source"], [])),
            "evidence_titles": [evidence.get(p, {}).get("title", "") for p in e.get("evidence", [])],
        }
        rec["text"] = "(%s) --[%s]--> (%s) | 等级:%s | 依据:%s | 备注:%s%s" % (
            rec["head"]["name"], e["relation"], rec["tail"]["name"], rec["evidence_level"] or "N/A",
            "、".join(evidence.get(p, {}).get("title", "") for p in rec["evidence_pmids"]) or "N/A",
            rec["note"], (" | 效应:" + rec["effect"]) if rec["effect"] else "")
        triples.append(rec)
    with open(OUT / "knowledge_triples.jsonl", "w", encoding="utf-8") as f:
        for r in triples:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("knowledge_triples:", len(triples))

    # ---- 3. benchmark ----
    relations = sorted({e["relation"] for e in edges})
    (BENCH / "relations.json").write_text(json.dumps(relations, ensure_ascii=False, indent=1), encoding="utf-8")

    # benefit 节点的主导关系（图谱统计，确定性）
    benefit_relation = {}
    cnt = defaultdict(Counter)
    for e in edges:
        if nodes.get(e["target"], {}).get("type") == "benefit":
            cnt[e["target"]][e["relation"]] += 1
    for b, c in cnt.items():
        benefit_relation[b] = c.most_common(1)[0][0]

    alias = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
    head_res = {k: [re.compile(p, re.I) for p in v] for k, v in alias["head_aliases"].items()}
    tail_res = {k: [re.compile(p, re.I) for p in v] for k, v in alias["tail_aliases"].items()}
    global_trigger = re.compile(alias["trigger_words"], re.I)
    neg_res = re.compile("|".join(alias.get("negative_context", [])), re.I) \
        if alias.get("negative_context") else None

    # v2.0 感官本体：新类目头实体不在 KG 节点表中，名称取自 schema；类目路由按 id 前缀
    node_all = {**nodes, **{k: {"name": v, "type": "stimulus"}
                            for k, v in alias.get("head_names", {}).items()}}
    MOD_PREFIX = {"vis_": "视觉", "aud_": "听觉", "olf_": "嗅觉", "tas_": "味觉",
                  "tac_": "触觉", "per_": "知觉", "env_": "多感官环境"}
    route2 = dict(route)
    for hid in alias["head_aliases"]:
        for p, m in MOD_PREFIX.items():
            if hid.startswith(p):
                route2[hid] = [m]
                break
    print("negative_context 守卫:", len(alias.get("negative_context", [])), "条；类目头实体:",
          len(alias["head_aliases"]), "（v2.0 感官本体）")

    # 3a. 人工核验 gold（87 篇）
    core_tasks, core_golds = [], []
    for pmid, edgelist in sorted(pmid2edges.items()):
        L = lit.get(pmid)
        if not L or not L["abstract"]:
            continue
        tid = "core_%s" % pmid
        gold = [{"head": nodes.get(e["source"], {}).get("name", e["source"]), "head_id": e["source"],
                 "relation": e["relation"],
                 "tail": nodes.get(e["target"], {}).get("name", e["target"]), "tail_id": e["target"],
                 "evidence_level": e.get("level", ""),
                 "category": sorted(route.get(e["source"], []))} for e in edgelist]
        core_tasks.append({"task_id": tid, "pmid": pmid, "split": "test_core", "gold_type": "human_curated",
                           "input": {"title": L["title"], "abstract": L["abstract"], "year": L["year"],
                                     "pubtypes": L["pubtypes"]},
                           "instruction": "从摘要中抽取 (头实体, 关系, 尾实体) 三元组；实体用图谱节点名或自然语言表达；关系取自 relations.json。",
                           "allowed_relations": relations, "gold_n": len(gold)})
        core_golds.append({"task_id": tid, "pmid": pmid, "split": "test_core",
                           "gold_type": "human_curated", "gold": gold})
    with open(BENCH / "gold_core_human.jsonl", "w", encoding="utf-8") as f:
        for g in core_golds:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print("gold_core(人工): %d tasks, %d triples" % (len(core_tasks), sum(g["gold_n"] for g in core_tasks)))

    # 全文级具体性规则：stimulus 子节点 → 父 modality 让位（modality--包含-->stimulus）
    child_of = {e["target"]: e["source"] for e in edges
                if e["relation"] == "包含" and nodes.get(e["source"], {}).get("type") == "modality"
                and nodes.get(e["target"], {}).get("type") == "stimulus"}

    # 3b. 远程监督 gold（大规模）
    ds_pool = [p for p in lit.values() if p["source"] != "graph_v1.1" and p["abstract"]]
    print("远程监督标注中... 候选 %d 篇" % len(ds_pool))
    # 人工 review 裁定：drop_all 整篇作废 / expect 强制等于人工确认的三元组
    # v2.0：test_review 台账中的 drop_all / drop_scope 一并纳入（train 纯度同步保证）
    rulings = {}
    if RULINGS_PATH.exists():
        for r in json.loads(RULINGS_PATH.read_text(encoding="utf-8"))["rulings"]:
            rulings[str(r["pmid"])] = r
    ledger_path = BENCH / "test_review.jsonl"
    if ledger_path.exists():
        for r in load_jsonl_local(ledger_path):
            if r.get("verdict") in ("drop_all", "drop_scope") and str(r["pmid"]) not in rulings:
                rulings[str(r["pmid"])] = {"verdict": "drop_all",
                                           "reason": "test_review:" + r.get("reason", "")[:80]}
    n_ruled_drop = n_ruled_fix = 0

    def expand_ruled(t):
        """把裁定里的 (head_id, relation, tail_id) 展开成完整三元组。"""
        hn = node_all.get(t["head_id"], {})
        tn = node_all.get(t["tail_id"], {})
        return {"head": hn.get("name", t["head_id"]), "head_id": t["head_id"],
                "relation": t["relation"],
                "tail": tn.get("name", t["tail_id"]), "tail_id": t["tail_id"],
                "evidence_level": "C"}

    ds_tasks = []
    for L in ds_pool:
        paper = {"title": L["title"], "abstract": L["abstract"], "pubtypes": L["pubtypes"]}
        trip = annotate(paper, head_res, tail_res, node_all, benefit_relation, None, global_trigger,
                        neg_res=neg_res, route=route2, child_of=None)
        rule = rulings.get(str(L["pmid"]))
        if rule:
            if rule["verdict"] == "drop_all":
                if trip:
                    n_ruled_drop += 1
                trip = []
            elif rule["verdict"] == "expect":
                want = sorted((t["head_id"], t["tail_id"]) for t in rule["expected"])
                have = sorted((t["head_id"], t["tail_id"]) for t in trip)
                if want != have:
                    n_ruled_fix += 1
                trip = [expand_ruled(t) for t in rule["expected"]]
        if trip:
            tid = "ds_%s" % L["pmid"]
            ds_tasks.append({"task_id": tid, "pmid": L["pmid"], "gold_type": "distant_supervision",
                             "channels": L.get("channels", []),
                             "input": {"title": L["title"], "abstract": L["abstract"], "year": L["year"],
                                       "pubtypes": L["pubtypes"]},
                             "instruction": "从摘要中抽取 (头实体, 关系, 尾实体) 三元组；实体用图谱节点名或自然语言表达；关系取自 relations.json。",
                             "allowed_relations": relations, "gold_n": len(trip),
                             "gold": trip})
    print("远程监督命中: %d / %d (%.0f%%)" % (len(ds_tasks), len(ds_pool), 100 * len(ds_tasks) / max(1, len(ds_pool))))
    if rulings:
        print("人工裁定生效: %d 条登记，drop_all 剔除 %d 篇，expect 改写 %d 篇" % (
            len(rulings), n_ruled_drop, n_ruled_fix))

    rng = random.Random(SEED)
    rng.shuffle(ds_tasks)
    need = N_TRAIN + N_DEV + N_TEST
    if len(ds_tasks) < need:
        print("警告: 命中 %d < 需要 %d，全量使用并在 stats 记录缺口" % (len(ds_tasks), need))
    train = ds_tasks[:N_TRAIN]
    dev = ds_tasks[N_TRAIN:N_TRAIN + N_DEV]
    test = ds_tasks[N_TRAIN + N_DEV:N_TRAIN + N_DEV + N_TEST]
    for t, sp in [(t, "train") for t in train] + [(t, "dev") for t in dev] + [(t, "test") for t in test]:
        t["split"] = sp

    all_tasks = train + dev + test
    with open(BENCH / "extraction_benchmark.jsonl", "w", encoding="utf-8") as f:
        for t in all_tasks:
            o = {k: v for k, v in t.items() if k != "gold"}
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    with open(BENCH / "gold_truth.jsonl", "w", encoding="utf-8") as f:
        for t in all_tasks:
            f.write(json.dumps({"task_id": t["task_id"], "pmid": t["pmid"], "split": t["split"],
                                "gold_type": t["gold_type"], "gold": t["gold"]}, ensure_ascii=False) + "\n")

    sc = Counter(t["split"] for t in all_tasks)
    print("benchmark: train=%d dev=%d test=%d, gold三元组=%d" % (
        sc["train"], sc["dev"], sc["test"], sum(t["gold_n"] for t in all_tasks)))

    # ---- 4. stats ----
    stats = {
        "built_at": datetime.now().isoformat(), "seed": SEED,
        "literature": len(lit),
        "literature_by_source": dict(Counter(r["source"] for r in lit.values())),
        "literature_with_if": sum(1 for r in lit.values() if r["journal_if"] is not None),
        "triples": len(triples),
        "edges_with_evidence": sum(1 for e in edges if e.get("evidence")),
        "benchmark_train": sc["train"], "benchmark_dev": sc["dev"], "benchmark_test": sc["test"],
        "benchmark_gold_triples": sum(t["gold_n"] for t in all_tasks),
        "gold_core_tasks": len(core_tasks),
        "gold_core_triples": sum(len(g["gold"]) for g in core_golds),
        "relations": relations,
        "target_sizes": {"train": N_TRAIN, "dev": N_DEV, "test": N_TEST},
        "shortfall": max(0, need - len(ds_tasks)),
    }
    (OUT / "dataset_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "relations"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
