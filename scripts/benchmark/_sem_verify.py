import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
from _paths import p as dpath
# -*- coding: utf-8 -*-
"""test 全量语义复核的可执行校验闸门 v2（无误报优先）。

不依赖任何人工/子代理自我报告：直接对 gold 三元组 + 原文 title/abstract
跑硬性规则，输出逐条 flags。只有「机器可判定的真疑点」才置 flag。

用法:
  python dataset/benchmark/_sem_verify.py                    # 校验 test.jsonl 全量
  python dataset/benchmark/_sem_verify.py --json out.json   # 同时落盘明细
"""
import json, re, sys, unicodedata
from pathlib import Path

B = _paths.BM

CJK = re.compile(r'[\u4e00-\u9fff]')
CATID = re.compile(r'^(vis|aud|olf|tas|tac|per|env|ben)_')

# --- 规则 1/11：弱结论 / 阴性 / 不显著（限定在修饰本条结论的措辞） ---
WEAK = re.compile(
    r'\b(tended?\s+to|tendency|may\s+|might\s+|could\s+|appears?\s+to|seems?\s+'
    r'|it\s+seems|only\s+an?\s+indication|preliminary|'
    r'insignificant|no\s+significant\s+(?:difference|change|effect)|'
    r'no\s+effect|not\s+superior|did\s+not\s+(?:affect|improve|reduce)|failed\s+to|'
    r'limited\s+evidence|insufficient|low-certainty|further\s+(?:research|studies)\s+'
    r'(?:are|is)\s+needed|only\s+(?:one|two|1|2)\s+(?:of|stud)|cautiously|'
    r'warrant\s+further|remains?\s+(?:unclear|inconclusive)|suggests?\s+that\s+.{0,30}may)\b',
    re.I)

# --- 规则 10：背景引用句 ---
BG = re.compile(
    r'^(studies\s+show|previous\s+studies|prior\s+research|it\s+is\s+well\s+known|'
    r'has\s+been\s+shown|have\s+been\s+shown|research\s+has\s+shown|'
    r'literature\s+suggests)', re.I)

# --- 规则 3：测量工具被当成结局 ---
MEAS_EV = re.compile(
    r'(as\s+evidenced\s+by|measured\s+(?:with|by|using)|assessed\s+(?:with|using|by)|'
    r'as\s+measured\s+by|scores?\s+on\s+the\s+\w+\s+scale)', re.I)

# --- 规则 5 / 7：head 非特异 / 分组描述 ---
NONSPEC_HEAD = re.compile(r'\b(with\s+or\s+without|and/or)\b', re.I)
GROUP = re.compile(
    r'\b(six\s+environmental\s+types|three\s+groups|four\s+groups|'
    r'path\s+space\s+shapes|experimental\s+group|control\s+group|'
    r'simulated\s+nature\s+conditions|six\s+types|different\s+groups)\b', re.I)

# --- 规则：经济学评价为主结局（规范负面清单）---
# 这类研究的临床效果是从 parent trial 借来的模型输入，不是本研究的一手结论，
# 整篇不应产出临床三元组。必须「标题点明经济评价」+「摘要出现经济评价方法/主结局」
# 双条件同时成立，避免误伤顺带提一句 cost-effective 的临床 RCT。
ECON_TITLE = re.compile(
    r'\b(economic evaluation|health[- ]economic evaluation|'
    r'cost-effectiveness analysis|cost-utility analysis|cost-benefit analysis|'
    r'economic analysis of|cost analysis of|cost comparison)\b', re.I)
ECON_DESIGN = re.compile(
    r'\b(cost-effectiveness analysis|cost-utility analysis|cost-benefit analysis|'
    r'incremental cost-effectiveness ratio|ICER|quality-adjusted life|QALY|'
    r'from the (?:hospital|payer|societal|healthcare|health care) perspective|'
    r'break-even analy|probabilistic sensitivity analysis|cost savings|'
    r'cost-effective for|base case cost|dominance)\b', re.I)

# --- 规则：case series / case report（规范负面清单）---
# 只在标题判定：摘要里的 "case reports were excluded" 是纳入排除标准，不能据此判负。
CASE_SERIES = re.compile(
    r'\b(case series|case report|a case of|single[- ]case (?:study|report))\b', re.I)
