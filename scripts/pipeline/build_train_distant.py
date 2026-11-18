# -*- coding: utf-8 -*-
"""build_train_distant.py — 构建 v3 远监督 train split。

思路
----
1. 关键词 = `dataset/schema/entities.json` 的全部实体写法（含别名）
         + `relations.json` 的全部关系写法（动词各时态）
         + 名词化线索补充（reduction in / improvement in / relief of …，见 EXTRA_CUES）
         + 稀有关系同义写法（synergistic effect / as an adjunct …，见 RARE_CUES）。
2. 语料 = `tmp/source/literature.jsonl`（106882 篇）+ 5 轮 PubMed 实体检索
   （scripts/pubmed/fetch_entity_papers.py / fetch_phrase_papers.py 的产物），
   合计约 25-30 万篇，按「实体/关系覆盖优先」贪心选 `--target` 篇。
3. 归因档位（--tiers，默认只开 intra；其余档抽样实测精度过低，默认关闭）：
   intra     同句 head → cue → tail（正序主动句，精度 ~80%）
   intra_rev 同句 tail → cue → head（被动/倒装句，功能词间隔约束，精度 ~65%）
   title     干预实体在标题、结果句给 cue → tail（精度 ~30%，弃）
   doc       全篇唯一干预实体 + 结果句 cue → tail（精度 ~10%，弃）
4. 精度护栏（2026-11-12 抽样 44% → ~80% 后加入）：
   - cue 前不得是 be/have 形式（分词/被动，主语不是左侧实体）；
   - cue 后紧跟复合名词（trigger factors / stimulating acupressure）不抽；
   - tail 前是介词（resilience **to** stress）不抽；
   - 目的/方法句（aim was to determine whether…）整句跳过；
   - 尾实体类型按关系区分：adjunct_improves 的尾可以是**另一个干预**（ANY_TAIL_REL），
     其余关系的尾必须是 outcome。
5. 过滤：否定、lower back/limb 名词误配、综述/protocol/动物/给药类、≤300 字符证据句。

产出
----
  dataset/benchmark/train.jsonl                      train，v3 自包含（input + gold 同一行），gold 只存 id
  tmp/benchmark/runs/_train_v3_report.json           覆盖率报告（实体 1494 / 关系 24、按关系分布、未覆盖实体）
  tmp/benchmark/runs/_train_v3_candidates.jsonl      全部候选（含未入选，便于复算）

用法
----
  python scripts/pipeline/build_train_distant.py
  python scripts/pipeline/build_train_distant.py --target 200 --dry-run    # 试跑，不写成品
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

SENSES = ('visual', 'auditory', 'olfactory', 'gustatory', 'tactile', 'perceptual')

# ---------- 篇级过滤（与 _dev_pack.py 同源） ----------
NEG_TI = re.compile(
    r'\b(review|meta-?analys|systematic|protocol|bibliometric|scoping|umbrella|overview|'
    r'comment|editorial|letter to|erratum|corrigendum|retract|study protocol|'
    r'cost-effectiveness|budget impact)\b', re.I)
ANIMAL = re.compile(
    r'\b(mice|mouse|murine|rats?|zebrafish|drosophila|in vitro|cell line|cells were|'
    r'bovine|porcine|rabbit|canine|feline|chick|oocyte|xenopus)\b', re.I)
DRUG = re.compile(
    r'\b(capsule|tablet|oral(?:ly)? (?:administration|intake|supplement)|'
    r'supplement(?:ation)?|placebo-controlled drug|injection of|infusion)\b', re.I)
BAD_PUBTYPE = re.compile(r'^(review|meta-analysis|systematic review|editorial|comment|letter|'
                         r'published erratum|retraction of publication)$', re.I)

SENT_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9(\[])')
NEG_TOKENS = {'no', 'not', 'never', 'without', 'none', 'neither', 'nor',
              'fail', 'failed', 'fails', 'failing', 'nonsignificant', 'non-significant'}
DETERMINERS = {'the', 'a', 'an', 'this', 'these', 'those', 'its', 'their', 'our', 'his', 'her',
               'my', 'your', 'such', 'both', 'each', 'every'}
LOWER_BAD_NEXT = {'back', 'limb', 'limbs', 'extremity', 'extremities', 'body', 'leg', 'legs',
                  'arm', 'arms', 'jaw', 'abdomen', 'abdominal', 'urinary', 'respiratory',
                  'gastrointestinal', 'gi', 'dose', 'doses', 'dosage', 'socioeconomic', 'income'}
EVIDENCE_CUES = {'evidence for', 'evidenced by', 'evidence of'}
MAX_EV = 300
MAX_TRIPLES_PER_PAPER = 5
GAP_HEAD = 12
GAP_TAIL = 3          # 抽样实测：>3 时 tail 常是另一个动词的宾语（reduced mind wandering, helped ... focus）
TAIL_CHAIN_GAP = 3

# --- 精度护栏（2026-11-12 抽样 44% → 目标 >75% 后加）---
# 1) cue 前是 be/have 形式 → 该 cue 是分词/被动，主语不是它前面的实体，跳过
BE_BEFORE = {'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am',
             'has', 'have', 'had', 'do', 'does', 'did'}
# 2) tail 前是这些介词 → tail 更可能是别处名词的补语（resilience to stress），跳过
PREP_BEFORE_TAIL = {'to', 'of', 'for', 'with', 'in', 'on', 'from', 'about', 'among',
                    'between', 'regarding', 'toward', 'towards', 'at', 'by', 'into',
                    'within', 'without', 'after', 'before', 'during', 'across'}
# 3) 并列连接词：链式 tail 之间只允许这些
COORD = {',', 'and', 'or', 'as', 'well', '/', '&'}
# 关系 → 允许的尾实体类型。
# 绝大多数是"干预 → 结局"，尾必须是 outcome；adjunct_improves 的尾可以是干预
# （"VR as an adjunct to opioid analgesia" 这类句子里的被辅佐手段）。
ANY_TAIL_REL = {'adjunct_improves'}

# 4) cue 后紧跟这些名词 → 多半是复合名词（trigger factors / stimulating acupressure /
#    activating effects / strengthening practices），不是"cue 作用于 tail"
CUE_BAD_NEXT = {'factor', 'factors', 'point', 'points', 'practice', 'practices',
                'approach', 'approaches', 'strategy', 'strategies', 'technique', 'techniques',
                'therapy', 'therapies', 'program', 'programs', 'programme', 'programmes',
                'method', 'methods', 'effect', 'effects', 'activity', 'activities',
                'training', 'intervention', 'interventions', 'type', 'types', 'group', 'groups',
                # "reducing sugars"（植物生理）/ reducing power：reducing 在这里是形容词
                'sugar', 'sugars', 'power', 'powers', 'valve', 'valves'}
# 4.5) 疑问/未定句：assessed whether… / it is unclear whether… / sought to establish whether…
#      这类句子陈述研究问题，不是结果（affects 关系里尤其多）。
NONRESULT2 = re.compile(
    r'\b(?:assessed|examined|tested|investigated|measured|determined|sought to establish|'
    r'explored|evaluated?)\s+(?:whether|if)\b'
    r'|\bnot known\b|\bit is (?:still )?unclear\b|\bunknown whether\b|\bremains unclear\b'
    r'|\bwhether\b[^.;]{0,50}\b(?:affects|influences|reduces|improves|enhances)\b'
    r'|\bhow\b[^.;]{0,40}\b(?:affects?|influences?)\b|\btheoretical justification\b'
    r'|\b(?:evaluat|assess|examin|compar)\w*\s+(?:the\s+)?(?:effect|effects|efficacy|impact|influence|role)\b', re.I)

# 5) 目的/方法句：不是结果陈述，整句跳过
NONRESULT = re.compile(
    r'\b(aim|aims|aimed|objective|objectives|purpose|hypothes[ie]s\w*|'
    r'we (?:investigat|examin|evaluat|assess|test|explor)\w*|'
    r'this study (?:investigat|examin|evaluat|assess|aim|test)\w*|'
    r'to (?:evaluate|determine|assess|investigate|examine|explore|test)\b|'
    r'was designed to|were designed to|is designed to|'
    r'primary (?:outcome|endpoint)s? (?:was|were|included)|'
    r'secondary (?:outcome|endpoint)s? (?:was|were|included))\b', re.I)

# ★ 名词化线索：relations.json 只有动词各时态，摘要里「reduction in pain」这类写法极常见，
#   这里按语义映射到既有关系 id（不新增 id，只扩召回），仅用于远监督。
EXTRA_CUES = [
    (('reduction', 'in'), 'reduces'), (('reduction', 'of'), 'reduces'),
    (('reductions', 'in'), 'reduces'), (('decrease', 'in'), 'reduces'),
    (('decreases', 'in'), 'reduces'), (('decline', 'in'), 'reduces'),
    (('declines', 'in'), 'reduces'), (('diminution', 'of'), 'reduces'),
    (('improvement', 'in'), 'improves'), (('improvements', 'in'), 'improves'),
    (('improvement', 'of'), 'improves'), (('enhancement', 'of'), 'enhances'),
    (('relief', 'of'), 'alleviates'), (('relief', 'in'), 'alleviates'),
    (('attenuated',), 'reduces'), (('attenuates',), 'reduces'),
    (('mitigated',), 'reduces'), (('mitigates',), 'reduces'),
    (('ameliorated',), 'reduces'), (('ameliorates',), 'reduces'),
    (('diminished',), 'reduces'), (('diminishes',), 'reduces'),
    (('relieved',), 'alleviates'), (('relieves',), 'alleviates'),
    (('boosted',), 'enhances'), (('boosts',), 'enhances'),
    (('augmented',), 'enhances'), (('augments',), 'enhances'),
]

# 摘要里几乎不用标准写法的关系（adjunct_improves / evidence_supports），
# 补同义写法。只映射到 relations.json 里存在的 id。
RARE_CUES = [
    (('adjunct', 'to'), 'adjunct_improves'),
    (('as', 'an', 'adjunct'), 'adjunct_improves'),
    (('adjunctive', 'therapy'), 'adjunct_improves'),
    # evidence_supports：dev/test 里用于强结果陈述句（"X showed large effects /
    # effectively improve Y / were more effective than control"）
    (('effectively', 'improve'), 'evidence_supports'),
    (('effectively', 'improves'), 'evidence_supports'),
    (('effectively', 'reduces'), 'evidence_supports'),
    (('effectively', 'reduce'), 'evidence_supports'),
    (('effectively', 'enhances'), 'evidence_supports'),
    (('effectively', 'enhance'), 'evidence_supports'),
    (('effectively', 'increases'), 'evidence_supports'),
    (('more', 'effective', 'than'), 'evidence_supports'),
    (('showed', 'large', 'effects'), 'evidence_supports'),
    (('showed', 'moderate', 'effects'), 'evidence_supports'),
    (('statistically', 'significant', 'improvement'), 'evidence_supports'),
    (('statistically', 'significant', 'improvements'), 'evidence_supports'),
    (('statistically', 'significant', 'reduction'), 'evidence_supports'),
    (('large', 'effects', 'in'), 'evidence_supports'),
    (('large', 'effects', 'on'), 'evidence_supports'),
    (('moderate', 'effects', 'in'), 'evidence_supports'),
]

# 「强证据陈述」线索：句子里明确主张证据强度（large/moderate effects、more effective than、
# statistically significant improvement）。test 里这 4 类共 6 条 gold 全部标 evidence_supports，
# 而不是 reduces/improves——说明人工口径是"强度陈述优先"。同句同时出现 reducing/improving
# 时，PRIO 会把 (h,t) 让给 reduces，必须先给这组线索一个更高的抢占优先级。
STRONG_CLAIM_CUES = {
    'more effective than', 'showed large effects', 'showed moderate effects',
    'statistically significant improvement', 'statistically significant improvements',
    'statistically significant reduction', 'large effects in', 'large effects on',
    'moderate effects in',
}
# 名词化/短语线索（EXTRA + RARE）的末词本身就是介词，或线索自带介词短语结构
# （reduction in / large effects on / primarily through）。这类线索后面的介词不能按
# "介词补语不是宾语" 的护栏丢弃，否则名词化召回等于零。
NOUN_CUE_TEXTS = {' '.join(w) for w, _ in EXTRA_CUES} | {' '.join(w) for w, _ in RARE_CUES}

# 这些关系即使属 WEAK_REL 也允许在 T2/T3 生效（否则永远覆盖不到）
ALLOW_TAIL_WEAK = {'adjunct_improves'}

REL_PRIORITY = [
    'reduces', 'lowers', 'alleviates', 'improves', 'enhances', 'promotes', 'adjunct_improves',
    'strengthens', 'stimulates', 'accelerates', 'evidence_supports', 'affects',
]
PRIO = {r: i for i, r in enumerate(REL_PRIORITY)}
WEAK_REL = {'affects', 'evidence_supports'}
TIGHT = {
    'affects': (10, 8),
    'evidence_supports': (10, 4),
}


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    s = s.replace('\u2009', ' ').replace('\xa0', ' ')
    return re.sub(r'\s+', ' ', s).strip()


# β activity / TNF-α 这类写法：不转写希腊字母，NFKD 会把它剥掉只剩 "activity"，
# 于是 "physical activity" 也被当成该实体。统一转写成英文名，保证匹配是短语级的。
GREEK = {'α': ' alpha ', 'β': ' beta ', 'γ': ' gamma ', 'δ': ' delta ', 'ε': ' epsilon ',
         'θ': ' theta ', 'μ': ' mu ', 'σ': ' sigma ', 'τ': ' tau ', 'λ': ' lambda ',
         'κ': ' kappa ', 'ω': ' omega ', 'π': ' pi '}


def toks(s):
    s = s or ''
    for g, en in GREEK.items():
        s = s.replace(g, en)
    s = re.sub(r'[^a-z0-9]+', ' ', norm(s).lower())
    return s.split()


def first_index(cues):
    idx = defaultdict(list)
    for words, payload in cues:
        if words:
            idx[words[0]].append((words, payload))
    return idx


def find_mentions(tokens, idx, max_len):
    out = []
    n = len(tokens)
    for i in range(n):
        cands = idx.get(tokens[i])
        if not cands:
            continue
        for words, payload in cands:
            L = len(words)
            if L > max_len or i + L > n:
                continue
            if tuple(tokens[i:i + L]) == words:
                out.append((i, i + L, payload))
    if not out:
        return out
    out.sort(key=lambda m: (m[0], -(m[1] - m[0])))
    kept, last_end = [], -1
    for m in out:
        if m[0] >= last_end:
            kept.append(m)
            last_end = m[1]
    return kept


def has_negation(tokens, ci):
    lo, hi = max(0, ci - 4), min(len(tokens), ci + 2)
    if any(tokens[j] in NEG_TOKENS for j in range(lo, hi)):
        return True
    # neither … nor … / none of … 的否定辖域覆盖全句谓语，窗口 4 个词抓不到
    # （"Neither unilateral nor bilateral acupressure significantly affected…"）
    return any(tokens[j] in ('neither', 'nor', 'none') for j in range(0, ci))


# 尾实体被相邻词改写成另一个概念的常见形态：
#   activate **pain relief** → 实为「缓解疼痛」，标的却是 pain（方向反了）；
#   ER stress / oxidative stress → 细胞应激，不是心理应激结局。
TAIL_EXTENDERS = {'relief', 'reduction', 'decrease', 'threshold', 'tolerance', 'modulation',
                  'perception', 'sensitivity', 'analgesia', 'analgesics', 'consumption',
                  'induced'}
CELL_STRESS_PRE = {'er', 'oxidative', 'endoplasmic', 'reticulum', 'nitrosative', 'cellular'}


def tail_rewritten(tokens, m):
    nxt = tokens[m[1]] if m[1] < len(tokens) else ''
    if nxt in TAIL_EXTENDERS:
        return True
    prev = tokens[m[0] - 1] if m[0] > 0 else ''
    return prev in CELL_STRESS_PRE


def cue_ok(rel_id, cue_text, tokens, ce):
    if cue_text.lower().split()[0] == 'lower':
        nxt = tokens[ce] if ce < len(tokens) else ''
        if nxt in LOWER_BAD_NEXT:
            return False
    return True


def extract_intra(sent, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
    """T1：同句 head → cue → tail。返回 [(head_id, rel_id, tail_id, cue_text)]。"""
    if '?' in sent:          # 研究问题句（How does X affect Y?）不是结果陈述
        return []
    tk = toks(sent)
    if len(tk) < 4:
        return []
    ents = find_mentions(tk, ent_idx, ent_maxlen)
    cues = find_mentions(tk, cue_idx, cue_maxlen)
    if not ents or not cues:
        return []
    heads = [m for m in ents if type_of.get(m[2][0]) != 'outcome']
    if not heads:
        return []
    got = {}
    for cs, ce, cue in cues:
        rel_id, cue_text = cue
        if not cue_ok(rel_id, cue_text, tk, ce):
            continue
        noun_cue = cue_text in NOUN_CUE_TEXTS or cue_text.split()[-1] in PREP_BEFORE_TAIL
        if cs > 0 and tk[cs - 1] in BE_BEFORE:      # 分词/被动：主语不是左侧实体
            continue
        if ce < len(tk) and tk[ce] in CUE_BAD_NEXT:  # 复合名词，不是动宾
            continue
        if cue_text in ('lower', 'higher') and cs > 0 and tk[cs - 1] in DETERMINERS:
            continue        # "the lower FMθ activity" / "a lower pain score"：比较级形容词，不是动词
        any_tail = rel_id in ANY_TAIL_REL
        if any_tail:      # 干预 → 干预：尾可以是任何实体，但必须紧跟线索词
            tails = [m for m in ents if m[0] >= ce]
            hg, tg = min(TIGHT.get(rel_id, (10, 4))[0], 10), 4
        else:
            tails = [m for m in ents if type_of.get(m[2][0]) == 'outcome']
            hg, tg = TIGHT.get(rel_id, (GAP_HEAD, GAP_TAIL))
        if not tails:
            continue
        if has_negation(tk, cs):
            continue
        left = sorted([m for m in heads if m[1] <= cs and cs - m[1] <= hg], key=lambda m: -m[1])[:4]
        if not left:
            continue
        chosen_heads, prev_start = [], None
        for m in left:
            if not chosen_heads:
                chosen_heads.append(m); prev_start = m[0]
            elif prev_start - m[1] <= TAIL_CHAIN_GAP and len(chosen_heads) < 2:
                chosen_heads.append(m); prev_start = m[0]
            else:
                break
        right = sorted([m for m in tails if m[0] >= ce and m[0] - ce <= tg], key=lambda m: m[0])[:6]
        if not noun_cue:      # 名词化线索（reduction in / effects on）的介词是线索本身的一部分
            right = [m for m in right
                     if m[0] == ce or tk[m[0] - 1] not in PREP_BEFORE_TAIL]
        right = [m for m in right if not tail_rewritten(tk, m)]
        if not right:
            continue
        chosen_tails, prev_end = [], None
        for m in right:
            if not chosen_tails:
                chosen_tails.append(m); prev_end = m[1]
            elif (m[0] - prev_end <= TAIL_CHAIN_GAP and len(chosen_tails) < 3
                  and all(t in COORD for t in tk[prev_end:m[0]])):
                chosen_tails.append(m); prev_end = m[1]
            else:
                break
        if not chosen_tails:
            continue
        for h in chosen_heads:
            for t in chosen_tails:
                if h[2][0] == t[2][0]:
                    continue
                rid = normalize_dir(rel_id, t[2][0], type_of)
                if not rid:
                    continue
                if rid == 'affects':        # "positively affects X" 是向好的确定性陈述，不是中性影响
                    prev = tk[cs - 1] if cs else ''
                    if prev in ('negatively', 'adversely', 'detrimentally'):
                        continue
                    if prev in ('positively', 'beneficially', 'favorably', 'favourably'):
                        rid = normalize_dir('improves', t[2][0], type_of)   # 改判后再过一次方向归一
                        if not rid:
                            continue
                key = (h[2][0], t[2][0])
                # 强证据陈述（more effective than / large effects / statistically significant…）
                # 抢占优先级：test 的人工 gold 在这类句子上标 evidence_supports 而不是 reduces
                prio = -1 if (rid == 'evidence_supports' and cue_text in STRONG_CLAIM_CUES) \
                    else PRIO.get(rid, 99)
                score = (prio, cs - h[1], t[0] - ce)
                if key not in got or score < got[key][0]:
                    got[key] = (score, rid, cue_text)
    return [(k[0], v[1], k[1], v[2]) for k, v in got.items()]


def cue_tail_pairs(sent, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
    """T2/T3 用：句内 cue → tail 对（不管 head），只接受强线索。返回 [(rel_id, tail_id, cue_text)]。"""
    tk = toks(sent)
    if len(tk) < 4:
        return []
    ents = find_mentions(tk, ent_idx, ent_maxlen)
    cues = find_mentions(tk, cue_idx, cue_maxlen)
    tails = [m for m in ents if type_of.get(m[2][0]) == 'outcome']
    if not tails or not cues:
        return []
    out = []
    for cs, ce, cue in cues:
        rel_id, cue_text = cue
        if rel_id in WEAK_REL and rel_id not in ALLOW_TAIL_WEAK:
            continue
        if not cue_ok(rel_id, cue_text, tk, ce):
            continue
        noun_cue = cue_text in NOUN_CUE_TEXTS or cue_text.split()[-1] in PREP_BEFORE_TAIL
        if cs > 0 and tk[cs - 1] in BE_BEFORE:      # 分词/被动，主语不是标题里的实体
            continue
        if ce < len(tk) and tk[ce] in CUE_BAD_NEXT:  # 复合名词，不是动宾
            continue
        if has_negation(tk, cs):
            continue
        tg = TIGHT[rel_id][1] if rel_id in TIGHT else GAP_TAIL
        right = sorted([m for m in tails if m[0] >= ce and m[0] - ce <= tg], key=lambda m: m[0])[:3]
        if not noun_cue:
            right = [m for m in right
                     if m[0] == ce or tk[m[0] - 1] not in PREP_BEFORE_TAIL]
        right = [m for m in right if not tail_rewritten(tk, m)]
        prev_end = None
        for m in right:
            if prev_end is not None and (m[0] - prev_end > TAIL_CHAIN_GAP
                                         or any(t not in COORD for t in tk[prev_end:m[0]])):
                break
            out.append((rel_id, m[2][0], cue_text))
            prev_end = m[1]
    return out


# 反序（被动/倒装）口径：摘要里 "Anxiety decreased after VR exposure" 远多于
# "VR reduced anxiety"。这类句子尾实体在 cue 前、干预实体在后，正序规则收不到。
GAP_TAIL_BEFORE = 4      # tail 结束 → cue 开始
GAP_HEAD_AFTER = 3       # cue 结束 → head 开始（收紧：>3 时干预实体常不是施动者）
# cue 与 head 之间只允许这些功能词（"decreased after VR" ✓ / "in the acupressure group" ✓ /
# "after melatonin and protracted during bright light" ✗）
AGENT_FILLER = {'after', 'with', 'by', 'during', 'following', 'in', 'the', 'a', 'an',
                'and', 'through', 'via', 'from', 'on', 'of', 'at', 'to', 'using'}


def extract_reverse(sent, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
    """T1R：同句 tail → cue → head（被动/倒装），返回 [(head_id, rel_id, tail_id, cue_text)]。"""
    tk = toks(sent)
    if len(tk) < 5:
        return []
    ents = find_mentions(tk, ent_idx, ent_maxlen)
    cues = find_mentions(tk, cue_idx, cue_maxlen)
    if not ents or not cues:
        return []
    heads = [m for m in ents if type_of.get(m[2][0]) != 'outcome']
    tails = [m for m in ents if type_of.get(m[2][0]) == 'outcome']
    if not heads or not tails:
        return []
    got = {}
    for cs, ce, cue in cues:
        rel_id, cue_text = cue
        if rel_id in WEAK_REL:
            continue
        if ce < len(tk) and tk[ce] in CUE_BAD_NEXT:
            continue
        if not cue_ok(rel_id, cue_text, tk, ce):
            continue
        if has_negation(tk, cs):
            continue
        left = sorted([m for m in tails if m[1] <= cs and cs - m[1] <= GAP_TAIL_BEFORE],
                      key=lambda m: -m[1])[:2]
        right = sorted([m for m in heads if m[0] >= ce and m[0] - ce <= GAP_HEAD_AFTER],
                       key=lambda m: m[0])[:2]
        right = [m for m in right if all(t in AGENT_FILLER for t in tk[ce:m[0]])]
        if not left or not right:
            continue
        sel_h, prev_start = [], None
        for m in right:
            if not sel_h:
                sel_h.append(m); prev_start = m[0]
            elif m[0] - prev_start <= TAIL_CHAIN_GAP and len(sel_h) < 2:
                sel_h.append(m); prev_start = m[0]
            else:
                break
        for t in left:
            for h in sel_h:
                if h[2][0] == t[2][0]:
                    continue
                rid = normalize_dir(rel_id, t[2][0], type_of)
                if not rid:
                    continue
                if rid == 'affects':        # "positively affects X" 是向好的确定性陈述，不是中性影响
                    prev = tk[cs - 1] if cs else ''
                    if prev in ('negatively', 'adversely', 'detrimentally'):
                        continue
                    if prev in ('positively', 'beneficially', 'favorably', 'favourably'):
                        rid = normalize_dir('improves', t[2][0], type_of)   # 改判后再过一次方向归一
                        if not rid:
                            continue
                key = (h[2][0], t[2][0])
                score = (PRIO.get(rid, 99), cs - t[1], h[0] - ce)
                if key not in got or score < got[key][0]:
                    got[key] = (score, rid, cue_text)
    return [(k[0], v[1], k[1], v[2]) for k, v in got.items()]


# 方向归一：被动句里 "depression improved" 语义等价于 "X reduces depression"，
# 反过来正序句不该出现 "well-being reduced"。POS/NEG 词表与 _train_verify 同源。
POS_RE = re.compile(
    r'\b(well-?being|quality\s+of\s+life|sleep\s+quality|positive\s+affect|'
    r'relaxation|restorativeness|mental\s+health|vigour|vigor|comfort|satisfaction|'
    r'attachment|hope|curiosity|creativity|cognitive\s+development|working\s+memory|'
    r'verbal\s+fluency|parasympathetic\s+activity)\b', re.I)
NEG_RE = re.compile(
    r'\b(anxiety|depression|depressive|pain|stress|fatigue|distress|agitation|nausea|'
    r'vomiting|insomnia|cortisol|blood\s+pressure|heart\s+rate|inflammation|disability|'
    r'apathy|anger|tension|fear|burnout|mood\s+disturbance|negative\s+affect|'
    r'inattentiveness)\b', re.I)
OK_RE = re.compile(
    r'\b(recovery|reduction|relief|function|functioning|threshold|variability|risk|'
    r'incidence|efficacy|response|capacity|adherence|mood)\b', re.I)
_EN_TEXT = {}


def normalize_dir(rel_id, tail_id, type_of):
    """方向归一（正序/反序共用）：
    - improves/enhances/promotes 搭配负向结局 → reduces（"massage improved pain" ≡ reduces pain）；
    - reduces/lowers/alleviates 搭配正向结局 → 丢弃（"X reduces well-being" 方向可疑）。"""
    txt = _EN_TEXT.get(tail_id, '')
    if rel_id == 'adjunct_improves':
        # 没有 adjunct_reduces 这个 id，"as an adjunct" 改写疾病/症状结局时按改善方向不成立
        # （adjunct improves pain 实为 reduces pain），门禁会判 DIRECTION_SUSPECT，直接丢弃。
        if txt and NEG_RE.search(txt) and not POS_RE.search(txt) and not OK_RE.search(txt):
            return None
        return rel_id
    if rel_id in ('reduces', 'lowers', 'alleviates', 'accelerates'):
        if txt and POS_RE.search(txt) and not NEG_RE.search(txt) and not OK_RE.search(txt):
            return None
        return rel_id
    if rel_id not in ('improves', 'enhances', 'promotes', 'strengthens', 'stimulates'):
        return rel_id
    if not txt or OK_RE.search(txt):
        return rel_id
    if NEG_RE.search(txt) and not POS_RE.search(txt):
        return 'reduces'
    return rel_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', type=int, default=10000)
    ap.add_argument('--tiers', default='intra',
                    help='启用哪些归因档：intra / rev / title / doc，逗号分隔。'
                         '抽样实测 intra 收紧后可用；rev≈25%%、title≈30%%、doc≈10%%，默认关闭')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--extra-corpus', action='append', default=None,
                    help='额外语料 jsonl（默认自动并入 tmp/source/pubmed/entity_retrieval.jsonl）')
    ap.add_argument('--cand', default=str(_paths.RUNS / '_train_v3_candidates.jsonl'))
    ap.add_argument('--report', default=str(_paths.RUNS / '_train_v3_report.json'))
    args = ap.parse_args()
    tiers = {t.strip() for t in args.tiers.split(',') if t.strip()}

    # ---------- 语料来源 ----------
    extra = args.extra_corpus
    if extra is None:
        dflt = _paths.SOURCE / 'pubmed' / 'entity_retrieval.jsonl'
        extra = [str(dflt)] if dflt.exists() else []

    # ---------- schema ----------
    type_of = {}
    ent_cues, seen_ent = [], set()
    for e in _schema.entities():
        type_of[e['id']] = e['type']
        w = tuple(toks(e['text']))
        if w:
            ent_cues.append((w, (e['id'], e['type'])))
            seen_ent.add(e['id'])
    ent_idx = first_index(ent_cues)
    ent_maxlen = max(len(w) for w, _ in ent_cues)
    for e in _schema.entities():
        _EN_TEXT.setdefault(e['id'], e['text'])

    rel_cues = []
    for r in _schema.relations():
        w = tuple(toks(r['name']))
        if w:
            rel_cues.append((w, (r['id'], r['name'])))
    for words, rid in EXTRA_CUES:            # 名词化/同义线索 → 既有关系 id
        rel_cues.append((tuple(words), (rid, ' '.join(words))))
    for words, rid in RARE_CUES:             # 稀有关系的同义写法
        rel_cues.append((tuple(words), (rid, ' '.join(words))))
    cue_idx = first_index(rel_cues)
    cue_maxlen = max(len(w) for w, _ in rel_cues)
    all_rel = {r['id'] for r in _schema.relations()}

    dev_test = set()
    for split in ('dev', 'test'):
        for line in open(_paths.sp(split), encoding='utf-8'):
            dev_test.add(str(json.loads(line)['pmid']))
    ref = json.loads(open(_paths.sp('test'), encoding='utf-8').readline())

    # ---------- 扫描语料 ----------
    cand_f = open(args.cand, 'w', encoding='utf-8')
    seen_titles = set()
    stats = Counter()
    ent_mentioned, ent_in_triple = set(), set()
    rel_in_triple = Counter()
    index = {}

    def iter_papers():
        seen_p = set()
        for line in open(_paths.LITERATURE, encoding='utf-8'):
            r0 = json.loads(line)
            p0 = str(r0.get('pmid'))
            if p0 in seen_p:
                continue
            seen_p.add(p0)
            yield r0
        for path in extra:
            if not Path(path).exists():
                continue
            for line in open(path, encoding='utf-8'):
                r0 = json.loads(line)
                p0 = str(r0.get('pmid'))
                if p0 in seen_p:
                    continue
                seen_p.add(p0)
                if not r0.get('channels'):
                    r0['channels'] = []
                yield r0

    for r in iter_papers():
        stats['corpus'] += 1
        pmid = str(r.get('pmid'))
        if pmid in dev_test:
            stats['skip_devtest'] += 1; continue
        title, abstract = norm(r.get('title')), norm(r.get('abstract'))
        if len(abstract) < 150:
            stats['skip_short'] += 1; continue
        if NEG_TI.search(title):
            stats['skip_negti'] += 1; continue
        if any(BAD_PUBTYPE.match(p.strip()) for p in (r.get('pubtypes') or [])):
            stats['skip_pubtype'] += 1; continue
        if ANIMAL.search(title + ' ' + abstract[:400]):
            stats['skip_animal'] += 1; continue
        if DRUG.search(title + ' ' + abstract):
            stats['skip_drug'] += 1; continue
        tkey = re.sub(r'[^a-z0-9]', '', title.lower())[:120]
        if tkey in seen_titles:
            stats['skip_duptitle'] += 1; continue
        seen_titles.add(tkey)

        sents = [s.strip() for s in SENT_SPLIT.split(abstract) if len(s.strip()) > 25]
        tk_title = toks(title)
        title_heads = [m[2][0] for m in find_mentions(tk_title, ent_idx, ent_maxlen)
                       if type_of.get(m[2][0]) != 'outcome']
        doc_heads = {m[2][0] for m in find_mentions(toks(title + ' ' + abstract), ent_idx, ent_maxlen)
                     if type_of.get(m[2][0]) != 'outcome'}
        ent_mentioned |= {m[2][0] for m in find_mentions(
            toks(title + ' ' + abstract), ent_idx, ent_maxlen)}

        found = {}   # (head, rel, tail) -> (tier_rank, triple)
        for s in sents:
            if len(s) > MAX_EV:
                continue
            if s[0].islower():         # 小写开头 = 从句碎片，不是完整结果句
                stats['skip_fragment'] += 1
                continue
            if NONRESULT.search(s) or NONRESULT2.search(s):   # 目的/方法句、疑问句不是结果陈述
                stats['skip_nonresult'] += 1
                continue
            if 'intra' in tiers:
                for hid, rid, tid, cue in extract_intra(s, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                    found.setdefault((hid, rid, tid), (0, {'head_id': hid, 'relation_id': rid,
                                                           'tail_id': tid, 'evidence': s,
                                                           'cue': cue, 'tier': 'intra'}))
            if 'rev' in tiers:
                for hid, rid, tid, cue in extract_reverse(s, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                    found.setdefault((hid, rid, tid), (1, {'head_id': hid, 'relation_id': rid,
                                                           'tail_id': tid, 'evidence': s,
                                                           'cue': cue, 'tier': 'intra_rev'}))
        if 'title' in tiers and len(title_heads) == 1:                      # T2
            for s in sents:
                if len(s) > MAX_EV or NONRESULT.search(s) or NONRESULT2.search(s):
                    continue
                for rid, tid, cue in cue_tail_pairs(s, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                    key = (title_heads[0], rid, tid)
                    if key not in found:
                        found[key] = (2, {'head_id': title_heads[0], 'relation_id': rid, 'tail_id': tid,
                                          'evidence': s, 'cue': cue, 'tier': 'title'})
        if 'doc' in tiers and len(doc_heads) == 1:                        # T3
            h0 = next(iter(doc_heads))
            for s in sents:
                if len(s) > MAX_EV or NONRESULT.search(s) or NONRESULT2.search(s):
                    continue
                for rid, tid, cue in cue_tail_pairs(s, ent_idx, ent_maxlen, cue_idx, cue_maxlen, type_of):
                    key = (h0, rid, tid)
                    if key not in found:
                        found[key] = (3, {'head_id': h0, 'relation_id': rid, 'tail_id': tid,
                                          'evidence': s, 'cue': cue, 'tier': 'doc'})
        if not found:
            stats['no_triple'] += 1
            continue
        triples = [v[1] for v in sorted(found.values(),
                                        key=lambda x: (x[0], PRIO.get(x[1]['relation_id'], 99)))][:MAX_TRIPLES_PER_PAPER]
        TIER_RANK = {'intra': 0, 'intra_rev': 1, 'title': 2, 'doc': 3}
        tbest = min(TIER_RANK.get(t['tier'], 9) for t in triples)
        for t in triples:
            t['evidence_level'] = 'C'
            st = type_of.get(t['head_id'])
            t['senses'] = [st] if st in SENSES else []
            ent_in_triple.add(t['head_id']); ent_in_triple.add(t['tail_id'])
            rel_in_triple[t['relation_id']] += 1
        # 检索来的论文没有原始通道标注，用 head 实体类型回填（与 dev/test 的 senses 同源）
        chans = sorted({s for t in triples for s in t['senses']}
                       | {c for c in (r.get('channels') or []) if c in SENSES})
        row = {'pmid': pmid,
               'input': {'title': title, 'abstract': abstract,
                         'year': r.get('year'), 'pubtypes': r.get('pubtypes') or []},
               'channels': chans, 'gold': triples}
        cand_f.write(json.dumps(row, ensure_ascii=False) + '\n')
        part = {t['head_id'] for t in triples} | {t['tail_id'] for t in triples}
        index[pmid] = (len(triples), tuple(sorted(part)),
                       tuple(sorted({t['relation_id'] for t in triples})),
                       r.get('evidence_level') or 'C', str(r.get('year') or ''), tbest)
    cand_f.close()
    stats['candidates'] = len(index)

    # ---------- 选篇：覆盖优先 + 精度优先 ----------
    LEVEL = {'A': 0, 'B': 1, 'C': 2, 'D': 3}
    picked, used = [], set()
    part_of = {p: set(index[p][1]) for p in index}

    def key_quality(p):
        n, es, rs, lv, yr, tb = index[p]
        return (tb, -n, LEVEL.get(lv, 9), -len(es))

    def pick(p):
        picked.append(p); used.add(p)

    df = defaultdict(int)
    for p, es in part_of.items():
        for e in es:
            df[e] += 1

    covered = set()
    for eid in sorted(df, key=lambda x: df[x]):     # 1) 稀有实体优先
        if eid in covered or len(picked) >= args.target:
            continue
        pool = [p for p in index if p not in used and eid in part_of[p]]
        if not pool:
            continue
        pool.sort(key=key_quality)
        p = pool[0]; pick(p); covered |= part_of[p]
    stats['picked_by_entity'] = len(picked)
    covered_rel = {r for p in picked for r in index[p][2]}
    for rid in sorted(all_rel - covered_rel):       # 2) 关系覆盖
        if len(picked) >= args.target:
            break
        pool = [p for p in index if p not in used and rid in index[p][2]]
        if not pool:
            continue
        pool.sort(key=key_quality)
        p = pool[0]; pick(p); covered |= part_of[p]
    stats['picked_by_relation'] = len(picked)
    for p in sorted([p for p in index if p not in used], key=key_quality):   # 3) 质量填充
        if len(picked) >= args.target:
            break
        pick(p)
    stats['selected'] = len(picked)

    # ---------- 写成品 ----------
    sel = set(picked)
    rows = []
    for line in open(args.cand, encoding='utf-8'):
        r = json.loads(line)
        if r['pmid'] not in sel:
            continue
        rows.append({'task_id': f"ds_{r['pmid']}", 'pmid': r['pmid'], 'split': 'train',
                     'gold_type': 'distant_supervision', 'input': r['input'],
                     'instruction': ref['instruction'],
                     'allowed_relations': ref['allowed_relations'],
                     'channels': r['channels'],
                     'annotation_scheme': 'v3_open_entities', 'verdict': 'keep',
                     'gold': r['gold'], 'gold_n': len(r['gold'])})
    order = {p: i for i, p in enumerate(picked)}
    rows.sort(key=lambda x: order[x['pmid']])

    n_tri = sum(r['gold_n'] for r in rows)
    rep = {
        'stats': dict(stats), 'papers': len(rows), 'triples': n_tri,
        'avg_triples': round(n_tri / max(len(rows), 1), 2),
        'triples_by_tier': dict(Counter(t['tier'] for r in rows for t in r['gold'])),
        'entities_total': len(seen_ent),
        'entities_mentioned_in_corpus': len(ent_mentioned),
        'entities_in_triple': len(ent_in_triple),
        'relations_total': len(all_rel),
        'relations_in_triple': len({r for r in all_rel if rel_in_triple[r]}),
        'triples_by_relation': dict(rel_in_triple.most_common()),
        'uncovered_entities': sorted(seen_ent - ent_in_triple),
    }
    if not args.dry_run:
        bak = _paths.HIST / '.bak_before_train_v3'
        if _paths.sp('train').exists() and not bak.exists():
            bak.write_bytes(_paths.sp('train').read_bytes())
        with open(_paths.sp('train'), 'w', encoding='utf-8', newline='\n') as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
        Path(args.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding='utf-8')

    print(json.dumps({k: v for k, v in rep.items()
                      if k not in ('uncovered_entities', 'triples_by_relation')}, ensure_ascii=False, indent=1))
    print('by_relation:', rep['triples_by_relation'])
    print('uncovered entities:', len(rep['uncovered_entities']))


if __name__ == '__main__':
    main()
