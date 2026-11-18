# -*- coding: utf-8 -*-
"""Merge pass-1 + pass-2 stores, filter to built-environment colour/shape healing studies."""
import json
import re

seen = {}
for f in ("papers_visual2.json", "papers_visual3.json"):
    for p in json.load(open(f, encoding="utf-8"))["papers"]:
        seen[p["pmid"]] = p
ALL = list(seen.values())

ENV = (r"interior|indoor|built environment|landscape|urban|architect|room|office|hospital|clinic|ward|"
       r"residential|housing|apartment|public space|garden|park|facility|spac|environmen|wall|window|"
       r"lighting|light|view|plaza|dwelling|school|classroom|workplace|gallery|museum|heritage|restorativ|therap|"
       r"dwell|place")
NEG = (r"cell|bacteri|protein|molecul|tumou?r|carcinom|\bmice\b|mouse|murine|\brat\b|zebrafish|drosophila|retina|"
       r"neuron|microbio|\bsoil\b|sediment|aquatic|taxonom|species|genom|chromosom|ribosom|polymer|viscos|"
       r"elastic|surgery|postoperative|preoperative|dosage|antibiotic|virus|ecosystem|river|stream|"
       r"vegetation|weather|climate|\bnoise\b|\bsound\b|\bmusic\b|temperature|curvature|optical|electrode|"
       r"crystallite|ribbon|membrane|autophagy|rod-like|gravitational|polytomy|ecosystem|ferment|carbon|soil")
HEAL = (r"stress|anxiety|depress|wellbeing|well-being|mood|health|cortisol|heart rate|arousal|restorat|recover|"
        r"relax|attention|fatigue|mental|emotion|affect|comfort|therap|preference|pleasant|burnout|sleep|"
        r"resilien|exhaustion|weariness|fatig")
COLOR = r"colou?r|hue|chroma|saturat|palette"
SHAPE = (r"shape|geometr|spatial form|spatial config|spatial layout|spatial organi|curv|rectilinear|angular|"
         r"enclosure|geodesic|fractal|organic form|biomorphic|legib|wayfinding|complexity|pattern|form")


def pubtag(p):
    pt = " ".join(p["pubtypes"])
    if "Meta-Analysis" in pt or "Systematic Review" in pt:
        return "A"
    if "Randomized Controlled Trial" in pt:
        return "B"
    if "Review" in pt:
        return "D"
    return "C"


def bucket(p):
    t = (p["title"] + " " + p["abstract"]).lower()
    if re.search(NEG, t):
        return None
    if not re.search(ENV, t) or not re.search(HEAL, t):
        return None
    c, s = bool(re.search(COLOR, t)), bool(re.search(SHAPE, t))
    if c and s:
        return "both"
    return "color" if c else ("shape" if s else None)


rows = []
for p in ALL:
    th = bucket(p)
    if not th:
        continue
    t = (p["title"] + " " + p["abstract"]).lower()
    tag = pubtag(p)
    topic = COLOR if th in ("color", "both") else SHAPE
    sc = 0
    sc += 6 if re.search(topic, p["title"].lower()) else 0
    sc += {"A": 4, "B": 3.5, "D": 2, "C": 0}[tag]
    sc += 2 if (p["year"] and p["year"].isdigit() and int(p["year"]) >= 2015) else 0
    sc += min(len(set(re.findall(HEAL, t))), 6) * 0.4
    sc += 1 if th == "both" else 0
    rows.append((sc, th, p, tag))
rows.sort(key=lambda r: -r[0])

from collections import Counter
print("总候选:", len(ALL), " 通过门禁:", len(rows), Counter(r[1] for r in rows))
for th in ("color", "shape", "both"):
    sub = [r for r in rows if r[1] == th][:24]
    print(f"\n==== {th.upper()} ====")
    for sc, _, p, tag in sub:
        print(f"{sc:5.1f} {tag} [{p['pmid']}] {p['year']} {p['title'][:100]}")