# --- 规则：head 是实验对比条件（"X without Y"）而非干预实体 ---
CONDITION_HEAD = re.compile(r'\b(without|versus|vs\.?|compared (?:with|to))\b', re.I)
# --- 规则：evidence 不是结果句（背景/目的/方法句）---
EV_NOT_RESULT = re.compile(
    r'^(?:the aim|to (?:evaluate|investigate|examine|assess|determine|compare)|in recent years|'
    r'previous studies|it is well|studies have|the purpose of this|the primary endpoint|'
    r'background\s*:|methods\s*:|objective\s*:|we tested|the cochrane|'
    r'this (?:study|review|paper) (?:aim|aims|examined|investigated)|'
    r'\w+ is a chronic|\w+ is characterized by|data (?:were|was) (?:analyzed|collected)|'
    r'the (?:study|trial) (?:was|included|aimed))', re.I)
# --- 规则：转述他人研究（非本篇一手结论）---
# 「According to the results of the study」/「according to the Sheehan Disability Scale」是本篇结论或量表出处，不能误判
REPORTED_SPEECH = re.compile(
    r'\b(?:authors? (?:stated|reported|concluded)|'
    r'(?:trial|study|review) (?:involving|of) .{0,60} reported|'
    r'studies (?:have|has) shown|'
    r'according to (?:previous|prior|the) (?:studies|literature|reports|authors)|'
    r'it has been reported|a large crossover trial .{0,60} reported)\b', re.I)
# 「lower on N of M measures」且无显著性检验：不是可抽的一手肯定结论
LOWER_NO_SIG = re.compile(r'\b(?:lower|displayed lower|were lower)\b.{0,60}\bon \d+ of (?:the )?\d+ measures\b', re.I)

# 纯负面「状态」词。注意：scores/index/severity/symptom 等是中性量词，
# 不能算负面状态，否则 "improves X scores" 会被大面积误报为方向反了。
NEG_OUTCOME = re.compile(
    r'\b(anxiety|depression|depressive|pain|stress|fatigue|distress|'
    r'agitation|nausea|vomiting|insomnia|'
    r'cortisol|blood\s+pressure|heart\s+rate|inflammation|disability|'
    r'apathy|anger|tension|fear|burnout|mood\s+disturbance|negative\s+affect|'
    r'inattentiveness)\b', re.I)
POS_OUTCOME = re.compile(
    r'\b(well-?being|quality\s+of\s+life|sleep\s+quality|positive\s+affect|'
    r'relaxation|restorativeness|mental\s+health|vigour|vigor|'
    r'comfort|satisfaction|attachment|hope|curiosity|creativity|'
    r'cognitive\s+development|working\s+memory|verbal\s+fluency|'
    r'parasympathetic\s+activity|environmental\s+perception)\b', re.I)
# 方向判定例外：正向过程 / 越高越好的功能与能力指标 / 明确的正向评分
DIRECTION_OK = re.compile(
    r'\b(recovery|reduction|relief|control|remission|improvement|tolerance|'
    r'threshold|variability|wellbeing|well-?being|quality\s+of\s+life|positive\s+affect|'
    r'mood\b|relaxation|satisfaction|comfort|function|functioning|'
    r'abstinence|adherence|efficacy|response|capacity|vigour|vigor|'
    r'MCS|PCS|RSES|MoCA|Barthel|range\s+of\s+motion|'
    r'disorders?|risk|incidence|prevalence)\b', re.I)

REDUCE = {'reduces', 'lowers', 'alleviates', 'impairs', 'accelerates'}
IMPROVE = {'improves', 'enhances', 'promotes', 'strengthens', 'stimulates', 'activates', 'triggers'}

