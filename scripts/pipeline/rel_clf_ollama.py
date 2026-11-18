# -*- coding: utf-8 -*-
"""rel_clf_ollama.py — 用服务器 Ollama 模型做「证据句关系分类」基线。

输入 head/tail/evidence 已给定，只输出 12 个关系 id 之一；
与 relation_clf.py（BERT 微调）共用数据口径，便于对比。

用法：
  python scripts/pipeline/rel_clf_ollama.py --split test --model qwen2.5-coder:32b
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402
from sklearn.metrics import f1_score, accuracy_score

REL = list(dict.fromkeys(r['id'] for r in _schema.relations()))
DEFINE = {
    'reduces': 'intervention lowers/reduces a negative outcome (pain, anxiety, stress, depression, nausea, etc.)',
    'lowers': 'intervention lowers a numeric/physiological measure (blood pressure, cortisol, heart rate, etc.)',
    'alleviates': 'intervention relieves a symptom or discomfort',
    'improves': 'intervention improves a positive outcome or function (sleep quality, well-being, cognition, etc.)',
    'enhances': 'intervention enhances a positive capacity (immunity, creativity, performance, etc.)',
    'promotes': 'intervention promotes a beneficial process (recovery, relaxation, development, etc.)',
    'strengthens': 'intervention strengthens a capacity or response',
    'stimulates': 'intervention stimulates an activity/response',
    'accelerates': 'intervention shortens time to an outcome',
    'affects': 'direction genuinely unclear or two-sided',
    'evidence_supports': 'sentence mainly states strength of evidence (large effects, more effective than, statistically significant improvement)',
    'adjunct_improves': 'intervention used as an adjunct to another treatment and improves outcome',
}
SYS = ('You are a relation classifier for a sensory-intervention evidence dataset. '
       'Given head entity, tail entity and the evidence sentence from a paper, choose exactly one relation id. '
       'Output ONLY one JSON object: {"relation": "<id>"}.\n'
       'Relation definitions:\n' + '\n'.join('- %s: %s' % (r, DEFINE[r]) for r in REL))


def load(split):
    idx = _schema.entity_index()
    rows = []
    for ln in open(_paths.sp(split), encoding='utf-8'):
        g = json.loads(ln)
        for t in g['gold']:
            ev = t.get('evidence') or ''
            if not ev:
                continue
            rows.append({'head': idx[t['head_id']]['text'], 'tail': idx[t['tail_id']]['text'],
                         'evidence': ev, 'relation': t['relation_id']})
    return rows


def ask(row, model):
    prompt = SYS + '\n\nHead: %s\nTail: %s\nEvidence: %s\nRelation:' % (
        row['head'], row['tail'], row['evidence'])
    data = json.dumps({'model': model, 'prompt': prompt, 'stream': False,
                       'format': 'json', 'options': {'temperature': 0}}).encode('utf-8')
    req = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=data,
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=120) as r:
        out = json.loads(r.read().decode('utf-8'))['response']
    m = re.search(r'\{.*\}', out, re.S)
    if m:
        try:
            rel = json.loads(m.group(0)).get('relation', '')
        except Exception:
            rel = ''
    else:
        rel = out.strip().strip('"')
    return rel if rel in REL else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--split', default='test')
    ap.add_argument('--model', default='qwen2.5-coder:32b')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()
    rows = load(args.split)
    if args.limit:
        rows = rows[:args.limit]
    preds = []
    for i, row in enumerate(rows):
        preds.append(ask(row, args.model))
        if (i + 1) % 50 == 0:
            print('done', i + 1, '/', len(rows), flush=True)
    y = [REL.index(r['relation']) for r in rows]
    p = [REL.index(x) if x else -1 for x in preds]
    valid = [i for i, x in enumerate(p) if x >= 0]
    print('%s n=%d valid=%d micro_f1=%.4f macro_f1=%.4f' %
          (args.split, len(rows), len(valid),
           accuracy_score([y[i] for i in valid], [p[i] for i in valid]),
           f1_score([y[i] for i in valid], [p[i] for i in valid], average='macro', zero_division=0)))
    dest = _paths.EVAL / ('rel_clf_ollama_%s.jsonl' % args.split)
    with open(dest, 'w', encoding='utf-8') as f:
        for r, pr in zip(rows, preds):
            f.write(json.dumps({**r, 'pred': pr}, ensure_ascii=False) + '\n')
    print('predictions ->', dest)


if __name__ == '__main__':
    main()
