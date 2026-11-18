import sys as _sys, pathlib as _pl
_sys.path.insert(0, str(_pl.Path(__file__).resolve().parents[1]))
import _paths		# 统一路径：dataset/ 是唯一数据目录
# -*- coding: utf-8 -*-
"""
train_sft.py — 在 GPU 服务器上对 Qwen2.5-7B-Instruct 做 LoRA SFT，学习 benchmark 标注协议。

数据：dataset/sft/sft_train.jsonl（{"prompt","completion"}），prompt 部分不计 loss。
用法（服务器）：
  python dataset/train_sft.py --model ~/models/Qwen2.5-7B-Instruct \
      --data dataset/sft/sft_train.jsonl --out ~/sft_digital_healing
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from torch.utils.data import DataLoader, Dataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", default="~/sft_digital_healing")
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--batch", type=int, default=4, help="per-device batch")
    ap.add_argument("--accum", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=2560)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--save-every", type=int, default=100, help="每 N 步保存一次 adapter（0=只在结束时存）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token

    print("加载模型（bf16）...")
    model = AutoModelForCausalLM.from_pretrained(
        args.model, dtype=torch.bfloat16, attn_implementation="sdpa",
        trust_remote_code=True)
    model.gradient_checkpointing_enable()
    model.config.use_cache = False

    lcfg = LoraConfig(r=args.lora_r, lora_alpha=2 * args.lora_r, lora_dropout=0.05,
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                      "gate_proj", "up_proj", "down_proj"],
                      task_type="CAUSAL_LM")
    model = get_peft_model(model, lcfg)
    model.print_trainable_parameters()
    model.cuda()

    rows = [json.loads(l) for l in open(args.data, encoding="utf-8") if l.strip()]
    print("训练样本:", len(rows))

    class SFT(Dataset):
        def __len__(self):
            return len(rows)

        def __getitem__(self, i):
            r = rows[i]
            p_ids = tok(r["prompt"], add_special_tokens=False)["input_ids"]
            c_ids = tok(r["completion"], add_special_tokens=False)["input_ids"]
            c_ids = c_ids + [tok.eos_token_id]
            ids = (p_ids + c_ids)[-args.max_len:]
            n_prompt = max(len(ids) - len(c_ids), 1)
            labels = [-100] * n_prompt + ids[n_prompt:]
            return {"input_ids": ids, "labels": labels}

    def collate(batch):
        mx = max(len(b["input_ids"]) for b in batch)
        input_ids, labels, attn = [], [], []
        for b in batch:
            pad = mx - len(b["input_ids"])
            input_ids.append(b["input_ids"] + [tok.pad_token_id] * pad)
            labels.append(b["labels"] + [-100] * pad)
            attn.append([1] * len(b["input_ids"]) + [0] * pad)
        return (torch.tensor(input_ids), torch.tensor(labels), torch.tensor(attn))

    dl = DataLoader(SFT(), batch_size=args.batch, shuffle=True, collate_fn=collate,
                    num_workers=2, drop_last=True)
    steps_per_epoch = math.ceil(len(dl) / args.accum)
    total_steps = int(steps_per_epoch * args.epochs)

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad],
                            lr=args.lr, weight_decay=0.01, betas=(0.9, 0.95))
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=args.lr, total_steps=total_steps, pct_start=0.03)

    model.train()
    t0 = time.time()
    step = 0
    done = False
    for epoch in range(math.ceil(args.epochs)):
        if done:
            break
        for i, (ids, labels, attn) in enumerate(dl):
            ids, labels, attn = ids.cuda(), labels.cuda(), attn.cuda()
            loss = model(input_ids=ids, attention_mask=attn, labels=labels).loss / args.accum
            loss.backward()
            if (i + 1) % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad], 1.0)
                opt.step()
                sched.step()
                opt.zero_grad(set_to_none=True)
                step += 1
                if args.save_every and step % args.save_every == 0:
                    ckpt = out_dir / ("step_%04d" % step)
                    model.save_pretrained(str(ckpt))
                    print("已保存 checkpoint:", ckpt, flush=True)
                if step % 10 == 0:
                    print("epoch %.1f step %d/%d loss %.4f lr %.2e 已用 %.1f min" % (
                        epoch + (i + 1) / len(dl), step, total_steps,
                        loss.item() * args.accum, sched.get_last_lr()[0],
                        (time.time() - t0) / 60), flush=True)
                if step >= total_steps:
                    done = True
                    break

    print("训练完成，保存 LoRA 到", out_dir)
    model.save_pretrained(str(out_dir))
    tok.save_pretrained(str(out_dir))
    print("总耗时 %.1f min" % ((time.time() - t0) / 60))


if __name__ == "__main__":
    main()