# --- v3：量表方向 / 无方向证据 / 笼统结论句 / 半个单词截断 ---
# 「分数越低越好」的量表与负面结局得分：improves X 应归一为 reduces X
SCALE_LOW = re.compile(
    r'\b(NIHSS|PSQI|HAMD|HAM-D|MADRS|BDI|STAI|VAS|NRS|GAD-7|PHQ-9|HADS|EPDS|PSS|'
    r'ISI|AICA-S|MDAS|HAMA|SDS|SAS|BAI|mMRC|SGRQ|NDI|BASMI|INVR|FLACC|TDIS|PMSS|'
    r'dyspnea score|pain scores?|anxiety scores?|depression scores?|fatigue scores?|'
    r'stress scores?|sleepiness scores?|Insomnia Severity Index|'
    r'Hamilton Scale for Depression|Pittsburgh Sleep Quality Index|'
    r'neck-disability index|HADS scores?)\b', re.I)
# 「越高越好」的结局：这些配 improves 是对的，不触发方向规则
SCALE_HIGH = re.compile(
    r'\b(relaxation|comfort|satisfaction|quality of life|QoL|well-being|wellbeing|'
    r'abstinence|adherence|self-efficacy|vitality|cognitive|memory|MoCA|Barthel|'
    r'MCS|PCS|RSES|WHO-5|SpO2|remission rate|sleep quality|mood scores?|'
    r'working capacity|general health status|positive affect|recovery|threshold|'
    r'mental health(?!\s+disorders?))\b', re.I)
# 只写「有显著差异」而无任何方向线索
NO_DIR = re.compile(
    r'\b(significant(?:ly)?\s+differences?|differed\s+significantly|'
    r'were\s+significantly\s+different|a\s+significant\s+difference)\b', re.I)
DIR_WORD = re.compile(
    r'\b(reduc\w*|decreas\w*|lower\w*|improv\w*|increas\w*|higher|enhanc\w*|fewer|'
    r'less|superior|gain\w*|elevat\w*|reliev\w*|alleviat\w*|beneficial|positive effect|'
    r'relief|decline\w*|better|worse|faster|slower)\b|-\d|→', re.I)
# v3b：残句 / 限定与推测 / 叙述性综述
FRAG_START = re.compile(r'^(?:[a-z]|[,;:.])')
HEDGE_LIMIT = re.compile(
    r'\b(but not higher SES|short-lived|placebo effects can play an important role|'
    r'but in the control group|on an exploratory analysis|These findings suggest|'
    r'except singing|can (?:significantly )?influence|in such a way as to|'
    r'only .{0,25}(?:low SES|subgroup)|can improve objective|'
    r'strong evidence for the effectiveness|generally reported beneficial|'
    r'convergent evidence shows|Evidence gathered demonstrates|'
    r'are consistent with previous research)\b', re.I)
# 推测 / 能力 / 目的状语：不是一手结果
HEDGE2 = re.compile(
    r'\b(can (?:significantly |effectively |be |improve|reduce|decrease|alleviate|'
    r'enhance|promote|modulate|regulate|alleviate)|probably|likely|appears? (?:to|most)|'
    r'was considered to|has been observed to|would benefit|is useful for|'
    r'can be considered|is able to|promising alternative|in order to|'
    r'is recommended to|has been recently proposed|is a promising)\b', re.I)
# 只有组内前后、完全没有对照比较
WITHIN2 = re.compile(
    r'\b(compared with baseline|compared to baseline|than the pretest|'
    r'before and after the experiment|paired sample t test|within sessions|'
    r'intra-?group analyses|within-?group|pre-?post|from baseline to|'
    r'after (?:both sessions|the sessions)|'
    r'after the intervention.{0,60}(?:decreased|improved|reduced))\b', re.I)
COMPARATOR = re.compile(
    r'\b(control|placebo|compared (?:with|to)|than (?:the )?(?:control|placebo|sham)|'
    r'versus|vs\.?|wait-?list|usual care)\b', re.I)

# 组内前后 / 两组都改善 / 非劣效：不能据此把改善特异归因于该干预
WITHIN_GROUP = re.compile(
    r'\b(both .{0,70}?groups? (?:showed|demonstrated|achieved|reported|had)|'
    r'in both groups|effect sizes in both groups|noninferior|non-inferior|'
    r'improved .{0,30}over time|increased .{0,30}over time|'
    r'from baseline to (?:week|Week|post)|pre-?post (?:comparison|change)|'
    r'as well as state anxiety)\b', re.I)
