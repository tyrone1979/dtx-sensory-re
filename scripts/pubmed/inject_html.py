# -*- coding: utf-8 -*-
"""Inject libs + KG data into HTML templates -> final single-file deliverables."""
import json

ROOT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈"
TPL = f"{ROOT}/assets/templates"
ASSETS = f"{ROOT}/output/assets"
OUT = f"{ROOT}/output"

graph = json.load(open(f"{OUT}/data/knowledge_graph.json", encoding="utf-8"))
kg_json = json.dumps(graph, ensure_ascii=False)
d3 = open(f"{ASSETS}/d3.v7.min.js", encoding="utf-8").read()
three = open(f"{ASSETS}/three.min.js", encoding="utf-8").read()
orbit = open(f"{ASSETS}/OrbitControls.js", encoding="utf-8").read()

kg_html = open(f"{TPL}/kg_template.html", encoding="utf-8").read()
kg_html = kg_html.replace("__D3_JS__", d3).replace("__KG_JSON__", kg_json)
assert "__D3_JS__" not in kg_html and "__KG_JSON__" not in kg_html
open(f"{OUT}/数字疗愈知识图谱.html", "w", encoding="utf-8").write(kg_html)

sc_html = open(f"{TPL}/scene_template.html", encoding="utf-8").read()
sc_html = sc_html.replace("__THREE_JS__", three).replace("__ORBIT_JS__", orbit).replace("__KG_JSON__", kg_json)
assert "__THREE_JS__" not in sc_html and "__ORBIT_JS__" not in sc_html and "__KG_JSON__" not in sc_html
open(f"{OUT}/康旅3D循证设计.html", "w", encoding="utf-8").write(sc_html)

import os
for f in ["数字疗愈知识图谱.html", "康旅3D循证设计.html", "data/knowledge_graph.json", "data/triples.csv", "data/neo4j_import.cypher"]:
    p = os.path.join(OUT, f)
    print(f"{os.path.getsize(p)/1024:8.0f} KB  {f}")
