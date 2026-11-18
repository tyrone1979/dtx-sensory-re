# -*- coding: utf-8 -*-
"""
evaluate_extraction.py — v3 开放实体 benchmark 评测脚本

与旧版（v2.0 闭集词表）的区别：
  - gold 只存 id（head_id / relation_id / tail_id），实体文本统一由 schema/entities.json 给出；
  - 实体匹配改为「开放实体 token 级匹配」：预测文本必须与该 gold id 的**任一规范写法**
    token 序列一致（含单复数折叠、冠词容忍）。不再做子串包含 / 字符重叠 / 正则 search
    这类宽松匹配——v2.0 时代它们是用来兜闭集同义词的，在开放实体口径下会把
    "acupressure" 错配给 "auricular acupressure" 这类不同实体，虚高 relaxed 分数；
  - 关系匹配按 id（兼容中文关系名 / 关系别名写法的输出）；
  - 输出 per-relation breakdown，便于按关系定位模型弱点。

输入：模型预测文件 predictions.jsonl，每行：
  {"task_id": "ds_12345678",
   "triples": [{"head": "forest therapy", "relation": "reduces",
                "tail": "anxiety", "evidence_level": "B"}, ...]}
  head/tail 为论文原文中的英文名词短语（开放词表，不限于 schema 词表）。

用法：
  python scripts/pipeline/evaluate_extraction.py predictions.jsonl                 # 评 dev+test(+test_core)
  python scripts/pipeline/evaluate_extraction.py predictions.jsonl --split test    # 只评某一 split
  python scripts/pipeline/evaluate_extraction.py predictions.jsonl --strict-level  # 额外统计证据等级准确率
  python scripts/pipeline/evaluate_extraction.py predictions.jsonl --per-relation  # 按关系拆分 strict F1

指标：
  strict  = (head, relation, tail) 全对
  relaxed = (head, tail) 对即算对（关系类型宽松）
"""
import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
import _schema		# entities.json / relations.json 统一入口

import argparse
import json
import sys
from collections import defaultdict

ARTICLES = {'the', 'a', 'an'}


def load_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def toks(s):
    """小写、去标点的 token 序列；数字保留。"""
    out, cur = [], []
    for ch in (s or '').lower():
        if ch.isalnum():
            cur.append(ch)
        elif cur:
            out.append(''.join(cur)); cur = []
    if cur:
        out.append(''.join(cur))
    return out


def fold(tok):
    """轻度单复数折叠：ies→y、去尾 s（≥4 字符）、es（≥5 字符且不以 ss 结尾）。"""
    if len(tok) > 4 and tok.endswith('ies'):
        return tok[:-3] + 'y'
    if len(tok) >= 5 and tok.endswith('es') and not tok.endswith('ss'):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith('s'):
        return tok[:-1]
    return tok


def toks_key(s):
    """匹配键：去冠词 + 单复数折叠后的 token 元组。"""
    return tuple(fold(t) for t in toks(s) if t not in ARTICLES)


def entity_keys(s):
    """一个实体文本的候选匹配键：原样 + 去括号（缩写注记）各一个。
    "auricular acupressure (GB30)" 既要能按全写法匹配，也要允许模型输出省略缩写的形式。"""
    import re as _re
    out = set()
    k = toks_key(s)
    if k:
        out.add(k)
    k2 = toks_key(_re.sub(r'\([^)]*\)', ' ', s or ''))
    if k2:
        out.add(k2)
    return out


# ---------------------------------------------------------------- 实体匹配
class EntityMatcher:
    """开放实体匹配：pred 文本 ↔ gold id 的任一规范写法（token 级全等）。"""

    def __init__(self):
        # {id: {匹配键, ...}}，来自 schema/entities.json 的全部写法
        self.surfaces = defaultdict(set)
        for e in _schema.entities():
            for k in entity_keys(e['text']):
                self.surfaces[e['id']].add(k)
        # {folded token 序列: set(id)} 反查表
        self.by_surface = defaultdict(set)
        for eid, ks in self.surfaces.items():
            for k in ks:
                self.by_surface[k].add(eid)

    def pred_ids(self, text):
        """pred 文本命中的实体 id 集合（不同 id 可能共享同一写法，取全部）。"""
        ids = set()
        for k in entity_keys(text):
            ids |= self.by_surface.get(k, set())
        return ids

    def match(self, pred_text, gold_id):
        return gold_id in self.pred_ids(pred_text)


MATCHER = None


def entity_match(pred_text, gold_id):
    return MATCHER.match(pred_text, gold_id)


# ---------------------------------------------------------------- 关系匹配
REL_NAME2ID = _schema.rel_name2id()
REL_ZH2EN = _schema.rel_zh2en()


def norm_rel(s):
    s = (s or '').strip().lower()
    if not s:
        return ''
    if s in REL_NAME2ID:
        return REL_NAME2ID[s]
    return REL_ZH2EN.get(s, s)


