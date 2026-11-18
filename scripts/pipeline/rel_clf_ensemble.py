# -*- coding: utf-8 -*-
"""rel_clf_ensemble.py — 关系分类基线的多模型概率平均集成。

输入是若干 *preds_*.jsonl（由 relation_clf.py / relation_clf_llm.py 的 eval 模式产出，
每行含 gold relation 与 12 类 probs），按行对齐后做 softmax 概率平均。

用法：
  python scripts/pipeline/rel_clf_ensemble.py \
      --preds tmp/eval/preds_rel_clf_distil_td.jsonl \
              tmp/eval/preds_rel_clf_bert_td.jsonl \
              tmp/eval/preds_qwen.jsonl \
              tmp/eval/preds_roberta.jsonl \
      --split test --out tmp/eval/results/relation_clf_ensemble_test.json
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

from sklearn.metrics import accuracy_score, f1_score, classification_report

ALL_REL = list(dict.fromkeys(r['id'] for r in _schema.relations()))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preds', nargs='+', required=True)
    ap.add_argument('--split', default='test')
    ap.add_argument('--out', default=None)
    ap.add_argument('--exclude', nargs='*', default=[],
                    help='与训练时一致的关系剔除列表（决定 probs 的类别顺序）')
    args = ap.parse_args()
    ex = set(args.exclude or [])
    REL = [r for r in ALL_REL if r not in ex]
    D = [[json.loads(l) for l in open(p, encoding='utf-8')] for p in args.preds]
    n = len(D[0])
    assert all(len(x) == n for x in D), '预测文件行数不一致'
    gold = [r['relation'] for r in D[0]]
    pred, probs = [], []
    for i in range(n):
        p = [0.0] * len(REL)
        for j in range(len(D)):
            v = D[j][i].get('probs')
            assert v and len(v) == len(REL), '缺少 probs 或类别数不一致: %s' % args.preds[j]
            p = [a + b for a, b in zip(p, v)]
        p = [x / len(D) for x in p]
        probs.append(p)
        pred.append(REL[max(range(len(p)), key=lambda k: p[k])])

    micro = accuracy_score(gold, pred)
    macro = f1_score(gold, pred, average='macro', zero_division=0)
    labels = sorted(set(gold))
    rep = classification_report(gold, pred, labels=labels,
                                target_names=labels,
                                output_dict=True, zero_division=0)
    print('%s ensemble(%d models): micro_f1=%.4f macro_f1=%.4f (n=%d)' %
          (args.split, len(D), micro, macro, n))
    out = args.out or str(_paths.EVAL / 'results' / ('relation_clf_ensemble_%s.json' % args.split))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps({'split': args.split, 'models': args.preds,
                                     'n': n, 'micro_f1': micro, 'macro_f1': macro,
                                     'per_class': rep}, ensure_ascii=False, indent=2), encoding='utf-8')
    print('结果 ->', out)


if __name__ == '__main__':
    main()
