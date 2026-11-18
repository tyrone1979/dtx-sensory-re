"""项目统一路径入口 —— 任何脚本都从这里取路径，禁止再写相对路径字符串。

目录约定：
    dataset/                       唯一数据目录（只放成品与词表）
        benchmark/                 train.jsonl / dev.jsonl / test.jsonl
                                   （每行含 input + gold，自包含；目录里只放这三个文件）
        schema/                    entities.json（实体表：id/text/text_zh/type）
                                   relations.json（关系表：id/name/name_zh/aliases）
    tmp/                           所有中间产物与副产品（可重跑再生，不入库）
        benchmark/runs/            每批次中间产物（_dev_spec_input_*、_spec_result_*、_dev_dNN_drops.json …）
        benchmark/history/         .bak_* 历史备份与陈旧副本
        benchmark/                 裁定日志、复核抽样、gold 强度等辅助文件
        benchmark/legacy/          已退出成品目录的旧产物（v2 dev 行、复核台账）
        source/                    原始语料（literature.jsonl、knowledge_triples.jsonl、pubmed 池）
        eval/                      评测产物（results、preds、sft）
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # 仓库根
DATA = ROOT / 'dataset'                         # 唯一数据目录（成品）
BM = DATA / 'benchmark'                         # 成品 benchmark（4 个文件）
SCHEMA = DATA / 'schema'                        # 词表

TMP = ROOT / 'tmp'                              # 中间产物根目录
AUX = TMP / 'benchmark'                         # benchmark 辅助文件（裁定/抽样/强度审计）
RUNS = AUX / 'runs'                             # 批次中间产物
HIST = AUX / 'history'                          # 历史备份
SOURCE = TMP / 'source'                         # 原始语料与检索池
EVAL = TMP / 'eval'                             # 评测产物
SCRIPTS = ROOT / 'scripts'
ASSETS = ROOT / 'assets'

# 三个 split 文件都是自包含的：input（title/abstract/instruction）+ gold（三元组答案）
SPLITS = ('train', 'dev', 'test')


def sp(split: str) -> Path:
    """split 文件路径：dataset/benchmark/{train,dev,test}.jsonl"""
    assert split in SPLITS, split
    return BM / f'{split}.jsonl'


# 常用文件
TRAIN = sp('train')
DEV = sp('dev')
TEST = sp('test')
LITERATURE = SOURCE / 'literature.jsonl'
USED_PMIDS = RUNS / '_used_pmids.json'

# 复核台账已退出成品目录，仅作历史留档（tmp/ 不入库）
LEGACY = AUX / 'legacy'
DEV_REVIEW = LEGACY / 'dev_review.jsonl'
TEST_REVIEW = LEGACY / 'test_review.jsonl'

# dataset/benchmark 下只应有这 3 个成品文件
CANONICAL = {'train.jsonl', 'dev.jsonl', 'test.jsonl'}

# benchmark 辅助文件（已移入 tmp/benchmark）
AUX_FILES = {
    'adjudication_log.md', 'review_rulings.json', 'gold_strength.json',
    'open_triples_devtest.jsonl', 'open_candidates_summary.txt', '_semantic_review_spec.txt',
}


def p(name: str) -> Path:
    """按文件名返回真实路径：成品→dataset/benchmark，辅助→tmp/benchmark，批次中间产物→tmp/benchmark/runs。"""
    if name in CANONICAL:
        return BM / name
    if name in AUX_FILES:
        return AUX / name
    return RUNS / name
