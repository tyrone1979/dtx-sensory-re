# -*- coding: utf-8 -*-
"""relation_clf.py — 给定 head / tail / evidence 的关系分类模型（数据集论文基线）。

任务设定
--------
输入：一篇论文中已标出的头实体、尾实体和一手证据句（gold evidence）；
输出：12 个关系 id 之一。这是数据集的「证据句关系分类」子任务，
      与端到端三元组抽取分开报告，避免把实体发现难度混入关系判定。

数据
----
train / dev / test 三个 split 的 gold 三元组（head_id / tail_id / relation_id），
用 scripts/_schema.py 展开实体文本；evidence 直接取 gold 中的原文证据句。

用法（GPU 服务器，需 torch + transformers + evaluate）
------------------------------------------------------
  python scripts/pipeline/relation_clf.py --mode train \
      --model bert-base-uncased --out tmp/eval/rel_clf_bert \
      --epochs 4 --bs 16

  python scripts/pipeline/relation_clf.py --mode eval \
      --model tmp/eval/rel_clf_bert --split test

指标
----
micro-F1 = 整体准确率（三元组级）；macro-F1 = 12 类宏平均。
论文若只报一个 F1，请注明是 micro（accuracy）还是 macro。
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

from datasets import Dataset
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, Trainer, TrainingArguments,
                          set_seed)

# relations.json 每个 id 有多个别名写法（49 行 / 12 个 id），必须去重后再建标签空间
ALL_REL_IDS = list(dict.fromkeys(r['id'] for r in _schema.relations()))
REL_IDS = list(ALL_REL_IDS)  # 可变：按 --exclude 原地缩减，保持外部引用一致
L2I = {r: i for i, r in enumerate(REL_IDS)}


def set_relations(exclude):
    """按剔除列表重建标签空间（原地修改 REL_IDS，返回它）。"""
    global L2I
    ex = set(exclude or [])
    REL_IDS[:] = [r for r in ALL_REL_IDS if r not in ex]
    L2I = {r: i for i, r in enumerate(REL_IDS)}
    return REL_IDS


def input_text(head, tail, evidence):
    return 'head: %s [SEP] tail: %s [SEP] evidence: %s' % (head, tail, evidence)


def load_split(split, exclude=None):
    idx = _schema.entity_index()
    ex = set(exclude or [])
    rows = []
    for ln in open(_paths.sp(split), encoding='utf-8'):
        g = json.loads(ln)
        for t in g['gold']:
            if t['relation_id'] in ex:
                continue
            h = idx[t['head_id']]['text']
            w = idx[t['tail_id']]['text']
            ev = t.get('evidence') or ''
            if not ev:
                continue
            rows.append({'text': input_text(h, w, ev),
                         'label': L2I[t['relation_id']],
                         'task_id': g['task_id'],
                         'head': h, 'tail': w, 'evidence': ev,
                         'relation': t['relation_id']})
    return rows


def metrics_builder():
    import numpy as np
    try:
        from sklearn.metrics import f1_score
    except ImportError:
        f1_score = None

    def f(p):
        y, pred = p.label_ids, np.argmax(p.predictions, axis=1)
        acc = float((y == pred).mean())
        out = {'micro_f1': acc, 'accuracy': acc}
        if f1_score is not None:
            out['macro_f1'] = float(f1_score(y, pred, average='macro', zero_division=0))
        return out
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['train', 'eval'], required=True)
    ap.add_argument('--model', required=True, help='训练时=基座模型名；评测时=微调后目录')
    ap.add_argument('--out', default=str(_paths.EVAL / 'rel_clf'))
    ap.add_argument('--split', default='test')
    ap.add_argument('--epochs', type=int, default=4)
    ap.add_argument('--bs', type=int, default=16)
    ap.add_argument('--lr', type=float, default=2e-5)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--train-split', default='train',
                    help='训练数据来源：train 或 train+dev（后者不能再用 dev 做验证）')
    ap.add_argument('--exclude', nargs='*', default=[],
                    help='从标签空间与数据中剔除的关系 id（如稀有类）')
    args = ap.parse_args()
    set_relations(args.exclude)
    print('标签空间 (%d): %s' % (len(REL_IDS), REL_IDS))
    set_seed(args.seed)
    random.seed(args.seed)

    tok = AutoTokenizer.from_pretrained(args.model)
    compute = metrics_builder()

    if args.mode == 'train':
        train_rows = load_split('train', args.exclude)
        if 'dev' in args.train_split and args.train_split != 'dev':
            train_rows += load_split('dev', args.exclude)
        dev_rows = load_split('dev', args.exclude)
        ds_tr = Dataset.from_list(train_rows).map(lambda x: tok(x['text'], truncation=True, max_length=384), batched=True)
        ds_dv = Dataset.from_list(dev_rows).map(lambda x: tok(x['text'], truncation=True, max_length=384), batched=True)
        coll = DataCollatorWithPadding(tok)
        model = AutoModelForSequenceClassification.from_pretrained(
            args.model, num_labels=len(REL_IDS), id2label={i: r for i, r in enumerate(REL_IDS)},
            label2id=L2I)
        # transformers 5.x 已移除 warmup_ratio，用 warmup_steps 代替（约 10% 总步数）
        steps_per_epoch = max(1, (len(train_rows) + args.bs - 1) // args.bs)
        warmup_steps = max(1, int(0.1 * steps_per_epoch * args.epochs))
        targs = TrainingArguments(
            output_dir=args.out, num_train_epochs=args.epochs,
            per_device_train_batch_size=args.bs, per_device_eval_batch_size=args.bs,
            learning_rate=args.lr, warmup_steps=warmup_steps, weight_decay=0.01,
            eval_strategy='epoch', save_strategy='epoch', save_total_limit=2,
            load_best_model_at_end=True, metric_for_best_model='micro_f1',
            greater_is_better=True, logging_steps=50, report_to='none', seed=args.seed)
        trainer = Trainer(model=model, args=targs, train_dataset=ds_tr,
                          eval_dataset=ds_dv, data_collator=coll, compute_metrics=compute)
        trainer.train()
        trainer.save_model(args.out)
        tok.save_pretrained(args.out)
        res = trainer.evaluate(ds_dv)
        print('DEV:', json.dumps(res, ensure_ascii=False))
        print('saved ->', args.out)
        return

    rows = load_split(args.split, args.exclude)
    ds = Dataset.from_list(rows).map(lambda x: tok(x['text'], truncation=True, max_length=384), batched=True)
    model = AutoModelForSequenceClassification.from_pretrained(args.model)
    targs = TrainingArguments(output_dir=str(_paths.EVAL / 'rel_clf_eval'),
                              per_device_eval_batch_size=args.bs, report_to='none')
    trainer = Trainer(model=model, args=targs, data_collator=DataCollatorWithPadding(tok),
                      compute_metrics=compute)
    res = trainer.predict(ds)
    m = res.metrics
    def g(key):
        for k in (key, 'eval_' + key, 'test_' + key):
            if k in m:
                return m[k]
        return 0.0
    micro, macro = g('micro_f1'), g('macro_f1')
    print('%s: micro_f1=%.4f macro_f1=%.4f  raw=%s' % (args.split, micro, macro, m))
    import numpy as np
    probs = np.exp(res.predictions) / np.exp(res.predictions).sum(axis=1, keepdims=True)
    dest = _paths.EVAL / ('rel_clf_pred_%s.jsonl' % args.split)
    with open(dest, 'w', encoding='utf-8') as f:
        for r, p, pb in zip(rows, res.predictions.argmax(axis=1), probs):
            f.write(json.dumps({**r, 'pred': REL_IDS[int(p)],
                                'probs': [round(float(x), 6) for x in pb]}, ensure_ascii=False) + '\n')
    print('predictions ->', dest)


if __name__ == '__main__':
    main()
