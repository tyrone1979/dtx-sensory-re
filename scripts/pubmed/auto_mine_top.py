# -*- coding: utf-8 -*-
"""
auto_mine_top.py — 自动挖掘高IF顶刊的数字疗愈循证文献，增量完善知识图谱。

流程：
  1) 按六大疗愈通道（视觉/听觉/味觉/嗅觉/触觉/知觉）向 PubMed 发起检索
     —— 两轮检索：A 主题宽检索(按相关度) → 期刊白名单过滤；
                   B 顶刊限定检索（通道关键词 AND 顶刊[Journal] OR 子句）。
  2) 按期刊影响因子(IF)分层打分：S(IF≥20) / A(10≤IF<20) / B(5≤IF<10)。
  3) 按文献类型判定证据等级建议：Meta/系统评价→A，RCT/类实验→B，观察性→C，综述/机制→D。
  4) 与现有 knowledge_graph.json 的 evidence 键(PMID) 去重，仅保留增量候选。
  5) 输出：
     - tmp/source/pubmed/mined_papers.json        全量候选元数据
     - output/知识挖掘_高IF期刊候选_*.md    人读报告（按通道分组）
     - tmp/source/pubmed/candidates_evidence.json 可合并进图谱的 evidence 候选条目

用法：
  python auto_mine_top.py [--days N]      # N=只看近N天，默认不限
  可配置 API_KEY（NCBI api_key，免费申请后 10 req/s）。
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(r"D:/projects/digital-therapeutics")
OUT_DIR = ROOT / "data" / "pubmed"
KG_PATH = ROOT / "output" / "data" / "knowledge_graph.json"
REPORT_PATH = ROOT / "output" / ("知识挖掘_高IF期刊候选_%s.md" % datetime.now().strftime("%Y%m%d"))
MINED_PATH = OUT_DIR / "mined_papers.json"
CAND_PATH = OUT_DIR / "candidates_evidence.json"

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
API_KEY = ""  # 可填入 NCBI api_key 提升限速

# ----------------------------------------------------------------------------
# 1. 期刊白名单（IF 为 2024 JCR 约值，标注 ≈；字段为所属领域）
# ----------------------------------------------------------------------------
JOURNALS = {
    # ——— 医学综合顶刊（S） ———
    "Lancet (London, England)": {"if": 98, "field": "综合医学"},
    "The New England journal of medicine": {"if": 54, "field": "综合医学"},
    "JAMA": {"if": 63, "field": "综合医学"},
    "BMJ (Clinical research ed.)": {"if": 93, "field": "综合医学"},
    "Nature medicine": {"if": 58, "field": "综合医学"},
    "JAMA internal medicine": {"if": 22, "field": "综合医学"},
    "Annals of internal medicine": {"if": 19, "field": "综合医学"},
    "JAMA network open": {"if": 10, "field": "综合医学"},
    "eClinicalMedicine": {"if": 15, "field": "综合医学"},
    "PLoS medicine": {"if": 11, "field": "综合医学"},
    # ——— 精神/心理（S/A） ———
    "World psychiatry": {"if": 60, "field": "精神医学"},
    "JAMA psychiatry": {"if": 22, "field": "精神医学"},
    "The Lancet. Psychiatry": {"if": 26, "field": "精神医学"},
    "The Lancet. Public health": {"if": 25, "field": "公共卫生"},
    "The Lancet. Planetary health": {"if": 25, "field": "环境健康"},
    "Molecular psychiatry": {"if": 10, "field": "精神医学"},
    "The American journal of psychiatry": {"if": 14, "field": "精神医学"},
    "Psychotherapy and psychosomatics": {"if": 16, "field": "心理治疗"},
    "Biological psychiatry": {"if": 10, "field": "神经精神"},
    "Nature human behaviour": {"if": 22, "field": "行为科学"},
    "Nature mental health": {"if": 15, "field": "精神医学"},
    # ——— 数字健康（A） ———
    "The Lancet. Digital health": {"if": 23, "field": "数字健康"},
    "NPJ digital medicine": {"if": 12, "field": "数字健康"},
    "Journal of medical Internet research": {"if": 6, "field": "数字健康"},
    "JMIR mental health": {"if": 5, "field": "数字健康"},
    # ——— 环境/行为/神经（A/B） ———
    "Environment international": {"if": 11, "field": "环境健康"},
    "Science of the total environment": {"if": 9, "field": "环境健康"},
    "Environmental research": {"if": 8, "field": "环境健康"},
    "Landscape and urban planning": {"if": 9, "field": "景观规划"},
    "Journal of environmental psychology": {"if": 7, "field": "环境心理"},
    "Health & place": {"if": 4, "field": "健康地理"},
    "Neuroscience and biobehavioral reviews": {"if": 8, "field": "神经科学"},
    "Trends in cognitive sciences": {"if": 16, "field": "认知科学"},
    "Trends in neurosciences": {"if": 12, "field": "神经科学"},
    "Nature reviews. Neuroscience": {"if": 25, "field": "神经科学"},
    "Annual review of psychology": {"if": 25, "field": "心理学"},
    "Brain, behavior, and immunity": {"if": 9, "field": "心理神经免疫"},
    "Psychosomatic medicine": {"if": 4, "field": "心身医学"},
    "Annals of behavioral medicine": {"if": 5, "field": "行为医学"},
    # ——— 睡眠/护理/专病（A/B） ———
    "Sleep medicine reviews": {"if": 11, "field": "睡眠"},
    "Sleep": {"if": 6, "field": "睡眠"},
    "International journal of nursing studies": {"if": 8, "field": "护理"},
    "Journal of affective disorders": {"if": 5, "field": "情感障碍"},
    "JAMA pediatrics": {"if": 24, "field": "儿科"},
}

# 常见 ISO 缩写 → 白名单全名（PubMed [Journal] 检索/元数据匹配用）
J_ALIAS = {
    "lancet": "Lancet (London, England)",
    "lancet psychiatry": "The Lancet. Psychiatry",
    "lancet public health": "The Lancet. Public health",
    "lancet planet health": "The Lancet. Planetary health",
    "lancet digital health": "The Lancet. Digital health",
    "n engl j med": "The New England journal of medicine",
    "jama": "JAMA",
    "bmj": "BMJ (Clinical research ed.)",
    "jama intern med": "JAMA internal medicine",
    "ann intern med": "Annals of internal medicine",
    "jama netw open": "JAMA network open",
    "eclinmed": "eClinicalMedicine",
    "plos med": "PLoS medicine",
    "world psychiatry": "World psychiatry",
    "jama psychiatry": "JAMA psychiatry",
    "mol psychiatry": "Molecular psychiatry",
    "am j psychiatry": "The American journal of psychiatry",
    "psychother psychosom": "Psychotherapy and psychosomatics",
    "biol psychiatry": "Biological psychiatry",
    "nat hum behav": "Nature human behaviour",
    "nat mental health": "Nature mental health",
    "nat med": "Nature medicine",
    "npj digit med": "NPJ digital medicine",
    "j med internet res": "Journal of medical Internet research",
    "jmir mental health": "JMIR mental health",
    "environ int": "Environment international",
    "sci total environ": "Science of the total environment",
    "environ res": "Environmental research",
    "landsc urban plan": "Landscape and urban planning",
    "j environ psychol": "Journal of environmental psychology",
    "health place": "Health & place",
    "neurosci biobehav rev": "Neuroscience and biobehavioral reviews",
    "trends cogn sci": "Trends in cognitive sciences",
    "trends neurosci": "Trends in neurosciences",
    "nat rev neurosci": "Nature reviews. Neuroscience",
    "annu rev psychol": "Annual review of psychology",
    "brain behav immun": "Brain, behavior, and immunity",
    "psychosom med": "Psychosomatic medicine",
    "ann behav med": "Annals of behavioral medicine",
    "sleep med rev": "Sleep medicine reviews",
    "sleep": "Sleep",
    "int j nurs stud": "International journal of nursing studies",
    "j affect disord": "Journal of affective disorders",
    "jama pediatr": "JAMA pediatrics",
}

TIER_OF = lambda IF: "S" if IF >= 20 else ("A" if IF >= 10 else "B")
TIER_SCORE = {"S": 3.0, "A": 2.0, "B": 1.0}
TIER_LABEL = {"S": "S级顶刊(IF≥20)", "A": "A级(IF 10-20)", "B": "B级(IF 5-10)"}

# ----------------------------------------------------------------------------
# 2. 检索式（按通道扩展）
# ----------------------------------------------------------------------------
QUERIES = {
    "visual": [
        '("green space"[tiab] OR "green spaces"[tiab] OR "greenness"[tiab]) AND (restoration[tiab] OR "attention restoration"[tiab] OR recovery[tiab] OR "mental health"[tiab])',
        '("window view"[tiab] OR "natural view"[tiab] OR "views of nature"[tiab] OR "green view"[tiab]) AND (stress[tiab] OR recovery[tiab] OR restoration[tiab] OR sleep[tiab])',
        '"blue space"[tiab] AND (health[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR restoration[tiab])',
        'color[tiab] AND (mood[tiab] OR emotion[tiab] OR anxiety[tiab] OR arousal[tiab]) AND (environment[tiab] OR interior[tiab] OR psychology[tiab])',
        '("biophilic design"[tiab] OR "nature indoors"[tiab] OR "indoor plants"[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR recovery[tiab])',
        'daylight[tiab] AND (sleep[tiab] OR mood[tiab] OR depression[tiab] OR "cortisol"[tiab])',
        '("healing garden"[tiab] OR "horticultural therapy"[tiab] OR "garden therapy"[tiab]) AND (stress[tiab] OR mood[tiab] OR wellbeing[tiab] OR recovery[tiab])',
        '("natural materials"[tiab] OR "wood interior"[tiab] OR "wooden interior"[tiab]) AND (stress[tiab] OR relaxation[tiab] OR wellbeing[tiab])',
        '("landscape preference"[tiab] OR "scene complexity"[tiab] OR "visual complexity"[tiab]) AND (restoration[tiab] OR preference[tiab] OR stress[tiab])',
        '("street trees"[tiab] OR "urban greenery"[tiab] OR "urban park"[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR restoration[tiab] OR "mental health"[tiab])',
        '("interior design"[tiab] OR "office design"[tiab] OR "room design"[tiab]) AND (stress[tiab] OR wellbeing[tiab] OR productivity[tiab] OR mood[tiab])',
        '("nature imagery"[tiab] OR "landscape image"[tiab] OR "nature video"[tiab]) AND (stress[tiab] OR restoration[tiab] OR mood[tiab])',
        '("daylighting"[tiab] OR "windowless"[tiab] OR "artificial lighting"[tiab]) AND (comfort[tiab] OR mood[tiab] OR sleep[tiab] OR wellbeing[tiab])',
    ],
    "auditory": [
        '"music therapy"[tiab] AND (anxiety[tiab] OR depression[tiab] OR cortisol[tiab] OR sleep[tiab]) AND (randomized[tiab] OR "meta-analysis"[tiab] OR review[tiab])',
        '("nature sounds"[tiab] OR "natural sound"[tiab] OR birdsong[tiab]) AND (stress[tiab] OR recovery[tiab] OR restoration[tiab])',
        'soundscape[tiab] AND (health[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR restoration[tiab] OR "perceived restorativeness"[tiab])',
        'noise[tiab] AND health[tiab] AND (sleep[tiab] OR stress[tiab] OR cardiovascular[tiab])',
        '"music intervention"[tiab] AND (pain[tiab] OR anxiety[tiab]) AND (trial[tiab] OR "meta-analysis"[tiab])',
        '("white noise"[tiab] OR "pink noise"[tiab]) AND (sleep[tiab] OR "sleep quality"[tiab] OR relaxation[tiab] OR concentration[tiab])',
        '("singing bowl"[tiab] OR "gong"[tiab] OR "bell sound"[tiab]) AND (relaxation[tiab] OR stress[tiab] OR meditation[tiab])',
        '("music medicine"[tiab] OR "music-based"[tiab]) AND (anxiety[tiab] OR pain[tiab] OR stress[tiab])',
        '("ocean sound"[tiab] OR "rain sound"[tiab] OR "water sound"[tiab]) AND (relaxation[tiab] OR sleep[tiab] OR stress[tiab])',
        '("ambient sound"[tiab] OR "environmental sound"[tiab]) AND (restoration[tiab] OR relaxation[tiab] OR wellbeing[tiab])',
        '("music tempo"[tiab] OR "music preference"[tiab] OR "musical tempo"[tiab]) AND (arousal[tiab] OR mood[tiab] OR relaxation[tiab])',
    ],
    "gustatory": [
        'taste[tiab] AND (emotion[tiab] OR mood[tiab] OR pleasure[tiab] OR depression[tiab])',
        'diet[tiab] AND ("mental health"[tiab] OR depression[tiab]) AND ("dietary pattern"[tiab] OR "mediterranean"[tiab]) AND (randomized[tiab] OR "meta-analysis"[tiab])',
        'tea[tiab] AND (anxiety[tiab] OR stress[tiab] OR mood[tiab] OR relaxation[tiab])',
        '("sweet taste"[tiab] OR umami[tiab]) AND (appetite[tiab] OR emotion[tiab] OR mood[tiab])',
        '"gut-brain"[tiab] AND (diet[tiab] OR nutrition[tiab]) AND (mood[tiab] OR anxiety[tiab] OR depression[tiab])',
        '"herbal tea"[tiab] AND (sleep[tiab] OR anxiety[tiab] OR relaxation[tiab] OR mood[tiab])',
        '("mindful eating"[tiab] OR "sensory food"[tiab]) AND (wellbeing[tiab] OR "well-being"[tiab] OR eating[tiab])',
        '("fermented food"[tiab] OR "fermented foods"[tiab] OR probiotic[tiab]) AND (anxiety[tiab] OR stress[tiab] OR mood[tiab])',
        '("spicy food"[tiab] OR capsaicin[tiab]) AND (mood[tiab] OR pain[tiab] OR "well-being"[tiab])',
        '("comfort food"[tiab] OR "food reward"[tiab]) AND (mood[tiab] OR emotion[tiab] OR stress[tiab])',
    ],
    "olfactory": [
        'aromatherapy[tiab] AND (anxiety[tiab] OR sleep[tiab] OR stress[tiab]) AND (randomized[tiab] OR "meta-analysis"[tiab] OR "systematic review"[tiab])',
        'lavender[tiab] AND (sleep[tiab] OR anxiety[tiab] OR stress[tiab])',
        '"essential oil"[tiab] AND (anxiety[tiab] OR stress[tiab] OR cortisol[tiab] OR sleep[tiab])',
        '(olfactory[tiab] OR olfaction[tiab]) AND (emotion[tiab] OR memory[tiab] OR mood[tiab]) AND (wellbeing[tiab] OR "well-being"[tiab] OR anxiety[tiab] OR depression[tiab])',
        '("forest air"[tiab] OR phytoncide[tiab] OR "monoterpene"[tiab]) AND (stress[tiab] OR immune[tiab] OR relaxation[tiab])',
        '("peppermint"[tiab] OR "citrus scent"[tiab]) AND (cognitive[tiab] OR fatigue[tiab] OR alertness[tiab] OR mood[tiab])',
        'scent[tiab] AND ("stress"[tiab] OR performance[tiab] OR "mood"[tiab]) AND (exposure[tiab] OR inhalation[tiab])',
        '(rosemary[tiab] OR jasmine[tiab] OR chamomile[tiab]) AND (sleep[tiab] OR anxiety[tiab] OR mood[tiab] OR stress[tiab])',
        '(fragrance[tiab] OR odor[tiab] OR odour[tiab]) AND (emotion[tiab] OR comfort[tiab] OR wellbeing[tiab]) AND (indoor[tiab] OR environmental[tiab] OR ambient[tiab])',
        'incense[tiab] AND (meditation[tiab] OR relaxation[tiab] OR stress[tiab])',
    ],
    "tactile": [
        '"massage therapy"[tiab] AND (anxiety[tiab] OR pain[tiab] OR cortisol[tiab] OR depression[tiab]) AND ("meta-analysis"[tiab] OR review[tiab] OR randomized[tiab])',
        '(balneotherapy[tiab] OR "thermal bath"[tiab] OR "hot spring"[tiab]) AND (health[tiab] OR stress[tiab] OR sleep[tiab] OR pain[tiab])',
        'touch[tiab] AND (wellbeing[tiab] OR "well-being"[tiab] OR stress[tiab] OR oxytocin[tiab])',
        '(hydrotherapy[tiab] OR "water immersion"[tiab]) AND (sleep[tiab] OR relaxation[tiab] OR recovery[tiab])',
        '"weighted blanket"[tiab] AND (sleep[tiab] OR anxiety[tiab] OR insomnia[tiab])',
        '("foot bath"[tiab] OR "foot soak"[tiab]) AND (sleep[tiab] OR relaxation[tiab] OR fatigue[tiab])',
        '("acupressure"[tiab] OR "acupoint massage"[tiab]) AND (pain[tiab] OR anxiety[tiab] OR sleep[tiab] OR nausea[tiab])',
        '("animal-assisted"[tiab] OR "pet therapy"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR wellbeing[tiab])',
        '(warmth[tiab] OR "thermal comfort"[tiab]) AND (comfort[tiab] OR relaxation[tiab] OR sleep[tiab])',
        '(knitting[tiab] OR "textile"[tiab] OR "tactile material"[tiab]) AND (wellbeing[tiab] OR stress[tiab] OR calm[tiab])',
    ],
    "perceptual": [
        '"mindfulness meditation"[tiab] AND (anxiety[tiab] OR stress[tiab]) AND ("meta-analysis"[tiab] OR "systematic review"[tiab] OR randomized[tiab])',
        '"virtual reality"[tiab] AND (pain[tiab] OR anxiety[tiab] OR relaxation[tiab]) AND (therapy[tiab] OR intervention[tiab])',
        '("forest bathing"[tiab] OR "shinrin-yoku"[tiab] OR "forest therapy"[tiab]) AND (stress[tiab] OR "cortisol"[tiab] OR immune[tiab] OR mood[tiab])',
        '("nature-based intervention"[tiab] OR "nature therapy"[tiab]) AND (mental health[tiab] OR wellbeing[tiab] OR "well-being"[tiab])',
        '("digital therapeutic"[tiab] OR "prescription digital therapeutic"[tiab] OR "digital mental health"[tiab]) AND (efficacy[tiab] OR trial[tiab] OR review[tiab])',
        '("wellness tourism"[tiab] OR "health resort"[tiab]) AND (wellbeing[tiab] OR "well-being"[tiab] OR health[tiab])',
        '"breathing exercise"[tiab] AND (anxiety[tiab] OR stress[tiab] OR "heart rate variability"[tiab])',
        '("virtual nature"[tiab] OR "VR nature"[tiab] OR "virtual forest"[tiab]) AND (stress[tiab] OR relaxation[tiab] OR mood[tiab])',
        '("chromotherapy"[tiab] OR "color therapy"[tiab] OR "lighting color"[tiab]) AND (mood[tiab] OR relaxation[tiab] OR sleep[tiab])',
        '(yoga[tiab] OR "tai chi"[tiab] OR qigong[tiab]) AND (stress[tiab] OR anxiety[tiab] OR sleep[tiab]) AND (trial[tiab] OR "meta-analysis"[tiab])',
        '("art therapy"[tiab] OR "expressive arts"[tiab]) AND (anxiety[tiab] OR stress[tiab] OR wellbeing[tiab])',
        '("nature walk"[tiab] OR "forest walk"[tiab] OR "park visit"[tiab]) AND (stress[tiab] OR mood[tiab] OR wellbeing[tiab])',
        '"sound therapy"[tiab] AND (tinnitus[tiab] OR stress[tiab] OR sleep[tiab] OR relaxation[tiab])',
        '"music listening"[tiab] AND (stress[tiab] OR anxiety[tiab] OR mood[tiab])',
        '("app-based"[tiab] OR "smartphone app"[tiab] OR "mobile application"[tiab]) AND (stress[tiab] OR anxiety[tiab] OR meditation[tiab])',
        '("guided imagery"[tiab] OR "progressive muscle relaxation"[tiab] OR "autogenic training"[tiab]) AND (anxiety[tiab] OR stress[tiab] OR sleep[tiab] OR pain[tiab])',
        '("floatation"[tiab] OR "sensory deprivation"[tiab] OR "flotation tank"[tiab]) AND (relaxation[tiab] OR stress[tiab] OR anxiety[tiab])',
        '("light exposure"[tiab] OR "bright light"[tiab]) AND (alertness[tiab] OR mood[tiab] OR sleep[tiab]) AND (healthy[tiab] OR adults[tiab] OR participants[tiab])',
        '("yoga nidra"[tiab] OR "body scan"[tiab] OR "mindfulness app"[tiab]) AND (stress[tiab] OR sleep[tiab] OR anxiety[tiab])',
    ],
    # 顶刊定向挖掘：24 本领域顶刊，[jour] 字段检索 + 域内主题词过滤
    "toplevel": [
        f'"{j}"[jour] AND (nature[tiab] OR green[tiab] OR "green space"[tiab] OR wellbeing[tiab] OR "well-being"[tiab] OR stress[tiab] OR sleep[tiab] OR mood[tiab] OR music[tiab] OR mindfulness[tiab] OR "virtual reality"[tiab] OR restoration[tiab] OR "mental health"[tiab] OR loneliness[tiab] OR relaxation[tiab] OR aromatherapy[tiab] OR "thermal"[tiab])'
        for j in [
            "Nature", "Nature Human Behaviour", "Nature Mental Health", "Nature Medicine",
            "Nature Communications", "Science", "The Lancet", "Lancet Psychiatry",
            "Lancet Planetary Health", "Lancet Digital Health", "JAMA", "JAMA Psychiatry",
            "JAMA Network Open", "BMJ", "BMJ Mental Health", "PNAS",
            "Psychological Bulletin", "Psychological Science", "Sleep Medicine Reviews",
            "Environment International", "Science of the Total Environment",
            "Landscape and Urban Planning", "Health & Place", "JMIR",
            "Journal of Medical Internet Research", "JMIR Mental Health", "npj Digital Medicine",
            "Neuroscience and Biobehavioral Reviews", "Trends in Cognitive Sciences",
            "Journal of Environmental Psychology", "Building and Environment", "Indoor Air",
            "EClinicalMedicine", "BMC Medicine", "Cochrane Database of Systematic Reviews",
        ]
    ],
}

# ----------------------------------------------------------------------------
# 3. PubMed API 封装
# ----------------------------------------------------------------------------
def get(url, retry=3):
    for i in range(retry):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dt-kg-miner/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == retry - 1:
                print("  ! 请求失败:", str(e)[:120])
                return ""
            time.sleep(1.5)


def esearch(term, retmax=40, mindate=None, maxdate=None, sort="relevance"):
    params = {
        "db": "pubmed", "term": term, "retmax": retmax,
        "retmode": "json", "sort": sort,
    }
    if API_KEY:
        params["api_key"] = API_KEY
    if mindate:
        params["mindate"] = mindate
        params["maxdate"] = maxdate or "3000"
        params["datetype"] = "pdat"
    data = json.loads(get(BASE + "esearch.fcgi?" + urllib.parse.urlencode(params)) or "{}")
    r = data.get("esearchresult", {})
    return r.get("idlist", []), int(r.get("count", "0") or 0)


def efetch(ids):
    if not ids:
        return ""
    params = {"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}
    if API_KEY:
        params["api_key"] = API_KEY
    return get(BASE + "efetch.fcgi?" + urllib.parse.urlencode(params))


def parse_articles(xml_text):
    root = ET.fromstring(xml_text)
    arts = []
    for art in root.iter("PubmedArticle"):
        mc = art.find("MedlineCitation")
        if mc is None:
            continue
        pmid = mc.findtext("PMID") or ""
        a = mc.find("Article")
        title = ""
        journal = ""
        iso = ""
        year = ""
        if a is not None:
            t = a.find("ArticleTitle")
            if t is not None:
                title = "".join(t.itertext()).strip()
            j = a.find("Journal")
            if j is not None:
                journal = j.findtext("Title") or ""
                iso = j.findtext("ISOAbbreviation") or ""
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
        if a is not None:
            el = a.find("ELocationID[@IdType='doi']")
            if el is not None and el.text:
                doi = el.text
        if not doi:
            pd = art.find("PubmedData/ArticleIdList")
            if pd is not None:
                for aid in pd.findall("ArticleId"):
                    if aid.get("IdType") == "doi" and aid.text:
                        doi = aid.text
                        break
        arts.append({
            "pmid": pmid, "title": title, "journal": journal, "iso": iso,
            "year": year, "abstract": " ".join(abstract_parts),
            "pubtypes": pubtypes, "doi": doi,
        })
    return arts


def norm_journal(name):
    """匹配白名单：先精确（归一化后），再查 ISO 缩写别名表。"""
    if not name:
        return None
    s = re.sub(r"[^a-z0-9& ]", " ", name.lower())
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    for jname in JOURNALS:
        k = re.sub(r"[^a-z0-9& ]", " ", jname.lower())
        k = re.sub(r"\s+", " ", k).strip()
        k = re.sub(r"^the ", "", k)
        if s == k:
            return jname
    return J_ALIAS.get(s)


# ----------------------------------------------------------------------------
# 4. 证据等级判定与打分
# ----------------------------------------------------------------------------
def suggest_level(pubtypes):
    pt = [p.lower() for p in pubtypes]
    if any("meta-analysis" in p for p in pt):
        return "A", "高（系统评价/Meta分析）"
    if any("systematic review" in p for p in pt):
        return "A", "高（系统评价/Meta分析）"
    if any("randomized controlled trial" in p for p in pt):
        return "B", "中高（RCT/类实验）"
    if any("clinical trial" in p for p in pt) or any("comparative study" in p for p in pt):
        return "B", "中高（RCT/类实验）"
    if any("review" in p for p in pt):
        return "D", "参考（综述/机制/共识）"
    return "C", "中（观察性研究）"


def score_paper(meta):
    sc = 0.0
    jm = JOURNALS.get(meta["_journal"])
    sc += TIER_SCORE[TIER_OF(jm["if"])]
    pt = [p.lower() for p in meta["pubtypes"]]
    if any("meta-analysis" in p for p in pt):
        sc += 3.0
    elif any("systematic review" in p for p in pt):
        sc += 2.5
    elif any("randomized controlled trial" in p for p in pt):
        sc += 2.0
    elif any("clinical trial" in p for p in pt):
        sc += 1.5
    elif any("review" in p for p in pt):
        sc += 1.0
    try:
        y = int(meta["year"])
        now = datetime.now().year
        if y >= now - 2:
            sc += 1.0
        elif y >= now - 5:
            sc += 0.5
    except ValueError:
        pass
    return round(sc, 2)


# ----------------------------------------------------------------------------
# 5. 主流程
# ----------------------------------------------------------------------------
def load_existing_pmids():
    pmids = set()
    if KG_PATH.exists():
        d = json.loads(KG_PATH.read_text(encoding="utf-8"))
        for k in (d.get("evidence") or {}):
            if re.fullmatch(r"\d{6,9}", k):
                pmids.add(k)
    return pmids


def journal_or_clause():
    return "(" + " OR ".join('"%s"[Journal]' % j for j in sorted(JOURNALS)) + ")"


def main():
    days = None
    if "--days" in sys.argv:
        days = sys.argv[sys.argv.index("--days") + 1]

    existing = load_existing_pmids()
    print("现有图谱 evidence 条目:", len(existing))

    journal_clause = journal_or_clause()
    results = {}   # pmid -> meta
    stats = {}

    def search_batch(channel, terms, journal_restricted):
        found = []
        for term in terms:
            q = term if not journal_restricted else "(%s) AND %s" % (term, journal_clause)
            ids, count = esearch(q, retmax=30 if not journal_restricted else 25,
                                 mindate=days)
            print("  [%s%s] %d 命中/%d 取回  %s" % (
                channel, "+J" if journal_restricted else "  ", count, len(ids), term[:60]))
            found.extend(ids)
            time.sleep(0.4)
        return found

    for channel, terms in QUERIES.items():
        print("\n== %s ==" % channel)
        # A. 宽检索 + 白名单过滤；B. 顶刊限定检索
        for jrestrict in (False, True):
            ids = search_batch(channel, terms, jrestrict)
            seen, uniq = set(), []
            for i in ids:
                if i not in seen and i not in existing:
                    seen.add(i)
                    uniq.append(i)
            for i in range(0, len(uniq), 40):
                xml_text = efetch(uniq[i:i + 40])
                if xml_text:
                    for p in parse_articles(xml_text):
                        jn = norm_journal(p["journal"]) or norm_journal(p["iso"])
                        if jn:
                            p["_journal"] = jn
                            p["if"] = JOURNALS[jn]["if"]
                            p["field"] = JOURNALS[jn]["field"]
                            p["tier"] = TIER_OF(JOURNALS[jn]["if"])
                            p["channels"] = [channel]
                            p["_score"] = score_paper(p)
                            old = results.get(p["pmid"])
                            if old:
                                if channel not in old["channels"]:
                                    old["channels"].append(channel)
                                old["_score"] = max(old["_score"], p["_score"])
                            else:
                                results[p["pmid"]] = p
                time.sleep(0.4)
        stats[channel] = sum(1 for p in results.values() if channel in p["channels"])

    papers = sorted(results.values(), key=lambda p: -p["_score"])
    for p in papers:
        lvl, lname = suggest_level(p["pubtypes"])
        p["suggest_level"] = lvl
        p["suggest_level_name"] = lname

    # ---- 输出 ----
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    MINED_PATH.write_text(json.dumps(
        {"mined_at": datetime.now().isoformat(), "days_limit": days,
         "existing_pmids": len(existing), "count": len(papers), "papers": papers},
        ensure_ascii=False, indent=1), encoding="utf-8")

    cand = []
    for p in papers:
        cand.append({
            "pmid": p["pmid"], "level": p["suggest_level"],
            "level_name": p["suggest_level_name"], "title": p["title"],
            "journal": p["journal"], "year": p["year"], "doi": p["doi"],
            "url": "https://pubmed.ncbi.nlm.nih.gov/%s/" % p["pmid"],
            "types": p["pubtypes"], "channels": p["channels"],
            "tier": p["tier"], "if_approx": p["if"],
            "concl": "",  # 待人工/LLM 提炼中文结论
        })
    CAND_PATH.write_text(json.dumps(cand, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- 报告 ----
    lines = [
        "# 知识挖掘报告 · 高IF期刊候选",
        "",
        "> 生成时间：%s ｜ 检索范围：%s ｜ 白名单期刊：%d 本（IF 2024 JCR 约值）" % (
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            ("近 %s 天" % days) if days else "全部年份",
            len(JOURNALS)),
        "> 已自动剔除现有图谱已收录的 %d 条证据。" % len(existing),
        "",
        "## 总览",
        "",
        "| 通道 | 候选数 |",
        "|---|---|",
    ]
    for ch, n in stats.items():
        lines.append("| %s | %d |" % (ch, n))
    lines += ["| **合计** | **%d** |" % len(papers), ""]

    tier_n = {"S": 0, "A": 0, "B": 0}
    for p in papers:
        tier_n[p["tier"]] += 1
    lines += ["期刊分层：S级顶刊 %d 篇 ｜ A级 %d 篇 ｜ B级 %d 篇" % (tier_n["S"], tier_n["A"], tier_n["B"]), ""]

    lvl_n = {}
    for p in papers:
        lvl_n[p["suggest_level"]] = lvl_n.get(p["suggest_level"], 0) + 1
    lines += ["证据等级：A(Meta/系统评价) %d ｜ B(RCT/类实验) %d ｜ C(观察性) %d ｜ D(综述/机制) %d" % (
        lvl_n.get("A", 0), lvl_n.get("B", 0), lvl_n.get("C", 0), lvl_n.get("D", 0)), ""]

    for ch in QUERIES:
        ch_papers = [p for p in papers if ch in p["channels"]]
        if not ch_papers:
            continue
        lines += ["## 通道：%s（%d 篇）" % (ch, len(ch_papers)), ""]
        for p in ch_papers:
            lvl, lname = suggest_level(p["pubtypes"])
            lines += [
                "### [%s] %s (%s) — %s %s" % (p["pmid"], p["title"], p["year"], p["journal"], TIER_LABEL[p["tier"]]),
                "",
                "- IF≈%d ｜ %s ｜ 建议证据等级：%s（%s）" % (
                    p["if"], " / ".join(p["pubtypes"][:4]) or "Journal Article", lvl, lname),
                "- 通道标签：%s ｜ 综合得分：%.1f" % ("、".join(p["channels"]), p["_score"]),
                "- DOI: https://doi.org/%s" % (p["doi"] or "N/A"),
                "",
                "> %s" % (p["abstract"][:400] + ("…" if len(p["abstract"]) > 400 else "")),
                "",
            ]

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("\n===== 完成 =====")
    print("候选文献: %d (S级 %d / A级 %d / B级 %d)" % (len(papers), tier_n["S"], tier_n["A"], tier_n["B"]))
    print("元数据:  ", MINED_PATH)
    print("图谱候选: ", CAND_PATH)
    print("报告:     ", REPORT_PATH)


if __name__ == "__main__":
    main()
