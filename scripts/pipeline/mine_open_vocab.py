import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口
# -*- coding: utf-8 -*-
"""Open-vocabulary mining of dev+test: find uncovered intervention-ish phrases."""
import json, re, collections
from pathlib import Path

ROOT = _paths.ROOT
alias = _schema.legacy_alias()
all_res = [re.compile(p, re.I) for v in list(alias["head_aliases"].values()) + list(alias["tail_aliases"].values()) for p in v]

ev = []
for _s in ('dev', 'test'):
    ev += [json.loads(l) for l in open(_paths.sp(_s), encoding='utf-8')]

PATTERNS = [
    r'([a-z]+(?: [a-z]+){0,2}) (therapy|training|intervention|exposure)',
    r'([a-z]+) (oil|extract|supplement|aroma|scent)',
    r'([a-z]+ (?:sound|noise|music))',
    r'(virtual [a-z]+)',
    r'([a-z]+ (?:bath|soak|spring|spa))',
    r'([a-z]+) (tea|infusion)',
    r'([a-z]+ (?:light|lighting))',
    r'([a-z]+ (?:garden|greenery|plant|plants))',
    r'((?:forest|nature|urban|indoor) [a-z]+)',
    r'([a-z]+-?assisted [a-z]+)',
    r'([a-z]+ breathing|breathing [a-z]+)',
    r'([a-z]+ meditation|meditation [a-z]+)',
    r'(aroma|color|music|sound|nature|garden|forest) ?therapy',
]
STOP = set(("a an the of in on for with and or to from by at as is are was were be been being this that these "
            "those it its their his her our your not no can could may might will would should than then when "
            "while during after before between among over under into onto about across per more most less least "
            "such other same another each every all any some both few many much very using used use uses patient "
            "patients participants subject subjects group groups study studies trial trials effect effects result "
            "results data time week weeks day days month months year years session sessions min minute minutes hour "
            "hours level levels score scores test tests measure measures measured rate rates risk change changes "
            "difference differences significant significantly association associated between within across had has "
            "have does did doing shown show showed found reported observed compared comparison reduction increase "
            "decreased increased improvement improvements treatment treatments control controlled effect size "
            "confidence interval outcome outcomes variable variables analysis model adjusted mean standard "
            "deviation error baseline following prior total high low higher lower greater smaller post pre one two "
            "three four five six ten first second third new older young adult adults women men female male "
            "healthy university college clinical chronic acute physical mental emotional social positive negative "
            "randomized assigned received receiving given performed completed participants").split())

FREQ = collections.Counter()
DOCS = collections.defaultdict(set)
CTX = {}
for d in ev:
    text = (d['input']['title'] + ' ' + d['input']['abstract']).lower()
    text_ns = re.sub(r'[^a-z ]', ' ', text)
    for pat in PATTERNS:
        for m in re.finditer(pat, text_ns):
            phrase = m.group(0).strip()
            words = phrase.split()
            if any(w in STOP for w in words):
                continue
            if len(phrase) < 5:
                continue
            i = text_ns.find(phrase)
            ctx = text_ns[max(0, i - 60): i + len(phrase) + 60]
            if not any(a.search(ctx) for a in all_res):
                FREQ[phrase] += 1
                DOCS[phrase].add(d['task_id'])
                CTX.setdefault(phrase, ctx.strip())

print("== dev+test 未覆盖干预类短语（频率降序，>=2）==")
for p, n in FREQ.most_common(100):
    if n >= 2:
        print(f"{n:3d}  {p:40s} | {CTX[p][:90]}")
