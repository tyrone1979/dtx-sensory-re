# -*- coding: utf-8 -*-
"""Rank candidate papers: built-environment context + healing outcome + colour/shape topic."""
import json
import re

DB = json.load(open("papers_visual2.json", encoding="utf-8"))

ENV = (r"interior|indoor|built environment|landscape|urban|architect|room|office|hospital|clinic|ward|"
       r"residential|housing|apartment|public space|garden|park|facility|spac|environmen|wall|window|"
       r"lighting|light|view|plaza|dwelling|school|classroom|workplace|gallery|museum|heritage|restorativ|therap")
NEG = (r"cell|bacteri|protein|molecul|tumou?r|carcinom|mice|mouse|murine|rat\b|zebrafish|drosophila|retina|"
       r"neuron|microbio|soil|sediment|aquatic|taxonom|species|genom|chromosom|ribosom|polymer|viscos|"
       r"elastic|surgery|postoperative|preoperative|dosage|antibiotic|virus|bacteri|ecosystem|river|stream|"
       r"forest |tree |vegetation|plant |soil|weather|climate|noise|sound|music|temperature")
HEAL = (r"stress|anxiety|depress|wellbeing|well-being|mood|health|cortisol|heart rate|arousal|restorat|recover|"
        r"relax|attention|fatigue|mental|emotion|affect|comfort|therap|preference|pleasant|burnout|sleep")
COLOR = r"colou?r|hue|chroma|saturat|palette"
SHAPE = (r"shape|geometr|spatial form|spatial config|spatial layout|curv|rectilinear|angular|enclosure|"
         r"geodesic|fractal|organic form|biomorphic|legib|wayfinding|complexity")


def classify(p):
    t = (p["title"] + " " + p["abstract"]).lower()
    if re.search(NEG, t):
        return None
    if not re.search(ENV, t) or not re.search(HEAL, t):
        return None
    if re.search(COLOR, t):
        return "color"
    if re.search(SHAPE, t):
        return "shape"
    return None


def pubtag(p):
    pt = " ".join(p["pubtypes"])
    if "Meta-Analysis" in pt or "Systematic Review" in pt:
        return "A"
    if "Randomized Controlled Trial" in pt:
        return "B"
    if "Review" in pt:
        return "D"
    return "C"


buckets = {"color": [], "shape": []}
for p in DB["papers"]:
    th = classify(p)
    if th:
        buckets[th].append(p)

for th in ("color", "shape"):
    rows = []
    topic = COLOR if th == "color" else SHAPE
    for p in buckets[th]:
        t = (p["title"] + " " + p["abstract"]).lower()
        tag = pubtag(p)
        sc = 0
        sc += 6 if re.search(topic, p["title"].lower()) else 0
        sc += {"A": 4, "B": 3.5, "D": 2, "C": 0}[tag]
        sc += 2 if (p["year"] and p["year"].isdigit() and int(p["year"]) >= 2015) else 0
        sc += min(len(set(re.findall(HEAL, t))), 6) * 0.4
        rows.append((sc, p, tag))
    rows.sort(key=lambda r: -r[0])
    print(f"==== {th.upper()}  通过门禁 {len(rows)} 篇 ====")
    for sc, p, tag in rows[:26]:
        print(f"{sc:5.1f} {tag} [{p['pmid']}] {p['year']} {p['title'][:104]}")
    print()