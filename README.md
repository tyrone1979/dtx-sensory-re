# dtx-sensory-re

Code for a PubMed open relation-extraction benchmark of multi-sensory non-pharmacological interventions (intervention, relation, outcome).

## Dataset

The released data (train / dev / test JSONL, entity and relation lexica, annotation protocol) is **not** in this repository.

- Figshare: https://doi.org/10.6084/m9.figshare.35037670 (CC0 1.0)

Place the downloaded package so that `dataset/benchmark/{train,dev,test}.jsonl` and `dataset/schema/{entities,relations}.json` match what `scripts/_paths.py` expects (or adjust that file).

## Code layout

```
scripts/
  _paths.py / _schema.py   path + lexicon helpers
  benchmark/               quality gates (dev / test / train)
  pipeline/                distant-supervision builder, RE eval, evidence-sentence classifiers
  pubmed/                  PubMed retrieval helpers used while building the pool
```

Intermediate artefacts go under `tmp/` (gitignored).

## Technical validation (evidence-sentence relation classification)

After the data package is in place (two-label `reduces` / `improves` release):

```bash
# Encoder baselines — Train only, then eval Dev and Test
python scripts/pipeline/relation_clf.py --mode train \
  --model distilbert-base-uncased \
  --out tmp/eval/tv2_distil --epochs 2 --bs 16 --lr 1e-5 --train-split train
python scripts/pipeline/relation_clf.py --mode eval --model tmp/eval/tv2_distil --split test

# Qwen2.5-7B + LoRA (same held-out protocol)
TRAIN_SPLIT=train python scripts/pipeline/relation_clf_llm.py --mode train \
  --model Qwen2.5-7B-Instruct --out tmp/eval/tv2_qwen --epochs 2 --bs 8 --lr 1e-4
```

See `scripts/README.md` for quality gates and extraction evaluation.

## Licence

Code in this repository is released under the MIT Licence. The dataset on Figshare is CC0 1.0.