NARRATIVE = re.compile(
    r'\b(narrative review|scoping review|integrative review|umbrella review|'
    r'rapid review|literature review|review of the literature|best evidence topic|'
    r'a systematic literature review)\b', re.I)
QUANT = re.compile(r'\d+\.\d+|95\s*%|p\s*[<=>]|SMD|WMD|MD\s*=|OR\s*=|CI\b', re.I)

# 笼统/二手结论句，不承载具体结局
VAGUE_EV = re.compile(
    r'^(?:Overall,?\s+we\s+conclude|All of (?:the|these) selected|'
    r'Two themes emerged|Quantitative findings from the studies showed|'
    r'These findings demonstrate the efficacy|Overall,?\s+both controlled|'
    r'The findings were confirmed|In conclusion)', re.I)


def norm(s):
    s = unicodedata.normalize('NFKD', s or '')
    for a, b in [('\u2010','-'),('\u2011','-'),('\u2012','-'),('\u2013','-'),
                 ('\u2014','-'),('\u2212','-'),('\u2018',"'"),('\u2019',"'"),
                 ('\u201c','"'),('\u201d','"'),('\u00b7','')]:
        s = s.replace(a, b)
    return re.sub(r'\s+', ' ', s).strip()


def compact(s):
    """只保留字母数字，用于判断实体是否为原文连续片段（容忍连字符/空格/引号差异）。"""
    return re.sub(r'[^a-z0-9]', '', (s or '').lower())


def slug(s):
    return re.sub(r'[^a-z0-9]+', '_', norm(s).lower()).strip('_')


# --- 开放实体 schema：id 由 dataset/schema/entities.json 定义，同一实体的别名共用同一 id ---
def load_entities():
    """entities.json 是扁平记录：一条记录一个写法，同一 id 的多条记录互为别名。"""
    ents = json.loads((_paths.SCHEMA / 'entities.json').read_text(encoding='utf-8'))
    t2i, forms = {}, {}
    for e in ents:
        t2i.setdefault(e['text'].lower(), e['id'])
        forms.setdefault(e['id'], []).append(e['text'])
    return t2i, forms


TEXT2ID, FORMS = load_entities()
ENT_IDS = set(FORMS)


def gold_surface(eid, ev, text):
    """gold 只存 id，这里把它还原成原文写法：优先证据句里出现的形态，其次全文，最后规范写法。"""
    forms = sorted(FORMS.get(eid) or [], key=len, reverse=True)
    if not forms:
        return ''
    evc, tc = compact(ev), compact(text)
    for f in forms:
        c = compact(f)
        if c and c in evc:
            return f
    for f in forms:
        c = compact(f)
        if c and c in tc:
            return f
    return forms[0]


def any_form_in(eid, comp):
    """该 id 的任一种写法是否出现在原文里（compact 口径）。"""
    return any(compact(f) in comp for f in FORMS.get(eid) or [])


def ci_crosses(evidence):
    ev = norm(evidence)
    for m in re.finditer(r'(?:95\s*%\s*(?:CI|confidence\s+interval)|CI)\s*'
                         r'[\[\(\:]?\s*(-?\d+\.?\d*)\s*(?:,|to|-)\s*(-?\d+\.?\d*)',
                         ev, re.I):
        lo, hi = float(m.group(1)), float(m.group(2))
        if lo > hi:
            lo, hi = hi, lo
        null = 1.0 if re.search(r'\b(OR|odds ratio)\b', ev, re.I) else 0.0
        if lo <= null <= hi:
            return (lo, hi)
    return None


def tail_tokens(t):
    return set(re.findall(r'[a-z]{3,}', re.sub(r'\([^)]*\)', ' ', t.lower())))


def near_dup(a, b):
    A, B_ = tail_tokens(a), tail_tokens(b)
    if not A or not B_:
        return False
    return len(A & B_) / len(A | B_) >= 0.75


def load_bench():
    """test.jsonl 是自包含的：同一行既有 input（title/abstract）也有 gold。"""
    d = {}
    for l in open(dpath('test.jsonl'), encoding='utf-8'):
        r = json.loads(l)
        d[str(r['pmid'])] = r
    return d