# ---------------------------------------------------------------- 主流程
def load_gold():
    gold = {}
    for sp in _paths.SPLITS:                      # train/dev/test 自包含文件
        for g in load_jsonl(_paths.sp(sp)):
            gold[g['task_id']] = g
    core_path = _paths.SOURCE / 'gold_core_human.jsonl'
    if core_path.exists():                        # v2.0 遗留人工子集（87 篇），存在才评
        for g in load_jsonl(core_path):
            gold[g['task_id']] = g
    return gold


def prf(tp, fp, fn):
    pr = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
    return pr, rc, f1


def main():
    global MATCHER
    ap = argparse.ArgumentParser()
    ap.add_argument('predictions')
    ap.add_argument('--split', default=None, help='train/dev/test/test_core，默认全部')
    ap.add_argument('--strict-level', action='store_true', help='统计证据等级准确率')
    ap.add_argument('--per-relation', action='store_true', help='按关系拆分 strict P/R/F1')
    ap.add_argument('--strong-only', action='store_true',
                    help='只用 gold_strength.json 中 strong（句内共现支撑）的 gold 三元组，剔除远监督噪声')
    args = ap.parse_args()
    MATCHER = EntityMatcher()

    strength = {}
    if args.strong_only:
        sp = _paths.AUX / 'gold_strength.json'
        if not sp.exists():
            print('缺少 %s（audit_gold.py 产物），无法启用 --strong-only' % sp)
            return 2
        strength = json.loads(sp.read_text(encoding='utf-8'))

    gold = load_gold()
    preds = load_jsonl(args.predictions)

    tp_s = tp_r = fp = fn = lvl_ok = lvl_n = 0
    rel_stat = defaultdict(lambda: [0, 0, 0])     # rel_id -> [tp, fp, fn]
    n_pred_used = 0
    for p in preds:
        g = gold.get(p['task_id'])
        if not g:
            continue
        if args.split and g['split'] != args.split:
            continue
        n_pred_used += 1
        gt = _schema.expand_gold(g['gold'])       # gold 只有 id，补回规范写法
        if args.strong_only:
            flags = strength.get(p['task_id'], [])
            gt = [t for i, t in enumerate(gt) if i >= len(flags) or flags[i] == 'strong']
            if not gt:
                continue
        matched = set()
        for tr in p.get('triples', []):
            hit = None
            for i, t in enumerate(gt):
                if i in matched:
                    continue
                if (entity_match(tr.get('head', ''), t.get('head_id', ''))
                        and entity_match(tr.get('tail', ''), t.get('tail_id', ''))
                        and norm_rel(tr.get('relation', '')) == norm_rel(t['relation'])):
                    hit = i
                    break
            if hit is not None:
                matched.add(hit)
                tp_s += 1
                rel_stat[gt[hit]['relation_id']][0] += 1
                if args.strict_level and tr.get('evidence_level') and gt[hit].get('evidence_level'):
                    lvl_n += 1
                    if tr['evidence_level'] == gt[hit]['evidence_level']:
                        lvl_ok += 1
                continue
            # 宽松：忽略关系类型
            for i, t in enumerate(gt):
                if i in matched:
                    continue
                if (entity_match(tr.get('head', ''), t.get('head_id', ''))
                        and entity_match(tr.get('tail', ''), t.get('tail_id', ''))):
                    matched.add(i)
                    tp_r += 1
                    break
            else:
                fp += 1
                rel_stat[norm_rel(tr.get('relation', '')) or '?'][1] += 1
        fn += len(gt) - len(matched)
        for i, t in enumerate(gt):
            if i not in matched:
                rel_stat[t['relation_id']][2] += 1

    ps, rs, fs = prf(tp_s, fp, fn)
    prr, rr, fr = prf(tp_s + tp_r, fp, fn)
    print('== 评测结果 (split=%s, %d 篇预测命中 gold%s) ==' % (
        args.split or 'all', n_pred_used, ', strong-gold 去噪' if args.strong_only else ''))
    print('strict  (头+关系+尾): P=%.4f R=%.4f F1=%.4f  (tp=%d fp=%d fn=%d)' % (ps, rs, fs, tp_s, fp, fn))
    print('relaxed (头+尾):     P=%.4f R=%.4f F1=%.4f  (tp=%d)' % (prr, rr, fr, tp_s + tp_r))
    if args.strict_level and lvl_n:
        print('证据等级准确率: %.4f (%d/%d)' % (lvl_ok / lvl_n, lvl_ok, lvl_n))
    if args.per_relation:
        print('--- per-relation (strict) ---')
        for rid in sorted(rel_stat, key=lambda r: -sum(rel_stat[r])):
            tp, fp_r, fn_r = rel_stat[rid]
            pr, rc, f1 = prf(tp, fp_r, fn_r)
            print('  %-20s P=%.3f R=%.3f F1=%.3f  (tp=%d fp=%d fn=%d)' % (rid, pr, rc, f1, tp, fp_r, fn_r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
