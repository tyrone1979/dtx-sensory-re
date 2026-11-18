# -*- coding: utf-8 -*-
"""开放实体 / 关系 schema 的统一读取入口。

数据源只有两个（都在 dataset/schema/）：
  entities.json    [{"id","text","text_zh","type"}]    一条记录一个写法
  relations.json [{"id","name","name_zh"}]           一条记录一个写法

同一实体的不同写法（复数、缩写、词序、连字符）各占一条记录并共用同一个 id，
因此「id 相同」就是别名关系，不再有 aliases 字段，也不再需要
entity_aliases.json / relation_en.json / node_en.json。

旧脚本按 v2.0 的三种字典形状取词表，这里给出等价视图，避免逐处重写：
  node_en()        {id: 英文规范名}
  rel_zh2en()      {中文名: 英文 id}
  legacy_alias()   {"head_aliases": {id: [正则源串]}, "tail_aliases": {...}, "negative_context": []}
"""
import json
import re
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import _paths

_CACHE = {}


def _load(name):
    if name not in _CACHE:
        _CACHE[name] = json.loads((_paths.SCHEMA / name).read_text(encoding='utf-8'))
    return _CACHE[name]


def entities():
    return _load('entities.json')


def relations():
    return _load('relations.json')


def entity_index():
    """{id: record}，同一 id 多写法时取规范写法（slug 与 id 一致的那条）"""
    out = {}
    for e in entities():
        cur = out.get(e['id'])
        if cur is None:
            out[e['id']] = e
        elif re.sub(r'[^a-z0-9]+', '_', e['text'].lower()).strip('_') == e['id']:
            out[e['id']] = e
    return out


def text2id():
    """{surface form（小写）: id}。用于把模型输出归一到实体 id。"""
    if 'text2id' not in _CACHE:
        m = {}
        for e in entities():
            m.setdefault(e['text'].lower(), e['id'])
        _CACHE['text2id'] = m
    return _CACHE['text2id']


def alias_patterns():
    """{id: [已编译正则]}，同一 id 下所有写法都收进来，用于旧版正则召回式匹配。"""
    if 'pats' not in _CACHE:
        out = {}
        for e in entities():
            out.setdefault(e['id'], []).append(re.compile(r'\b%s\b' % re.escape(e['text']), re.I))
        _CACHE['pats'] = out
    return _CACHE['pats']


def node_en():
    """旧 node_en.json 的等价物：{id: 英文规范名}。"""
    return {i: e['text'] for i, e in entity_index().items()}


def expand_gold(gold):
    """gold 只存 id（head_id / relation_id / tail_id）。评测、SFT、抽样预览这些老代码
    还在读 t["head"] / t["relation"] / t["tail"]，这里按 id 补回规范写法再交出去。"""
    idx = entity_index()
    out = []
    for g in gold:
        d = dict(g)
        d['head'] = idx.get(g.get('head_id', ''), {}).get('text', '')
        d['tail'] = idx.get(g.get('tail_id', ''), {}).get('text', '')
        d['relation'] = g.get('relation_id') or g.get('relation', '')
        out.append(d)
    return out


def rel_name2id():
    """{关系写法（小写）: 关系 id}，含别名写法。"""
    return {r['name'].lower(): r['id'] for r in relations()}


def rel_zh2en():
    """旧 relation_en.json 的等价物：{中文名: 英文 id}（含别名写法）。"""
    m = {}
    for r in relations():
        m.setdefault(r['name_zh'], r['id'])
        m.setdefault(r['name'], r['id'])
    return m


def rel_ids():
    return {r['id'] for r in relations()}


def rel_name2zh():
    return {r['id']: r['name_zh'] for r in relations()}


def legacy_alias():
    """旧 entity_aliases.json 的等价物：head/tail 词表 + 空 negative_context。"""
    pats = {i: [rx.pattern.replace('\\b', '') for rx in v] for i, v in alias_patterns().items()}
    return {'head_aliases': pats, 'tail_aliases': pats, 'negative_context': [],
            'trigger_words': (r'\b(improv|reduc|decreas|increas|alleviat|reliev|enhanc|lower|'
                              r'promot|ameliorat|attenuat|mitigat)\w*\b')}
