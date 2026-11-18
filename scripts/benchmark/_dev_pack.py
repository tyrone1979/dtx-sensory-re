# -*- coding: utf-8 -*-
"""从候选池取一批待核读的 dev 篇目，生成紧凑阅读包（只留标题 + 结果句 + 设计线索）。

用法:
  python scripts/benchmark/_dev_pack.py --cls tactile --n 40 --out tmp/benchmark/runs/_pack_b01.jsonl
  python scripts/benchmark/_dev_pack.py --cls all --n 200 --out ...   # 按类轮转配额

输出每行:
  {"pmid","cls","level","year","title","design","sents":["结果句1", ...]}
sents 只保留含显著性/比较措辞的句子（证据句几乎都在这里），已规范化（与闸门同一 norm）。
"""
import argparse
import json
import re
import sys
import pathlib
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _paths

POOL = _paths.RUNS / '_topup_pool.jsonl'
USED = _paths.RUNS / '_dev_used_pmids.json'
DROPPED = _paths.RUNS / '_dev_dropped_pmids.json'   # 已核读并剔除的篇，不再进阅读包

# 明显不是一手结果型研究的标题特征
NEG_TI = re.compile(
    r'\b(review|meta-?analys|systematic|protocol|bibliometric|scoping|umbrella|overview|'
    r'comment|editorial|letter to|erratum|corrigendum|retract|study protocol|'
    r'cost-effectiveness|budget impact)\b', re.I)
# 动物 / 体外
ANIMAL = re.compile(
    r'\b(mice|mouse|murine|rats?|zebrafish|drosophila|in vitro|cell line|cells were|'
    r'bovine|porcine|rabbit|canine|feline|chick|oocyte|xenopus)\b', re.I)
# 显著性或比较措辞（有其一才可能出证据句）
SIG = re.compile(
    r'(significan|p\s*[<=>]\s*\.?\d|95\s*%\s*(ci|confidence)|'
    r'\b(lower|higher|greater|less|reduc|decreas|increas|improv|alleviat|reliev|enhanc|'
    r'drop|declin)\w*\b)', re.I)
# 设计线索（判断是否一手对照研究）
DESIGN = re.compile(
    r'\b(randomi[sz]ed|randomi[sz]ation|controlled trial|double-blind|single-blind|'
    r'crossover|cross-over|quasi-experimental|pretest-posttest|pre-test|'
    r'parallel[- ]group|sham|placebo|control group|compared (?:with|to)|'
    r'participants were|patients were|subjects were|we enrolled|were recruited)\b', re.I)
# 纯给药/膳食/补剂（非感官刺激）——预筛掉，减少核读量
DRUG = re.compile(
    r'\b(capsule|tablet|oral(?:ly)? (?:administration|intake|supplement)|'
    r'supplement(?:ation)?|placebo-controlled drug|injection of|infusion)\b', re.I)

SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9(\[])')

MAX_SENTS = 5


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = s.replace('\u2009', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def sents_of(abstract):
    return [s.strip() for s in SENT_SPLIT.split(norm(abstract)) if len(s.strip()) > 25]


def pack_row(r, k=MAX_SENTS):
    ab = norm(r.get('abstract'))
    ss = [s for s in sents_of(ab) if SIG.search(s)]
    # 结果句优先：含 significant / p 值的排前面
    ss.sort(key=lambda s: (0 if re.search(r'significan|p\s*[<=]\s*\.?\d', s, re.I) else 1))
    ss = ss[:k]
    d = DESIGN.search(ab)
    design = (d.group(0) if d else '')
    return {'pmid': str(r['pmid']), 'cls': r['cls'], 'level': r.get('evidence_level'),
            'year': r.get('year'), 'title': norm(r.get('title')),
            'design': design, 'sents': ss}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cls', default='all')
    ap.add_argument('--n', type=int, default=40)
    ap.add_argument('--out', required=True)
    ap.add_argument('--max-level', default='C', choices=['A', 'B', 'C', 'D'])
    args = ap.parse_args()

    pool = [json.loads(l) for l in open(POOL, encoding='utf-8')]
    used = set(map(str, json.load(open(USED, encoding='utf-8'))))
    if DROPPED.exists():                                     # 已核读剔除的不再重复进入包
        used |= set(map(str, json.load(open(DROPPED, encoding='utf-8'))))
    for s in _paths.SPLITS:                                  # 已在数据集里的篇不再入选
        for l in open(_paths.sp(s), encoding='utf-8'):
            used.add(str(json.loads(l)['pmid']))
    done = set()
    if pathlib.Path(args.out).exists():
        for l in open(args.out, encoding='utf-8'):
            done.add(json.loads(l)['pmid'])
    used |= done

    order = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
    cap = order[args.max_level]
    picks = []
    for r in pool:
        pmid = str(r['pmid'])
        if pmid in used:
            continue
        if args.cls != 'all' and r['cls'] != args.cls:
            continue
        if order.get(r.get('evidence_level'), 9) > cap:
            continue
        ti = norm(r.get('title'))
        ab = norm(r.get('abstract'))
        if not ab or NEG_TI.search(ti):
            continue
        if ANIMAL.search(ti + ' ' + ab[:400]):
            continue
        if DRUG.search(ti + ' ' + ab):
            continue
        row = pack_row(r)
        if not row['sents']:
            continue
        if not row['design']:                                 # 无对照/试验线索 → 多半是关联或机制文
            continue
        picks.append(row)
        used.add(pmid)
        if len(picks) >= args.n:
            break

    with open(args.out, 'a', encoding='utf-8') as fo:
        for r in picks:
            fo.write(json.dumps(r, ensure_ascii=False) + '\n')
    print(f'{args.cls}: +{len(picks)} 篇 → {args.out}')


if __name__ == '__main__':
    main()
