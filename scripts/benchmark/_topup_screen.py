import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
from _paths import p
# -*- coding: utf-8 -*-
"""补齐 test 500：按 5 类感官宽筛候选（味觉已另有 graded 名单）。
只做检索启发，gold 仍按 v3 开放实体范式逐篇抽取。"""
import json, re, random

USED = set(json.load(open(str(_paths.USED_PMIDS), encoding='utf-8')))
NEG_PT = ('Review', 'Meta-Analysis', 'Systematic Review', 'Protocol',
          'Case Reports', 'Scoping Review', 'Narrative Review', 'Comment',
          'Editorial', 'Published Erratum', 'Interview', 'Lecture')

KW = {
 'visual': [r'window', r'\bview', r'green space', r'greenness', r'garden', r'forest\b',
            r'nature', r'natural environment', r'landscape', r'daylight', r'natural light',
            r'sunlight', r'bright light', r'blue light', r'light exposure', r'\bart\b',
            r'painting', r'artwork', r'photo', r'picture', r'\bvideo', r'virtual reality',
            r'\bVR\b', r'\bcolor', r'\bplant', r'\bsky', r'visual'],
 'auditory': [r'\bmusic', r'\bsound', r'\bnoise', r'\bsinging', r'\bsong', r'rhythm',
              r'binaural', r'white noise', r'nature sound', r'\bvoice', r'audio'],
 'olfactory': [r'aroma', r'essential oil', r'\bscent', r'\bsmell', r'\bodor', r'\bodour',
               r'fragrance', r'lavender', r'incense', r'olfactory', r'bergamot', r'jasmine',
               r'\brose\b', r'peppermint', r'eucalyptus', r'citrus', r'sandalwood'],
 'tactile': [r'massage', r'acupressure', r'\btouch', r'foot bath', r'footbath', r'footbath',
             r'warm', r'warmth', r'thermal', r'\bspa\b', r'hydrotherapy', r'\bbath',
             r'balneotherapy', r'weighted blanket', r'kangaroo care', r'skin-to-skin',
             r'reflexology', r'tuina', r'moxibustion', r'hot spring', r'warming'],
 'perceptual': [r'mindfulness', r'meditation', r'relaxation', r'breathing exercise',
                r'slow breathing', r'virtual reality', r'\bVR\b', r'immersive',
                r'autogenic training', r'guided imagery', r'progressive muscle',
                r'hypnosis', r'hypnotherapy', r'biofeedback', r'yoga', r'tai chi',
                r'qigong', r'music therapy', r'cognitive'],
}

def has_kw(txt, pats):
    for p in pats:
        if re.search(p, txt, re.I):
            return True
    return False

def neg_text(txt):
    # 明显不可抽的信号（动物/体外等），仅粗筛，细判在读批时做
    return re.search(r'\b(mice|mouse|rats?\b|zebrafish|drosophila|cells?\b|in vitro|in vivo|pigs?\b|rabbits?)\b', txt, re.I)

RESULT_SIG = re.compile(
    r'significan|p\s*[<=]\s*0?\.0|p\s*=\s*0?\.0\d|improv|reduc|decreas|lower(?:ed)?|effect', re.I)
DESIGN_SIG = re.compile(
    r'random|RCT|trial|participants|patients|subjects|group|controlled', re.I)

NEG_TITLE = re.compile(
    r'systematic review|meta-?analys|scoping review|narrative review|literature review'
    r'|review of( the)? .*(evidence|studies|literature)|protocol (of|for)|study protocol'
    r'|overview of|evidence mapping|umbrella', re.I)

def main():
    pools = {k: [] for k in KW}
    with open(str(_paths.LITERATURE), encoding='utf-8') as f:
        for line in f:
            d = json.loads(line)
            if d['pmid'] in USED:
                continue
            try:
                pts = eval(d.get('pubtypes') or '[]')
            except Exception:
                pts = []
            if any(p in pts for p in NEG_PT):
                continue
            title = d.get('title') or ''
            abstract = d.get('abstract') or ''
            if NEG_TITLE.search(title):
                continue
            if len(abstract) < 200:
                continue
            if not DESIGN_SIG.search(abstract) or not RESULT_SIG.search(abstract):
                continue
            txt = title + ' ' + abstract
            if neg_text(txt):
                continue
            # 类关键词必须命中标题（大幅收紧），摘要仅作为可读性保障
            tcls = None
            for cls, pats in KW.items():
                if has_kw(title, pats):
                    tcls = cls
                    break
            if not tcls:
                continue
            pools[tcls].append(d)
    out = []
    for cls, items in pools.items():
        # 优先证据等级高、期刊质量好的
        items.sort(key=lambda x: (x.get('evidence_level') in ('A', 'B'),
                                  -(x.get('journal_if') or 0)), reverse=True)
        for d in items:
            out.append({'cls': cls, 'pmid': d['pmid'], 'title': d['title'],
                        'abstract': d['abstract'], 'evidence_level': d.get('evidence_level'),
                        'journal_if': d.get('journal_if'), 'year': d.get('year')})
    with open(p('_topup_pool.jsonl'), 'w', encoding='utf-8') as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    from collections import Counter
    print('pool size per class:', Counter(r['cls'] for r in out))

if __name__ == '__main__':
    main()
