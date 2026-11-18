# -*- coding: utf-8 -*-
"""验收：提示词包是否覆盖知识图谱全部节点 ID。"""
import json
from collections import Counter

ROOT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈"
g = json.load(open(f"{ROOT}/output/data/knowledge_graph.json", encoding="utf-8"))
doc = open(f"{ROOT}/output/云谷_文生视频提示词包.md", encoding="utf-8").read()

by_type = Counter(n["type"] for n in g["nodes"])
print("图谱:", dict(by_type), "| 边", len(g["edges"]), "| 文献", len(g["evidence"]))
lv = Counter(v["level"] for v in g["evidence"].values())
print("证据等级:", dict(sorted(lv.items())))
print()

# 主线九镜头 + 附录镜头10 的定义区
main = doc.split("## 三、九镜头脚本")[1].split("## 四、")[0]
appendix = doc.split("## 六、附录镜头 10")[1].split("## 七、")[0] if "## 六、附录镜头 10" in doc else ""
cover = doc.split("## 五、要素覆盖核对表")[1].split("## 六、")[0]

rows = []
for n in g["nodes"]:
    nid = n["id"]
    in_main = nid in main
    in_app = nid in appendix
    in_cover = nid in cover
    rows.append((n["type"], nid, n["name"], in_main, in_app, in_cover))

bad = [r for r in rows if not (r[4] or r[5])]
print(f"=== 82 节点是否都在某个镜头的『覆盖』声明里 ===")
print("未声明的节点:", len(bad))
for t, i, nm, m, a, c in bad:
    print(f"  {t:9s} {i:22s} {nm}")

print()
print("=== 覆盖表是否含全部节点 ===")
nc = [r[1] for r in rows if not r[5]]
print("覆盖表缺失:", len(nc), nc if nc else "无 ✅")

print()
print("=== 负向清单命中的证据节点 ===")
neg_ids = ["stim_noise", "des_sound"]
for i in neg_ids:
    n = next(x for x in g["nodes"] if x["id"] == i)
    print(f"  {i} ({n['name']}) -> negative: {'是' if i in main or i in cover else '否'}")

print()
print("=== 统计 ===")
print("主线镜头声明的节点数:", len([r for r in rows if r[3]]))
print("附录镜头10 声明的节点数:", len([r for r in rows if r[4]]))
print("合计覆盖:", len([r for r in rows if r[3] or r[4]]), "/", len(g["nodes"]))