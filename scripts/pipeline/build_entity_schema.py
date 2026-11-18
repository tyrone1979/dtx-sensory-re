# -*- coding: utf-8 -*-
"""从 dev + test 的 head/tail 重建开放实体 schema（entities.json / relations.json）。

产出（扁平记录：一条记录一个写法，同一 id 的多条记录互为别名——不再有 aliases 字段）：
  dataset/schema/entities.json    [{"id","text","text_zh","type"}]
  dataset/schema/relations.json [{"id","name","name_zh"}]

id 为规范实体的 slug；复数、缩写、词序、连字符等不同写法各占一条记录并共用同一个 id，
因此不再需要独立的 entity_aliases.json / relation_en.json。

同时把 dev.jsonl / test.jsonl 里 alias 写法的 head_id/tail_id 改写为规范 id，
gold 里只存 id（head_id / relation_id / tail_id），实体文本由 tmp/schema/surfaces.json 持有；
本脚本把「id → 写法 + 中文名 + 感官类型」合成 entities.json。

用法：
  python scripts/pipeline/build_entity_schema.py            # 生成并回写 id
  python scripts/pipeline/build_entity_schema.py --dry-run  # 只报告，不写盘
"""
import argparse
import collections
import json
import shutil
import sys
import unicodedata
import pathlib
import re

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import _paths

SURF = _paths.TMP / 'schema' / 'surfaces.json'      # {id: [原文写法...]}，gold 压缩后实体文本的存放处
ZH = _paths.TMP / 'schema' / 'zh_merged.json'       # {id: [中文名, type]}

# 规范 id -> 归并进来的别名 slug（人工裁定：同一实体的不同写法，不含上下位关系）
ALIASES = {
    # 穴位按压
    'p6_acupressure': ['acupressure_at_p6', 'acupressure_at_the_p6_point',
                       'acupressure_applied_to_p6_acupuncture_point',
                       'acupressure_applied_to_the_pc6_point'],
    'acupressure_wristband': ['acupressure_wristbands'],
    'self_administered_acupressure': ['self_delivered_acupressure'],
    'auricular_acupressure': ['auricular_point_acupressure', 'auricular_acupressure_therapy'],
    # 芳香/精油
    'aromatherapy_massage_with_lavender_oil': ['massage_with_lavender_oil',
                                               'massage_therapy_with_lavender_oil',
                                               'lavender_essential_oil_massage'],
    # 虚拟现实
    'vr_distraction': ['virtual_reality_distraction'],
    'vr_distraction_intervention': ['virtual_reality_distraction_intervention'],
    'vr_video': ['virtual_reality_video'],
    'vr_glasses': ['virtual_reality_glass', 'virtual_glasses'],
    'vr_goggles': ['virtual_reality_goggles'],
    'vr_headset': ['vr_headsets', 'virtual_reality_headset'],
    # 光
    'blue_light': ['blue_light_exposure'],
    'blue_light_therapy': ['blue_light_treatment'],
    'bright_light_at_10_000_lux': ['white_light_10_000_lux'],
    # 声
    'binaural_beats': ['binaural_beat_audio', 'binaural_beat_exposure', 'binaural_beat_stimulation'],
    'ocean_sound': ['ocean_sounds'],
    # 触觉/温度
    'foot_bath': ['foot_baths', 'footbath'],
    'weighted_blanket': ['heavy_weighted_blanket'],
    'forced_air_warming': ['active_forced_air_warming'],
    # 正念/冥想
    'mindfulness_based_stress_reduction': ['mindfulness_based_stress_reduction_mbsr', 'mbsr'],
    'mindfulness_meditation': ['mindfulness_meditation_mm'],
    'brief_mindfulness_meditation': ['brief_mindfulness_meditation_bmm'],
    'mindfulness_training': ['mindfulness_based_training'],
    'classical_music_listening': ['listening_to_classical_music'],
    # 环境
    'forest_environment': ['forest_environments'],
    # 结局/量表
    'anxiety': ['anxiety_level', 'anxiety_levels', 'level_of_anxiety'],
    'anxiety_score': ['anxiety_scores'],
    'anxiety_symptoms': ['symptoms_of_anxiety'],
    'depressive_and_anxiety_symptoms': ['symptoms_of_anxiety_and_depression'],
    'gad_7_score': ['gad_7_scores'],
    'epds_score': ['epds_scores'],
    'psqi_score': ['psqi_scores'],
    'sds_score': ['sds_scores'],
    'vas_score': ['vas', 'vas_scores', 'vas_value', 'vas_values'],
    'pain_score': ['pain_scores'],
    'pain_intensity': ['intensity_of_pain'],
    'pain_severity': ['severity_of_pain'],
    'pain_perception': ['pain_perceptions'],
    'mood_disturbance': ['mood_disturbances'],
    'quality_of_life': ['qol', 'qol_scores'],
    'quality_of_sleep': ['sleep_quality'],
    'heart_rate_variability': ['hrv', 'heart_rate_variability_sdnn'],
    'sdnn': ['sdnn_hrv'],
    'respiratory_rate': ['respiratory_rates'],
    'stress_level': ['stress_levels'],
    'sleep_onset_latency': ['sleep_latency'],
    'mental_well_being': ['mental_wellbeing'],
    'vigor': ['vigour'],
    'labour_pain': ['labor_pain'],
    'hypothermia_incidence': ['incidence_of_hypothermia'],
    'perceived_stress': ['perceived_stress_scores', 'scores_for_perceived_stress'],
}

