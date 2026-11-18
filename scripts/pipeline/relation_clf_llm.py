# -*- coding: utf-8 -*-
"""relation_clf_llm.py — 用 Qwen2.5-7B + LoRA 做证据句关系分类。

与 relation_clf.py 数据口径完全相同（给定 head/tail/evidence，预测 12 类关系 id），
区别是基座换成 GPU 服务器本地的 Qwen2.5-7B-Instruct，只训练 LoRA 适配器。

用法：
  python scripts/pipeline/relation_clf_llm.py --mode train \
      --model ~/models/Qwen2.5-7B-Instruct --out tmp/eval/rel_clf_qwen --epochs 2
  python scripts/pipeline/relation_clf_llm.py --mode eval \
      --model tmp/eval/rel_clf_qwen --base ~/models/Qwen2.5-7B-Instruct --split test
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _paths  # noqa: E402
import _schema  # noqa: E402

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (AutoModelForSequenceClassification, AutoTokenizer,
                          DataCollatorWithPadding, Trainer, TrainingArguments,
                          set_seed)

ALL_REL_IDS = list(dict.fromkeys(r['id'] for r in _schema.relations()))
REL_IDS = list(ALL_REL_IDS)
L2I = {r: i for i, r in enumerate(REL_IDS)}


def set_relations(exclude):
    global L2I
    ex = set(exclude or [])
    REL_IDS[:] = [r for r in ALL_REL_IDS if r not in ex]
    L2I = {r: i for i, r in enumerate(REL_IDS)}
    return REL_IDS


def load_split(split, exclude=None):
    idx = _schema.entity_index()
    ex = set(exclude or [])
    rows = []
    for ln in open(_paths.sp(split), encoding='utf-8'):
        g = json.loads(ln)
        for t in g['gold']:
            if t['relation_id'] in ex:
                continue
            ev = t.get('evidence') or ''
            if not ev:
                continue
            rows.append({'text': 'head: %s [SEP] tail: %s [SEP] evidence: %s' %
                                (idx[t['head_id']]['text'], idx[t['tail_id']]['text'], ev),
                         'label': L2I[t['relation_id']]})
    return rows


def compute(p):
    import numpy as np
    from sklearn.metrics import f1_score
    y, pr = p.label_ids, np.argmax(p.predictions, axis=1)
    return {'micro_f1': float((y == pr).mean()),
            'macro_f1': float(f1_score(y, pr, average='macro', zero_division=0))}


def build_model(base, trainable=False):
    tok = AutoTokenizer.from_pretrained(base)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForSequenceClassification.from_pretrained(
        base, num_labels=len(REL_IDS), torch_dtype=torch.bfloat16,
        id2label={i: r for i, r in enumerate(REL_IDS)}, label2id=L2I)
    model.config.pad_token_id = tok.pad_token_id
    if not trainable:
        model = get_peft_model(model, LoraConfig(
            r=16, lora_alpha=32, lora_dropout=0.05, bias='none',
            target_modules=['q_proj', 'k_proj', 'v_proj', 'o_proj'],
            task_type='SEQ_CLS'))
        model.print_trainable_parameters()
    return tok, model


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['train', 'eval'], required=True)
    ap.add_argument('--model', required=True)
    ap.add_argument('--base', default=None)
    ap.add_argument('--out', default=str(_paths.EVAL / 'rel_clf_qwen'))
    ap.add_argument('--split', default='test')
    ap.add_argument('--epochs', type=int, default=2)
    ap.add_argument('--bs', type=int, default=8)
    ap.add_argument('--lr', type=float, default=1e-4)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--exclude', nargs='*', default=[],
                    help='从标签空间与数据中剔除的关系 id（如稀有类）')
    args = ap.parse_args()
    set_relations(args.exclude)
    print('标签空间 (%d): %s' % (len(REL_IDS), REL_IDS))
    set_seed(args.seed)

    if args.mode == 'train':
        tok, model = build_model(args.model)
        train_rows = load_split('train', args.exclude) + load_split('dev', args.exclude)
        dev_rows = load_split('dev', args.exclude)
        ds_tr = Dataset.from_list(train_rows).map(lambda x: tok(x['text'], truncation=True, max_length=384), batched=True)
        ds_dv = Dataset.from_list(dev_rows).map(lambda x: tok(x['text'], truncation=True, max_length=384), batched=True)
        steps = max(1, (len(ds_tr) + args.bs - 1) // args.bs) * args.epochs
        targs = TrainingArguments(
            output_dir=args.out, num_train_epochs=args.epochs,
            per_device_train_batch_size=args.bs, per_device_eval_batch_size=args.bs,
            gradient_accumulation_steps=2, learning_rate=args.lr,
            warmup_steps=max(1, int(0.05 * steps)), weight_decay=0.01,
            bf16=True, eval_strategy='epoch', save_strategy='no',
            logging_steps=50, report_to='none', seed=args.seed)
        trainer = Trainer(model=model, args=targs, train_dataset=ds_tr, eval_dataset=ds_dv,
                          data_collator=DataCollatorWithPadding(tok), compute_metrics=compute)
        trainer.train()
        model.save_pretrained(args.out)
        tok.save_pretrained(args.out)
        print('DEV:', trainer.evaluate(ds_dv))
        print('saved ->', args.out)
        return

    base = args.base or args.model
    tok, _ = build_model(base, trainable=True)
    from peft import PeftModel
    model = AutoModelForSequenceClassification.from_pretrained(
        base, num_labels=len(REL_IDS), torch_dtype=torch.bfloat16,
        id2label={i: r for i, r in enumerate(REL_IDS)}, label2id=L2I)
    model.config.pad_token_id = tok.pad_token_id
    model = PeftModel.from_pretrained(model, args.model)
    rows = load_split(args.split, args.exclude)
    ds = Dataset.from_list(rows).map(lambda x: tok(x['text'], truncation=True, max_length=384), batched=True)
    targs = TrainingArguments(output_dir=str(_paths.EVAL / 'rel_clf_qwen_eval'),
                              per_device_eval_batch_size=args.bs, bf16=True, report_to='none')
    trainer = Trainer(model=model, args=targs, data_collator=DataCollatorWithPadding(tok),
                      compute_metrics=compute)
    res = trainer.predict(ds)
    m = res.metrics
    micro = next((m[k] for k in ('micro_f1', 'eval_micro_f1', 'test_micro_f1') if k in m), 0)
    macro = next((m[k] for k in ('macro_f1', 'eval_macro_f1', 'test_macro_f1') if k in m), 0)
    print('%s: micro_f1=%.4f macro_f1=%.4f' % (args.split, micro, macro))
    import numpy as np
    probs = np.exp(res.predictions.astype(np.float32)) / np.exp(res.predictions.astype(np.float32)).sum(axis=1, keepdims=True)
    dest = _paths.EVAL / ('rel_clf_qwen_pred_%s.jsonl' % args.split)
    with open(dest, 'w', encoding='utf-8') as f:
        for r, pr, pb in zip(rows, res.predictions.argmax(axis=1), probs):
            f.write(json.dumps({**r, 'pred': REL_IDS[int(pr)],
                                'probs': [round(float(x), 6) for x in pb]}, ensure_ascii=False) + '\n')
    print('predictions ->', dest)


if __name__ == '__main__':
    main()
