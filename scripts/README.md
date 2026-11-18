# scripts —— 全部生产脚本

> 成品数据只有一个目录：`dataset/`（`benchmark/` 三个自包含 split + `schema/` 两个词表）；
> 中间产物全部在 `tmp/`。**脚本里不允许再写相对路径字符串**，统一从 `scripts/_paths.py` 取。

## 目录

```
scripts/
├── _paths.py            统一路径常量（唯一定义处）
│                        DATA=dataset/  BM=dataset/benchmark/  SCHEMA=dataset/schema/
│                        SPLITS=('train','dev','test')  sp(split)→dataset/benchmark/{split}.jsonl
│                        TMP=tmp/  AUX=tmp/benchmark/  RUNS=tmp/benchmark/runs/
│                        HIST=tmp/benchmark/history/  SOURCE=tmp/source/  EVAL=tmp/eval/
│                        p(name) → 成品回 BM、辅助回 AUX、批次中间产物回 RUNS
├── _schema.py           开放实体/关系 schema 的统一读取入口（读 entities.json / relations.json）
│                        text2id() / alias_patterns() / node_en() / rel_zh2en() / legacy_alias()
│                        expand_gold() → gold 只存 id，评测/SFT 用它按 id 补回实体规范写法
├── benchmark/           benchmark 闸门（现役，5 个脚本）
│   ├── _sem_verify.py   test 闸门（读 test.jsonl；条级 20+ 规则，0 flag 才算过）
│   ├── _dev_verify.py   dev(v3) 闸门（读 dev.jsonl，规则集与 test 完全相同）
│   ├── _sem_dump.py     打印闸门 flagged 明细
│   ├── _subset_preview.py  预览 test 的 subset/感官推导（不落盘）
│   ├── _spec_screen.py / _topup_screen.py   新篇预筛（候选打分）
│   └── archive/         历史一次性批次脚本（d01–d33、b01–b05 的 build/apply/fix/选篇、台账同步等，仅存档）
├── pipeline/            数据构建与评测
│   ├── build_bench_splits.py  一次性迁移：把旧合并版拼成 {train,dev,test}.jsonl（已执行）
│   ├── build_entity_schema.py 从 surfaces.json + zh_merged.json 重建 entities.json + relations.json
│   ├── build_train_distant.py v3 远监督 train 构建器（intra/rev 两档归因 + 精度护栏 + 覆盖优先选篇）
│   ├── _train_verify.py       train 闸门（结构/ id/ 证据/ 方向/ 泄漏自检，随构建跑）
│   ├── _train_diag.py         召回损失诊断（no_triple 归因：无实体/无尾/无 cue/语序/间距）
│   ├── _train_sample.py       按 tier × relation 分层抽样，打印 head/cue/tail + 证据句供核读
│   ├── coverage_ceiling.py    实体覆盖理论上限（reachable / devtest_only / absent 三分类，需 --extra-corpus 传全语料）
│   ├── _coverage_rescue.py    覆盖救援：放宽同句间距为未覆盖实体补三元组（--dry-run 先看收益）
│   ├── _relation_probe.py     缺失关系定点排查：打印「线索短语 + 句中≥2 实体」的原始句供人工判读
│   ├── compact_gold_ids.py    一次性：把 gold 的 head/relation/tail 文本压成 *_id（已执行）
│   ├── evaluate_extraction.py strict/relaxed P/R/F1（--strong-only 去噪口径）
│   ├── run_llm_extraction.py  vLLM/HF 推理
│   ├── eval_report.py         批量评测出 results/*.json
│   ├── audit_gold.py / validate_gold.py   gold 噪声审计与协议校验
│   ├── oracle_sim.py / oracle_ablation.py 规则 oracle 上界
│   ├── build_sft_data.py / train_sft.py   SFT 数据与 LoRA 训练
│   ├── extract_open_devtest.py / mine_open_vocab.py  开放实体候选挖掘
│   └── archive/      一次性迁移脚本（convert_to_english / migrate_ontology_v2 /
│                     apply_review_rulings / review_test 旧 500 篇复核工具 /
│                     update_vocab_* / update_vr_ontology / fix_aliases_noise —— 都写旧 schema，仅存档）
├── pubmed/             PubMed 检索 → 语料池 → 图谱（19 py + 63 cjs + 3 js + 2 sh）
│   ├── fetch_entity_papers.py   按实体短语检索 PubMed（--cue-filter / --all-surfaces / --ids-file）
│   ├── fetch_phrase_papers.py   按任意线索短语检索（补稀有关系语料）
│   ├── rank_entities_by_count.py 统计各实体可检索总量，产出 top-N 清单
│   ├── fetch_pubmed.py / fetch_papers_large.py / fetch_topup.py / fetch_supp.py
│   ├── build_dataset.py      v2.0 遗留构建器（产物已废弃，运行会被守门拦下，仅供 annotate() 复用）
│   ├── build_kg*.py          图谱构建
│   ├── verify_*.cjs / diag*.cjs  CDP 页面验证脚本（3D 验证页）
│   └── optimize_siheyuan.py  3D 模型优化（assets/buildings）
└── probe_vllm_api.py / dl_qwen.sh   环境与推理探针
```

## 常用命令（工作目录任意）

```bash
python scripts/benchmark/_sem_verify.py        # test 500 篇 / 961 条 / 0 flag
python scripts/benchmark/_dev_verify.py        # dev  501 篇 / 750 条 / 0 flag
python scripts/benchmark/_train_verify.py      # train 闸门（远监督自检，0 LEAK / 0 EV_NOT_SUBSTR）
python scripts/pipeline/audit_gold.py          # 重算 tmp/benchmark/gold_strength.json
python scripts/pipeline/evaluate_extraction.py preds.jsonl --split test --strict-level
```

## 数据集文件形态

三个 split 文件都是**自包含**的：一行一篇，`input`（title/abstract/year/pubtypes）+ `instruction`
+ `allowed_relations` + `gold`（三元组答案）+ `gold_n` + 子集标记。读数据只需打开对应文件，
不要再去找「题面文件 / 答案文件」两份。

## 下一批（补 dev）流程

1. 候选预筛：`scripts/benchmark/_spec_screen.py` / `_topup_screen.py` 打分
2. 逐篇核读 → 写批次 build 脚本（P 表 + `slice_ev()` 精确取证 + 预检）
3. 落盘：备份 `tmp/benchmark/history/.bak_before_dev_dNN` → 写 `dataset/benchmark/dev.jsonl`
   → 更新 `tmp/benchmark/runs/_used_pmids.json`
4. 跑两个闸门，必须 `flagged 0`

> 历史批次用的 `_build_dNN.py` / `_apply_dNN.py` 双写旧合并版，已归档到 `scripts/benchmark/archive/`；
> 新批次请直接读写 `dataset/benchmark/dev.jsonl`。

## 约定

- 批次中间产物一律写 `RUNS`（`tmp/benchmark/runs/`），成品一律写 `BM`（`dataset/benchmark/`）。
- 备份文件写 `HIST`（`tmp/benchmark/history/`），不参与任何计算。
- 原始语料写 `SOURCE`（`tmp/source/`），评测产物写 `EVAL`（`tmp/eval/`）。
- 若脚本需要新路径，先加到 `_paths.py`，不要在脚本里拼字符串。