# 旧 82 篇 dev 行没有条级 senses，这 54 个干预实体的通道在此人工指定。
# 口径与 test 一致：按摩/按压/触摸/足浴/加温/重力毯 → tactile；精油与气味 → olfactory；
# VR/光照/影像 → visual；沐浴类（含硫磺浴，按 test 惯例）→ tactile；躯体练习 → perceptual。
SENSE_MANUAL = {
    'abdominal_hypopressive_gymnastics': 'perceptual',
    'active_acupressure': 'tactile',
    'acupoint_hot_compress': 'tactile',
    'acupressure_with_ice': 'tactile',
    'acupuncture_massage': 'tactile',
    'aromatherapy_of_lavandula': 'olfactory',
    'automated_massage_chair': 'tactile',
    'ayurvedic_massage': 'tactile',
    'brush_stroking_targeting_c_tactile_fibres': 'tactile',
    'circulating_water_mattress': 'tactile',
    'citrus_aurantium': 'olfactory',
    'ct_optimal_touch': 'tactile',
    'food_odors': 'olfactory',
    'foot_reflexology_massage': 'tactile',
    'healing_touch': 'tactile',
    'hegu_point_acupressure': 'tactile',
    'hot_stone_massage': 'tactile',
    'immersive_vr_based_intervention': 'visual',
    'immersive_vr_distraction': 'visual',
    'immersive_vr_distraction_therapy': 'visual',
    'immersive_vr_therapy': 'visual',
    'lavender_scent': 'olfactory',
    'lychee_scented_candles': 'olfactory',
    'moderate_pressure_massage_of_the_upper_back': 'tactile',
    'moxibustion_at_the_dazhui_point': 'tactile',
    'on_table_vr': 'visual',
    'peppermint_and_rose_essential_oils': 'olfactory',
    'phototherapy': 'visual',
    'phytoncide_odor': 'olfactory',
    'qtc_vr': 'visual',
    'reflective_blankets': 'tactile',
    'reflexology_hand_massage': 'tactile',
    'rose_oil': 'olfactory',
    'rose_oil_aromatherapy': 'olfactory',
    'self_guided_virtual_reality': 'visual',
    'slow_soft_brushing_of_their_forearm': 'tactile',
    'sulfur_baths': 'tactile',
    'sweet_orange': 'olfactory',
    'synergistic_blend_of_essential_oils': 'olfactory',
    'synthetic_motion_pictures': 'visual',
    'thai_massage': 'tactile',
    'therapeutic_touch': 'tactile',
    'thermal_brine_hand_baths': 'tactile',
    'topical_lavender_oil': 'olfactory',
    'virtual_reality_application': 'visual',
    'virtual_reality_based_cue_exposure_therapy': 'visual',
    'virtual_reality_based_operating_room_tour': 'visual',
    'vr_based_relaxing_treatment': 'visual',
    'vr_distraction_therapy': 'visual',
    'vr_self_hypnosis': 'visual',
    'vr_with_hrvbf': 'visual',
    'warm_foot_bath': 'tactile',
    'warm_salt_water_foot_bath': 'tactile',
    'warm_touch': 'tactile',
}

