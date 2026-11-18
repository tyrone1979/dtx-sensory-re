import re
import sys

p = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈/assets/templates/scene_template.html"
s = open(p, encoding="utf-8").read()
blocks = re.findall(r"<script>(.*?)</script>", s, re.S)
main = max(blocks, key=len)
out = "/tmp/main_scene.js"
open(out, "w", encoding="utf-8").write(main)
print("main script chars:", len(main), "-> ", out)