def verify(gold_path=None, dump=None, rows=None):
    bench = load_bench()
    if rows is None:
        if gold_path:
            rows = [json.loads(l) for l in open(gold_path, encoding='utf-8')]
        else:
            rows = list(bench.values())
    test = [r for r in rows if r.get('split') == 'test']
    out, idx = [], 0
    for r in test:
        pmid = str(r['pmid'])
        inp = bench.get(pmid, {}).get('input', {})
        text = norm((inp.get('title', '') or '') + ' ' + (inp.get('abstract', '') or ''))
        comp = compact(text)
        gl = r.get('gold', [])
        econ_primary = bool(ECON_TITLE.search(inp.get('title', '') or '')) and \
                       bool(ECON_DESIGN.search(inp.get('abstract', '') or ''))
        case_report = bool(CASE_SERIES.search(inp.get('title', '') or ''))
        # 规则化抽取（未逐篇人工核读）的篇：额外要求 head 在证据句里出现，防止归因不特异
        machine = r.get('gold_type') == 'rule_gate_verified'
        for ci, t in enumerate(gl):
            idx += 1
            f = []
            hid, tid = t.get('head_id', ''), t.get('tail_id', '')
            rel = t.get('relation_id') or t.get('relation', '')
            ev = norm(t.get('evidence', ''))
            ev_l = ev.lower()
            # gold 只存 id：把实体文本还原回原文写法，供下面的语义/特异性规则使用
            head, tail = gold_surface(hid, ev, text), gold_surface(tid, ev, text)

            # 篇级负面清单：经济学评价为主结局 / case series 无对照，整篇不应产出临床三元组
            if econ_primary:
                f.append('ECONOMIC_EVAL')
            if case_report:
                f.append('CASE_SERIES')
            # head 是实验对比条件而非干预实体（"birdsong without car noise"）
            if CONDITION_HEAD.search(head):
                f.append('CONDITION_HEAD')
            # evidence 必须是本篇一手结果句，不是背景/目的/方法句或转述他人研究
            if EV_NOT_RESULT.search(ev):
                f.append('EV_NOT_RESULT')
            if REPORTED_SPEECH.search(ev):
                f.append('REPORTED_SPEECH')
            if LOWER_NO_SIG.search(ev) and not re.search(r'\b(significantly|p\s*[<=]|95\s*%\s*CI)\b', ev, re.I):
                f.append('LOWER_NO_SIG')
            # 规则化抽取篇：head 未出现在证据句里即归因不特异
            if machine and ev and compact(head) not in compact(ev):
                f.append('HEAD_NOT_IN_EV')

            # --- 结构类（客观） ---
            if CJK.search(head) or CJK.search(tail):
                f.append('CJK_ENTITY')
            if CATID.match(hid) or CATID.match(tid):
                f.append('CATEGORY_ID')
            if hid not in ENT_IDS:
                f.append('ENTITY_HEAD')
            if tid not in ENT_IDS:
                f.append('ENTITY_TAIL')
            if not ev:
                f.append('NO_EVIDENCE')
            elif ev not in text:
                f.append('EV_NOT_SUBSTR')
            if len(ev) > 300:
                f.append('EV_TOO_LONG')
            # evidence 不能从/到半个单词处截断（200 字硬切或补句不当中常见）
            if ev:
                p = text.find(ev)
                if p >= 0 and ((p > 0 and text[p - 1].isalnum()) or
                               (p + len(ev) < len(text) and text[p + len(ev)].isalnum())):
                    f.append('EV_MIDWORD')
            if not any_form_in(hid, comp):
                f.append('HEAD_NOT_IN_TEXT')
            if not any_form_in(tid, comp):
                f.append('TAIL_NOT_IN_TEXT')
            # 括号里若是抽取员自加的量表缩写（非原文），已被上面的 *_NOT_IN_TEXT 捕获

            # --- 语义类（逐条判定） ---
            if WEAK.search(ev):
                f.append('WEAK_OR_NEG')
            if BG.search(ev) or VAGUE_EV.search(ev):
                f.append('BACKGROUND_CITATION')
            if FRAG_START.match(ev):
                f.append('EV_FRAGMENT')
            if HEDGE_LIMIT.search(ev):
                f.append('HEDGE_OR_LIMIT')
            if WITHIN_GROUP.search(ev) or (WITHIN2.search(ev) and not COMPARATOR.search(ev)):
                f.append('WITHIN_GROUP_ONLY')
            if HEDGE2.search(ev):
                f.append('HEDGING')
            if re.search(r'\b(associated with|correlated with|significant correlation)\b', ev, re.I) \
                    and not DIR_WORD.search(ev):
                f.append('ASSOC_NO_DIRECTION')
            # 叙述性综述且本条证据无定量结果 -> 不是一手结论
            if NARRATIVE.search(text[:500]) and not QUANT.search(ev):
                f.append('NARRATIVE_REVIEW')
            # evidence 必须直接支撑 tail：tail 实词一个都不出现在证据句里即不通过
            evtk = set(re.findall(r'[a-z]{4,}', ev_l))
            tk = set(re.findall(r'[a-z]{4,}', re.sub(r'\([^)]*\)', ' ', tail.lower())))
            if tk and not (tk & evtk):
                f.append('TAIL_NOT_IN_EV')
            # 注：不检查 head 是否在 evidence。结果句常只写结局而不重复干预名
            # （"Pain scores were significantly lower in the +MUSIC group"），属合法写法。
            # 方向性关系必须建立在有方向的证据上；中性关系（affects/evidence_supports）豁免
            if rel in REDUCE or rel in IMPROVE:
                if NO_DIR.search(ev) and not DIR_WORD.search(ev):
                    f.append('NO_DIRECTION')
                if rel in IMPROVE and SCALE_LOW.search(tail) and not SCALE_HIGH.search(tail):
                    f.append('SCALE_DIRECTION')
            if MEAS_EV.search(ev) and re.search(r'\b(scores?|scale|inventory|index|questionnaire)\b', tail, re.I):
                f.append('MEASUREMENT_AS_TAIL')
            if NONSPEC_HEAD.search(head):
                f.append('NONSPEC_HEAD')
            if GROUP.search(head):
                f.append('GROUP_DESC_HEAD')
            if ci_crosses(ev):
                f.append('CI_CROSSES_NULL')
            # 方向：仅当 tail 无「正向过程」例外词时判定
            if not DIRECTION_OK.search(tail):
                if rel in REDUCE and POS_OUTCOME.search(tail) and not NEG_OUTCOME.search(tail):
                    f.append('DIRECTION_SUSPECT')
                if rel in IMPROVE and NEG_OUTCOME.search(tail) and not POS_OUTCOME.search(tail):
                    f.append('DIRECTION_SUSPECT')
            # 近义 tail：仅同一 head + 同一证据句才判（不同 head 共享 tail 是合法的）
            for cj, t2 in enumerate(gl):
                if cj == ci or t2.get('head_id') != hid:
                    continue
                if norm(t2.get('evidence', '')) == ev and near_dup(tail, t2.get('tail', '')):
                    f.append('NEAR_DUP_TAIL')
                    break

            out.append({'idx': idx, 'pmid': pmid, 'ci': ci,
                        'head': head, 'head_id': hid, 'relation': rel, 'relation_id': rel,
                        'tail': tail, 'tail_id': tid, 'evidence': ev, 'flags': f})
    from collections import Counter
    c = Counter(x for o in out for x in o['flags'])
    if dump:
        Path(dump).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    return out, c, len(test), len(out), sum(1 for o in out if o['flags'])


if __name__ == '__main__':
    dump = sys.argv[sys.argv.index('--json') + 1] if '--json' in sys.argv else None
    out, c, npap, ntri, nflag = verify(dump=dump)
    print(f'test papers : {npap}\ntriples     : {ntri}\nflagged     : {nflag} ({nflag*100//max(ntri,1)}%)')
    print('--- flag counts ---')
    for k, v in c.most_common():
        print(f'  {k:26s} {v}')
    print('--- all flagged (idx/flags/head->tail) ---')
    for o in [x for x in out if x['flags']]:
        print(f"  {o['idx']:4d} [{'/'.join(o['flags'])}] {o['pmid']} | {o['head']} --{o['relation']}--> {o['tail']}")