SENSES = ('visual', 'auditory', 'olfactory', 'gustatory', 'tactile', 'perceptual')

# 语义上是被测量的结局，只是在这几条里被当成 head 写了 —— type 按实体本身定性，不按槽位。
TYPE_MANUAL = {
    'attitude_toward_the_uncovered_biophilic_design_features': 'outcome',
    'natural_environment_perception': 'outcome',
}

REL_ZH = {
    'promotes': ('促进', ['promote', 'promoted', 'promoting']),
    'reduces': ('减轻', ['reduce', 'reduced', 'reducing', 'decrease', 'decreased', 'decreases']),
    'stimulates': ('刺激', ['stimulate', 'stimulated', 'stimulating']),
    'accelerates': ('加速', ['accelerate', 'accelerated', 'accelerating']),
    'strengthens': ('增强', ['strengthen', 'strengthened', 'strengthening']),
    'affects': ('影响', ['affect', 'affected', 'affecting']),
    'evidence_supports': ('循证依据', ['evidence support', 'supported by evidence']),
    'enhances': ('提升', ['enhance', 'enhanced', 'enhancing']),
    'improves': ('改善', ['improve', 'improved', 'improving']),
    'alleviates': ('缓解', ['alleviate', 'alleviated', 'alleviating']),
    'adjunct_improves': ('辅助改善', ['improves as an adjunct', 'adjunctively improves']),
    'lowers': ('降低', ['lower', 'lowered', 'lowering']),
}


def slug(s):
    s = unicodedata.normalize('NFKD', s or '')
    return re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if SURF.exists():
        surf_map = json.load(open(SURF, encoding='utf-8'))      # id -> [原文写法...]
    else:                                                       # 兜底：从现有 entities.json 反推
        surf_map = collections.defaultdict(list)
        for e in _schema.entities():
            surf_map[e['id']].append(e['text'])
    zh = json.load(open(ZH, encoding='utf-8'))                 # id -> [中文名, type]

    text_of = collections.defaultdict(list)              # slug/id -> [text...]
    roles = collections.defaultdict(set)
    for eid, forms in surf_map.items():
        text_of[eid] += forms
    for sp in ('dev', 'test'):
        for line in open(_paths.sp(sp), encoding='utf-8'):
            for g in json.loads(line)['gold']:
                roles[g['head_id']].add('head')
                roles[g['tail_id']].add('tail')
    missing_zh = sorted(set(text_of) - set(zh))
    assert not missing_zh, '这些实体缺中文名/类型，需补 tmp/schema/zh_merged.json: %s' % missing_zh[:10]

    # 别名归并已经沉淀进 surfaces.json（同一个 id 下挂着全部写法），这里不再重新分组。
    # ALIASES 保留为归并依据的存档，只做一致性提示：规范 id 必须还在实体表里。
    lost = [c for c in ALIASES if c not in text_of]
    assert not lost, 'ALIASES 里的规范 id 已不在实体表: %s' % lost[:5]
    groups = {eid: [eid] for eid in text_of}

    # ---- 干预实体的感官类型：从 gold 条级 senses 反推（head 实体）----
    # 一篇多条的 senses 可能不同（同一干预在不同论文里叠加了别的通道），按「写法组合」投票：
    # 取众数；并列时优先感官数更少的那一组（按摩 + 附带香薰仍算 tactile）。
    agg = collections.defaultdict(collections.Counter)
    for sp in ('dev', 'test'):
        for line in open(_paths.sp(sp), encoding='utf-8'):
            for g in json.loads(line)['gold']:
                ss = frozenset(g.get('senses') or [])
                if ss:
                    agg[g['head_id']][ss] += 1

    def sense_type(eid):
        if eid in SENSE_MANUAL:
            return SENSE_MANUAL[eid]
        c = agg.get(eid)
        if not c:
            raise SystemExit('干预实体缺 senses，需在 SENSE_MANUAL 指定: %s' % eid)
        best = sorted(c.items(), key=lambda kv: (-kv[1], len(kv[0]), sorted(kv[0])))[0][0]
        return 'multiple_senses' if len(best) > 1 else next(iter(best))

    # ---- entities.json ----
    # 一条记录 = 一个具体写法（text）。同一实体的不同写法各占一条记录、共用同一个 id，
    # 因此「id 相同」本身就是别名关系，不需要额外的 aliases 字段，也不需要 entity_aliases.json。
    ents, text2id = [], {}
    for cid, members in sorted(groups.items()):
        surf = []
        for m in members:
            surf += text_of[m]
        surf = sorted(set(surf))
        rl = set()
        for m in members:
            rl |= roles[m]
        types = {zh[m][1] for m in members}
        if rl == {'head'}:
            etype = 'context' if ('context' in types and 'intervention' not in types) else sense_type(cid)
        else:
            etype = 'outcome'
        etype = TYPE_MANUAL.get(cid, etype)
        for t in surf:
            ents.append({'id': cid, 'text': t, 'text_zh': zh[cid][0], 'type': etype})
            text2id[t.lower()] = cid

    # ---- relations.json ----
    # 同样是一条记录一个写法：24 个关系 id + 若干别名写法，同 id 即同一关系。
    rels = []
    for rid, (zhname, al) in REL_ZH.items():
        rels.append({'id': rid, 'name': rid, 'name_zh': zhname})
        for a in al:
            rels.append({'id': rid, 'name': a, 'name_zh': zhname})
    seen = collections.Counter(r['name'].lower() for r in rels)
    dup = [k for k, v in seen.items() if v > 1]
    assert not dup, dup

    # ---- 校验 dev/test：gold 是纯 id，必须都能在实体表里找到 ----
    bad_ids = collections.Counter()
    for sp in ('dev', 'test'):
        for line in open(_paths.sp(sp), encoding='utf-8'):
            for g in json.loads(line)['gold']:
                for role in ('head_id', 'tail_id'):
                    if g[role] not in text_of:
                        bad_ids[g[role]] += 1
    assert not bad_ids, 'gold 里有未登记的 id: %s' % list(bad_ids)[:10]

    multi = collections.Counter(e['id'] for e in ents)
    print('entity rows:', len(ents), '| ids:', len(multi),
          '| 有别名写法的实体:', sum(1 for v in multi.values() if v > 1))
    print('relation rows:', len(rels), '| ids:', len({r['id'] for r in rels}))
    by_type = collections.Counter({e['id']: e['type'] for e in ents}.values())
    bad = set(by_type) - set(SENSES) - {'multiple_senses', 'outcome', 'context'}
    assert not bad, '非法 type: %s' % bad
    print('type:', ' '.join('%s=%d' % (k, by_type[k]) for k in
                            ['visual', 'auditory', 'olfactory', 'gustatory', 'tactile',
                             'perceptual', 'multiple_senses', 'outcome', 'context'] if by_type[k]))

    if args.dry_run:
        return

    for f in ('entity_aliases.json', 'relation_en.json', 'node_en.json'):
        p = _paths.SCHEMA / f
        if p.exists():
            shutil.copy(p, _paths.HIST / ('.bak_schema_' + f))
            p.unlink()
            print('removed', f, '(backup in tmp/benchmark/history)')

    (_paths.SCHEMA / 'entities.json').write_text(
        json.dumps(ents, ensure_ascii=False, indent=1), encoding='utf-8')
    (_paths.SCHEMA / 'relations.json').write_text(
        json.dumps(rels, ensure_ascii=False, indent=1), encoding='utf-8')

    print('wrote schema/entities.json, schema/relations.json')


if __name__ == '__main__':
    main()
