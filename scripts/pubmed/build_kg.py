# -*- coding: utf-8 -*-
"""Build the digital-healing knowledge graph: nodes, evidence-bearing triples, exports."""
import csv
import json

ROOT = "/Users/leizhao/同步空间/学校/1.科研/数字疗愈"
RAW = json.load(open(f"{ROOT}/tmp/source/pubmed/papers_raw.json", encoding="utf-8"))
BY_PMID = {p["pmid"]: p for p in RAW["papers"]}

# ---------------------------------------------------------------- evidence --
# pmid -> evidence level: A=meta/systematic review, B=RCT/quasi-experiment,
# C=observational, D=narrative review / expert consensus / mechanism study
LEVELS = {
    "6143402": "B", "30309256": "C", "35741607": "C", "35966494": "C",
    "36208780": "B", "34932980": "C", "27525811": "D", "39370878": "D", "28672128": "D",
    "20617017": "B", "33981262": "D", "41425167": "D", "39019965": "A", "40922518": "A",
    "34595510": "A", "26896913": "D", "32992767": "D", "33806377": "C",
    "32601102": "D", "32447382": "D", "34959972": "D", "34032648": "D",
    "36863096": "D", "38722464": "D", "9858756": "D",
    "32663929": "A", "34166869": "A", "31655395": "A", "33454232": "B",
    "39400653": "B", "26211735": "B", "39230757": "B", "20074458": "B",
    "16162447": "D", "25172313": "D", "34323238": "D", "40119884": "A",
    "12919115": "D", "29908578": "D", "37368560": "A",
    "31001682": "A", "28814305": "A", "36864583": "A", "33910423": "A",
    "19568835": "B", "36328581": "D", "32745943": "D",
    "16416750": "B", "30991724": "A", "34646931": "A",
    "24395196": "A", "15256293": "A", "33884400": "D", "36630953": "B",
    "31237569": "B", "31333198": "A", "35993398": "A", "35094802": "A",
    "40371757": "D", "39312259": "A",
    "36698603": "D", "29342844": "B", "34682622": "D",
}
LEVEL_NAME = {"A": "高（系统评价/Meta分析）", "B": "中高（RCT/类实验）",
              "C": "中（观察性研究）", "D": "参考（综述/机制/共识）"}

# pmid -> 论文核心结论（中文，面向康旅设计引用；前端只展示结论，不展示题录）
CONCLUSIONS = {
    # ---- A：系统评价 / Meta ----
    "15256293": "正念减压训练可适度改善临床与非临床人群的多项心理健康指标，是压力管理的有效手段。",
    "24395196": "冥想项目对焦虑、抑郁与疼痛有小到中等程度的改善效果，证据强度中等。",
    "28814305": "森林浴可显著降低收缩压与舒张压，对高血压人群有辅助降压价值。",
    "31655395": "薰衣草干预（吸入/口服）可显著降低不同人群的焦虑水平。",
    "31001682": "森林浴可显著降低唾液皮质醇水平，是缓解生理应激的有效暴露。",
    "30991724": "在绿色自然环境中运动（绿色运动）比室内运动更能提升情绪、自尊与心理健康。",
    "31333198": "数字化心理健康干预对抑郁、焦虑及心理幸福感有中度改善效果，可作为传统服务的补充。",
    "32663929": "芳香疗法（按摩+吸入）可显著缓解急性与慢性场景下的焦虑。",
    "34166869": "芳香疗法（以薰衣草为主）可改善成人与老年人的睡眠质量。",
    "34646931": "自然户外活动对心理健康（焦虑、抑郁、情绪）与生理指标均有小幅正向改善。",
    "34595510": "音乐疗法对自闭症、痴呆、抑郁、失眠等多种状况的症状有改善作用。",
    "33910423": "森林浴对幸福感的多维度（情绪、压力、活力）均有正向效应，证据一致性高。",
    "35993398": "虚拟现实干预可显著减轻儿童诊疗过程中的疼痛与焦虑。",
    "35094802": "虚拟现实暴露疗法可作为疼痛管理的有效非药物辅助手段。",
    "37368560": "按摩疗法可减轻运动后延迟性肌肉酸痛，促进运动表现恢复。",
    "36864583": "森林浴显著提升心理健康水平（焦虑、抑郁、压力全面改善）。",
    "39019965": "音乐疗法可显著减轻乳腺癌患者的焦虑与抑郁。",
    "39312259": "游戏化数字心理健康干预对儿童青少年心理状况有明确改善效果。",
    "40922518": "音乐疗法可显著减轻抑郁症患者的抑郁症状，且多次干预效果更稳定。",
    "40119884": "按摩疗法可缓解类风湿关节炎患者的疼痛与功能障碍，改善生活质量。",
    # ---- B：RCT / 类实验 ----
    "6143402": "术后能看到绿色窗景的患者止痛药用量更少、恢复更快、住院时间更短——窗景是经典的自然疗愈证据。",
    "16416750": "绿色运动比室内运动更能提升情绪与自尊、降低血压，短期暴露即见效。",
    "20074458": "森林环境中的树木芬多精暴露可提升人体自然杀伤细胞活性，并降低应激激素水平。",
    "20617017": "暴露于自然声（比环境噪声）后交感神经激活恢复更快，自然声加速应激恢复。",
    "19568835": "森林浴降低皮质醇、肾上腺素等应激激素，提升副交感神经活性，使机体进入放松状态。",
    "26211735": "芳香疗法按摩可改善患者的睡眠质量并降低焦虑水平。",
    "29342844": "短期休假即可显著降低压力水平、提升幸福感，且效应在回归工作后仍可持续数周。",
    "31237569": "正念冥想手机应用可显著降低高压人群（大学生）的压力水平，数字正念便捷可行。",
    "33454232": "薰衣草与洋甘菊精油吸入可显著减轻抑郁、焦虑与压力。",
    "36208780": "暴露于绿色空间虚拟现实可产生积极的生理与情绪反应（绿视 VR 有放松效应）。",
    "36630953": "每日数分钟的结构化呼吸练习即可改善情绪并降低生理唤起（心率、皮电）。",
    "39400653": "薰衣草芳香疗法可显著减轻剖宫产术后的疼痛与焦虑。",
    "39230757": "芳香疗法联合音乐干预可显著减轻姑息治疗患者的疼痛、焦虑与压力。",
    # ---- C：观察性 ----
    "30309256": "自然主题窗景壁画可改善儿科住院患者的生理指标（心率、血压趋于平稳）。",
    "33806377": "感知声环境质量越好，大学生自评健康水平越高，声环境是校园健康的重要影响因素。",
    "35741607": "公园绿地的感知恢复度（PSD）越高，使用者的注意力恢复越好。",
    "35966494": "自然环境暴露可提升创造力（发散思维任务表现改善）。",
    "34932980": "绿地质量与青少年心理健康正相关，且受人格特质调节（高尽责者获益更明显）。",
    # ---- D：综述 / 机制 ----
    "9858756": "多巴胺主要介导“想要”（奖励学习与动机凸显）而非“喜欢”（快感本身）——鲜味激发食欲的神经机制基础。",
    "12919115": "矿泉浴（浴疗）对湿疹、银屑病等多种皮肤疾病有辅助治疗作用。",
    "16162447": "按摩可降低皮质醇、提升血清素与多巴胺水平，从内分泌角度解释其减压效应。",
    "25172313": "按摩在疼痛、焦虑、抑郁等指标上均有正向效应，是有效的压力管理辅助手段。",
    "27525811": "城市绿色空间通过减压恢复、促进活动、社会凝聚等多条路径促进居民健康。",
    "28672128": "绿地影响健康存在三条主要路径：减压与注意恢复、促进身体活动、增强社会交往。",
    "26896913": "音乐疗法可改善阿尔茨海默病患者的认知、心理与行为症状（尤其激越与抑郁）。",
    "29908578": "浴疗在皮肤科适应证广泛，可改善瘙痒、红斑与皮肤屏障功能。",
    "32992767": "音乐干预可减轻痴呆患者的激越与抑郁情绪，改善生活质量。",
    "32601102": "饮食与营养通过肠-脑轴、慢性炎症、微量营养素等途径影响心理健康。",
    "32745943": "森林浴作为成瘾治疗的辅助干预具有理论基础与初步证据支持。",
    "33981262": "水声、鸟鸣、树叶声等自然声景是恢复性环境的核心要素，可降低应激与注意力疲劳。",
    "32447382": "营养状况与抑郁、焦虑等行为健康问题相关，饮食干预应纳入心理健康管理。",
    "34959972": "膳食模式与焦虑风险相关，富含蔬菜水果的地中海式饮食具保护性。",
    "34032648": "整体饮食质量与心理健康正相关，西式加工饮食模式与抑郁风险升高相关。",
    "34323238": "孕期与产后按摩可缓解腰背疼痛与焦虑，改善睡眠与情绪。",
    "33884400": "正念干预对压力、焦虑、抑郁、慢性疼痛等多类问题具有广泛适用性。",
    "34682622": "健康/养生旅游研究持续增长，康旅体验与旅行者的身心健康改善明确相关。",
    "36328581": "森林环境通过免疫（NK 细胞）、内分泌（皮质醇）、神经（副交感）多条通路促进健康。",
    "36698603": "健康旅游的健康效益涵盖身体、心理、社会多个维度，是整体健康干预场景。",
    "36863096": "气味与味道可触发自传体记忆与怀旧情绪（普鲁斯特效应），是味觉疗愈的情绪通路。",
    "38722464": "岛叶皮层是感觉-情绪-认知的接口，整合味觉与内感受信息并参与情绪加工。",
    "39370878": "室内与室外绿色空间均通过多条机制改善人类健康，室内绿植同样有价值。",
    "41425167": "慢速、低唤醒、节奏稳定的音乐元素（约 60-80 BPM）有助于入睡与睡眠维持。",
    "40371757": "数字心理健康领域证据快速积累，数字化干预有效但实施规范与隐私仍需完善。",
}

# ------------------------------------- colour / shape extension (2026-10-18) --
# 第二轮细化：在视觉通道下新增「颜色」与「形状/空间形态」两个子体系，
# 语料来自 fetch_visual2.py + fetch_visual3.py（472 篇候选 → 门禁筛选 → 38 篇入图）。
EXT = json.load(open(f"{ROOT}/tmp/source/pubmed/kg_ext_visual2.json", encoding="utf-8"))
LEVELS.update(EXT["levels"])
CONCLUSIONS.update(EXT["conclusions"])
print(f"[ext] merged {len(EXT['levels'])} new evidence entries "
      f"({sum(1 for v in EXT['levels'].values() if v == 'A')} A / "
      f"{sum(1 for v in EXT['levels'].values() if v == 'B')} B)")

def ev(pmid):
    p = BY_PMID.get(pmid)
    if not p:
        raise SystemExit(f"missing metadata for {pmid}")
    return {
        "pmid": pmid, "level": LEVELS[pmid], "level_name": LEVEL_NAME[LEVELS[pmid]],
        "title": p["title"], "journal": p["journal"], "year": p["year"],
        "doi": p.get("doi", ""), "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        "types": p["pubtypes"][:4],
        "concl": CONCLUSIONS[pmid],
    }

EVIDENCE = {pmid: ev(pmid) for pmid in LEVELS}
missing = [pmid for pmid, e in EVIDENCE.items() if not e["title"]]

# ------------------------------------------------------------------- nodes --
NODES = []
def node(nid, ntype, name, desc, channel=None, color=None, extra=None):
    n = {"id": nid, "type": ntype, "name": name, "desc": desc}
    if channel:
        n["channel"] = channel
    if color:
        n["color"] = color
    if extra:
        n.update(extra)
    NODES.append(n)
    return n

CH_COLOR = {"visual": "#3BA55D", "auditory": "#3E7CB1", "gustatory": "#E07B39",
            "olfactory": "#8E5EA2", "tactile": "#C99A2E", "perceptual": "#5B5FC7"}

for cid, cname, cdesc in [
    ("ch_visual", "视觉疗愈", "经由色彩、绿量、水体景观、自然窗景与光线调节情绪与认知恢复"),
    ("ch_auditory", "听觉疗愈", "经由自然声景、舒缓音乐与噪声控制调节自主神经与睡眠"),
    ("ch_gustatory", "味觉疗愈", "经由食物风味、饮食质量与味觉-情绪通路影响心理健康"),
    ("ch_olfactory", "嗅觉疗愈", "经由植物芳香分子（精油/芬多精）经嗅通路调节情绪、睡眠与免疫"),
    ("ch_tactile", "触觉疗愈", "经由按压、水温、天然材料接触经皮肤-神经通路降低应激"),
    ("ch_perceptual", "知觉疗愈", "经由正念、呼吸、VR与数字介导的整体感知训练实现疗愈"),
]:
    node(cid, "channel", cname, cdesc, channel=cid, color=CH_COLOR[cid.split("_")[1]])

STIMULI = [
    ("stim_window_view", "自然窗景", "面向自然植被/水体的窗户视野（病房、客房、餐厅）", "visual"),
    ("stim_green_view", "高绿视率景观", "视野中绿色植被覆盖比例高的景观界面", "visual"),
    ("stim_blue_water", "蓝色水体景观", "湖面、溪流、跌水等蓝色空间要素", "visual"),
    ("stim_warm_light", "暖色柔光照明", "低色温、低照度跃变的柔和人工照明", "visual"),
    ("stim_birdsong", "鸟鸣虫唱等自然声", "以生物声为主的自然声景要素", "auditory"),
    ("stim_water_sound", "流水声", "溪涧、跌水、雨声等水声要素", "auditory"),
    ("stim_soft_music", "舒缓音乐", "慢节奏、低响度的干预性音乐（约60-80BPM）", "auditory"),
    ("stim_noise", "交通与设备噪声", "来自交通、设备与人群的负面声刺激", "auditory"),
    ("stim_phytoncide", "树木芬多精", "林木释放的挥发性植物杀菌素（芬多精）", "olfactory"),
    ("stim_lavender", "薰衣草香氛", "薰衣草及洋甘菊等花香类精油扩香", "olfactory"),
    ("stim_citrus", "柑橘类清香", "柑橘属果皮挥发性香气", "olfactory"),
    ("stim_local_food", "山野食材与地方风味", "本地特色食材与烹饪风味", "gustatory"),
    ("stim_umami", "鲜味食物", "富含谷氨酸等鲜味物质的食物", "gustatory"),
    ("stim_nostalgia", "家乡味与怀旧风味", "唤起自传体记忆的童年/家乡味道", "gustatory"),
    ("stim_hot_spring", "温泉矿物水", "含矿物质的温泉水浸浴", "tactile"),
    ("stim_massage", "手法按压", "中等强度的人工按压与推拿接触", "tactile"),
    ("stim_natural_mat", "天然接触材料", "原木、石材、草编、沙土等自然质感材料", "tactile"),
    ("stim_breath", "结构化呼吸训练", "循环叹气、箱式呼吸等节律呼吸练习", "perceptual"),
    ("stim_mindfulness", "正念冥想练习", "对当下体验不加评判的觉察训练", "perceptual"),
    ("stim_vr_nature", "VR自然场景", "虚拟现实中的自然场景暴露", "perceptual"),
    ("stim_app", "疗愈App与数字干预", "移动端正念/睡眠/心理干预程序", "perceptual"),
]
for sid, name, desc, ch in STIMULI:
    node(sid, "stimulus", name, desc, channel=ch, color=CH_COLOR[ch])

MODALITIES = [
    ("mod_view", "自然景观暴露", "以观看自然场景为核心的低强度暴露干预", "visual"),
    ("mod_soundscape", "声景疗愈", "以自然声景设计与噪声控制为核心的干预", "auditory"),
    ("mod_music", "音乐疗法", "由专业治疗师实施的音乐干预", "auditory"),
    ("mod_aroma", "芳香疗法", "精油吸入/扩香为核心的气味干预", "olfactory"),
    ("mod_nutrition", "营养与食疗干预", "以饮食质量与风味设计为核心的身心干预", "gustatory"),
    ("mod_massage", "按摩疗法", "以手法按压为核心的接触干预", "tactile"),
    ("mod_balneo", "温泉浴疗", "以矿物温水浸浴为核心的水疗干预", "tactile"),
    ("mod_forest", "森林浴（Shinrin-yoku）", "沉浸式森林环境的多感官整合疗愈方式", "multi"),
    ("mod_green_ex", "绿色运动", "在自然环境中进行的身体活动", "multi"),
    ("mod_mindfulness", "正念冥想", "结构化的正念觉察训练", "perceptual"),
    ("mod_breath", "呼吸训练", "结构化节律呼吸练习", "perceptual"),
    ("mod_vr", "VR疗愈", "虚拟现实暴露/分心干预", "perceptual"),
    ("mod_digital", "数字疗法", "软件程序驱动的循证心理干预", "perceptual"),
    ("mod_wellness_trip", "康旅度假", "以健康效益为目的的旅行度假产品组合", "multi"),
]
for mid, name, desc, ch in MODALITIES:
    node(mid, "modality", name, desc, channel=(ch if ch != "multi" else None), color="#7A8699" if ch == "multi" else CH_COLOR[ch])

BENEFITS = [
    ("ben_stress_down", "压力与皮质醇下降"), ("ben_bp", "血压下降"),
    ("ben_anxiety", "焦虑减轻"), ("ben_depression", "抑郁改善"),
    ("ben_sleep", "睡眠质量改善"), ("ben_pain", "疼痛缓解"),
    ("ben_immune", "免疫功能提升（NK细胞）"), ("ben_attention", "注意力恢复"),
    ("ben_creativity", "创造力提升"), ("ben_wellbeing", "主观幸福感提升"),
    ("ben_recovery", "术后与疲劳恢复加速"), ("ben_memory", "积极记忆与怀旧唤起"),
    ("ben_arousal", "生理唤醒降低（皮电/心率）"), ("ben_skin", "皮肤炎症改善"),
    ("ben_mood", "即时情绪提升"), ("ben_addiction", "成瘾行为辅助改善"),
]
for bid, name in BENEFITS:
    node(bid, "benefit", name, "", color="#C0532B")

DESIGNS = [
    ("des_room", "客房自然窗景与暖光系统", "每间客房对景自然植被/水体，低位暖光照明，绿色软装", "visual"),
    ("des_trail", "森林步道与林间休息点", "康养环线步道，沿线设歇脚平台与观景点", "multi"),
    ("des_lake", "湖景水系与跌水", "中心湖面、溪流跌水与亲水栈道", "multi"),
    ("des_sound", "声景观分区", "静谧区（虫鸣鸟唱）与活化区（舒缓音乐）分区管控", "auditory"),
    ("des_aroma_garden", "香氛花园与扩香系统", "芳香植物花园+公共空间定时扩香", "olfactory"),
    ("des_spring", "温泉汤池区", "矿化物温泉泡池、按摩浴与静卧区", "tactile"),
    ("des_restaurant", "疗愈餐厅（地方风味食疗）", "本地食材、鲜味与怀旧菜单设计", "gustatory"),
    ("des_meditation", "冥想平台与呼吸花园", "半山冥想平台，配套引导式呼吸课程", "perceptual"),
    ("des_digital", "数字疗愈中心", "VR自然暴露舱、正念App课程、睡眠声景室", "perceptual"),
    ("des_barefoot", "赤足触觉步道", "木/石/沙/草多材质赤足感知路径", "tactile"),
]
for did, name, desc, ch in DESIGNS:
    node(did, "design", name, desc, channel=(ch if ch != "multi" else None), color="#B03A48" if ch != "multi" else "#8A4B58")

# ---- extension: colour + shape/spatial-form nodes (visual channel) ----
EXT_SUBCH = {"color": "#2E8B62", "shape": "#7A5C9E"}
for sid, name, desc, ch in EXT["stimuli"]:
    sub = "color" if any(k in sid for k in ("color", "hue", "sat", "lightness", "low_contrast", "colorful")) else "shape"
    node(sid, "stimulus", name, desc, channel=ch, color=EXT_SUBCH[sub], extra={"subpath": sub})
for mid, name, desc, ch in EXT["modalities"]:
    sub = "color" if "color" in mid else "shape"
    node(mid, "modality", name, desc, channel=ch, color=EXT_SUBCH[sub], extra={"subpath": sub})
for did, name, desc, ch in EXT["designs"]:
    sub = "color" if "palette" in did else "shape"
    node(did, "design", name, desc, channel=ch, color="#B03A48", extra={"subpath": sub})
for bid, name in EXT["benefits"]:
    node(bid, "benefit", name, "", color="#C0532B")

# ------------------------------------------------------------------- edges --
EDGES = []
def edge(eid, src, rel, dst, pmids, note="", effect="", population="", n=""):
    evs = [EVIDENCE[p] for p in pmids]
    top = min(evs, key=lambda e: e["level"]) if evs else None
    EDGES.append({
        "id": eid, "source": src, "target": dst, "relation": rel,
        "note": note, "effect": effect, "population": population, "n": n,
        "level": top["level"] if top else "", "level_name": top["level_name"] if top else "",
        "evidence": [e["pmid"] for e in evs],
    })

def E(src, rel, dst, pmids, **kw):
    edge(f"e{len(EDGES)+1:03d}", src, rel, dst, pmids, **kw)

# 刺激元素 -> 感官通道
for sid, _, _, ch in STIMULI:
    if ch != "multi":
        E(sid, "作用于", f"ch_{ch}", [], note=f"{dict((s[0], s[1]) for s in STIMULI)[sid]}经{ch}通道输入")
# 疗愈方式 -> 感官通道
for mid, _, _, ch in MODALITIES:
    if ch != "multi":
        E(mid, "主要经由", f"ch_{ch}", [])
# 疗愈方式包含刺激元素
E("mod_forest", "包含", "stim_green_view", ["36328581"], note="森林环境多维属性：静谧氛围、优美景色、宜人气候、愉悦香气、清洁空气")
E("mod_forest", "包含", "stim_phytoncide", ["20074458"])
E("mod_forest", "包含", "stim_birdsong", ["33981262"])
E("mod_forest", "包含", "stim_natural_mat", ["36328581"])
E("mod_view", "包含", "stim_green_view", ["35741607"])
E("mod_view", "包含", "stim_window_view", ["6143402"])
E("mod_view", "包含", "stim_blue_water", ["39370878"])
E("mod_soundscape", "包含", "stim_birdsong", ["20617017"])
E("mod_soundscape", "包含", "stim_water_sound", ["33981262"])
E("mod_music", "包含", "stim_soft_music", ["41425167"])
E("mod_aroma", "包含", "stim_lavender", ["33454232"])
E("mod_aroma", "包含", "stim_citrus", ["39230757"])
E("mod_nutrition", "包含", "stim_local_food", ["32601102"])
E("mod_nutrition", "包含", "stim_umami", ["9858756"])
E("mod_nutrition", "包含", "stim_nostalgia", ["36863096"])
E("mod_massage", "包含", "stim_massage", ["16162447"])
E("mod_balneo", "包含", "stim_hot_spring", ["12919115"])
E("mod_mindfulness", "包含", "stim_mindfulness", ["24395196"])
E("mod_breath", "包含", "stim_breath", ["36630953"])
E("mod_vr", "包含", "stim_vr_nature", ["36208780"])
E("mod_digital", "包含", "stim_app", ["31237569"])
E("mod_green_ex", "包含", "stim_green_view", ["16416750"])
E("mod_wellness_trip", "组合", "mod_forest", ["36698603"])
E("mod_wellness_trip", "组合", "mod_aroma", ["36698603"])
E("mod_wellness_trip", "组合", "mod_balneo", ["36698603"])

# 视觉疗愈
E("mod_view", "加速", "ben_recovery", ["6143402"], effect="自然窗景组术后住院时间更短、镇痛药用量更少、护士负面评价更少",
  population="胆囊切除术后患者", n="23 vs 23", note="Ulrich经典研究：窗景作为'积极分心'")
E("mod_view", "缓解", "ben_pain", ["6143402"], effect="强效镇痛药使用更少")
E("stim_window_view", "降低", "ben_arousal", ["30309256"], effect="自然主题窗户壁画降低儿科患者心率与血压",
  population="住院儿童", n="生理指标实测")
E("mod_view", "促进", "ben_attention", ["35741607"], effect="公园绿地感知自然度与注意恢复正相关",
  population="成都市四公园游客", n="现场问卷")
E("mod_view", "提升", "ben_creativity", ["35966494"], effect="高感知自然度环境提升创造力表现",
  population="高校被试", n="三组自然度对照")
E("mod_view", "改善", "ben_stress_down", ["36208780"], effect="VR绿地暴露改善孕妇情绪与生理应激恢复",
  population="孕期女性", n="RCT")
E("stim_green_view", "改善", "ben_wellbeing", ["34932980"], effect="感知绿地质量与青少年心理健康正相关",
  population="16-17岁青少年", n="2946")
E("mod_view", "改善", "ben_bp", ["27525811", "39370878"], effect="多项综述支持绿地暴露与血压改善相关")
E("mod_view", "改善", "ben_wellbeing", ["28672128"], effect="绿地-健康多路径：恢复、活动、社交、空气", note="专家研讨会共识")

# 听觉疗愈
E("mod_soundscape", "改善", "ben_stress_down", ["20617017"], effect="自然声暴露后皮肤电导恢复显著快于噪声",
  population="健康成人", n="40", note="Alvarsson 2010：应激后听觉恢复实验")
E("mod_soundscape", "增强", "ben_wellbeing", ["33981262"], effect="鸟鸣/风/水声提升自然环境积极感知与恢复性评价")
E("stim_noise", "损害", "ben_sleep", ["33806377"], effect="室内不良声环境与自评健康下降相关", population="居家大学生")
E("mod_music", "改善", "ben_anxiety", ["39019965"], effect="音乐疗法显著降低乳腺癌患者焦虑", note="2024 Meta分析")
E("mod_music", "改善", "ben_depression", ["40922518"], effect="音乐疗法对抑郁症状有效（RCT Meta）", note="BJPsych Open 2025")
E("mod_music", "改善", "ben_sleep", ["41425167", "34595510"], effect="慢节奏低响度音乐元素改善入睡与睡眠质量")
E("mod_music", "改善", "ben_mood", ["26896913", "32992767"], effect="音乐疗法改善痴呆患者认知、心理与行为症状", population="痴呆患者")

# 味觉疗愈
E("mod_nutrition", "改善", "ben_depression", ["32601102", "32447382"], effect="饮食质量与抑郁风险负相关，改善饮食或可保护心理健康")
E("mod_nutrition", "影响", "ben_anxiety", ["34959972", "34032648"], effect="营养状况与焦虑症状发生发展相关")
E("mod_nutrition", "机制", "ben_depression", ["34032648"], effect="肠-脑轴等机制通路连接饮食与心理健康")
E("stim_nostalgia", "触发", "ben_memory", ["36863096"], effect="味嗅觉唤起高度自我相关的积极自传体记忆（普鲁斯特效应）")
E("stim_umami", "激活", "ben_mood", ["9858756", "38722464"], effect="美味经眶额叶/岛叶奖赏环路产生即时愉悦")

# 嗅觉疗愈
E("mod_aroma", "减轻", "ben_anxiety", ["32663929"], effect="芳香疗法显著降低患者焦虑（25篇/32试验Meta）", note="J Affect Disord 2020")
E("mod_aroma", "改善", "ben_sleep", ["34166869"], effect="芳香疗法改善成人及老年睡眠质量", note="Meta分析")
E("stim_lavender", "减轻", "ben_anxiety", ["31655395"], effect="薰衣草各剂型均显示抗焦虑效应", note="Phytomedicine Meta")
E("stim_lavender", "减轻", "ben_anxiety", ["33454232"], effect="薰衣草/洋甘菊吸入降低社区老人抑郁焦虑压力",
  population="社区居家老人", n="183", note="三臂RCT")
E("stim_lavender", "改善", "ben_depression", ["33454232"])
E("stim_lavender", "改善", "ben_stress_down", ["33454232"])
E("stim_lavender", "缓解", "ben_pain", ["39400653"], effect="薰衣草芳疗降低剖宫产术后疼痛与焦虑", population="剖宫产产妇", n="RCT")
E("stim_lavender", "改善", "ben_sleep", ["26211735"], effect="薰衣草精油改善冠心病ICU患者睡眠质量与焦虑", population="冠心病ICU患者", n="60", note="RCT")
E("mod_aroma", "缓解", "ben_pain", ["39230757"], effect="音乐+芳香联合降低姑息患者疼痛焦虑压力", population="姑息治疗患者", n="88", note="四臂RCT")
E("stim_phytoncide", "提升", "ben_immune", ["20074458"], effect="树木精油（芬多精）提升NK细胞活性与细胞内抗癌蛋白",
  population="健康男性", n="12", note="森林免疫机制关键实验")

# 触觉疗愈
E("stim_massage", "降低", "ben_stress_down", ["16162447"], effect="按摩后皮质醇下降", note="Field 2005 生化证据综述")
E("stim_massage", "提升", "ben_mood", ["16162447"], effect="按摩后5-羟色胺与多巴胺上升")
E("mod_massage", "提升", "ben_immune", ["25172313"], effect="按摩提升NK细胞数量与活性")
E("mod_massage", "缓解", "ben_pain", ["25172313", "40119884"], effect="按摩缓解纤维肌痛、类风湿等疼痛综合征")
E("mod_massage", "改善", "ben_anxiety", ["34323238"], effect="按摩缓解孕期焦虑与抑郁", population="孕产妇")
E("mod_balneo", "改善", "ben_skin", ["29908578", "12919115"], effect="温泉水浸浴改善银屑病与特应性皮炎皮肤炎症", note="死海/蓝湖等疗愈地证据")
E("stim_hot_spring", "改善", "ben_skin", ["12919115"])

# 森林浴（跨通道）
E("mod_forest", "降低", "ben_stress_down", ["31001682"], effect="森林浴显著降低唾液/血清皮质醇", note="Cortisol Meta 2019")
E("mod_forest", "降低", "ben_bp", ["28814305"], effect="森林浴具有降压效应", note="BP Meta 2017")
E("mod_forest", "提升", "ben_wellbeing", ["36864583", "33910423"], effect="森林浴提升心理幸福感", note="Meta+伞形综述")
E("mod_forest", "提升", "ben_immune", ["19568835", "20074458"], effect="森林环境提升NK细胞活性且效果持续7天以上", note="日本24片森林场实验")
E("mod_forest", "辅助改善", "ben_addiction", ["32745943"], effect="作为成瘾治疗的辅助手段（证据有限）", note="述评，低强度证据")
E("mod_forest", "协同", "ch_visual", ["36328581"], note="森林浴同步调动视/嗅/听/触多通道")
E("mod_forest", "协同", "ch_olfactory", ["36328581"])
E("mod_forest", "协同", "ch_auditory", ["36328581"])
E("mod_forest", "协同", "ch_tactile", ["36328581"])

# 绿色运动 / 自然干预
E("mod_green_ex", "提升", "ben_wellbeing", ["16416750", "30991724"], effect="绿色运动较室内运动有协同增效", note="Benton & Pretty 经典 + 系统综述")
E("mod_forest", "改善", "ben_mood", ["34646931"], effect="自然干预改善社区成人心理健康", note="Nature-based interventions Meta")

# 知觉/数字疗愈
E("mod_mindfulness", "减轻", "ben_anxiety", ["24395196"], effect="冥想程序改善焦虑、抑郁、压力", note="JAMA Intern Med 2014 Meta")
E("mod_mindfulness", "改善", "ben_depression", ["24395196", "15256293"], effect="MBSR对抑郁症状有效")
E("mod_mindfulness", "改善", "ben_stress_down", ["15256293"], effect="MBSR改善多种人群健康结局", note="MBSR Meta 2004")
E("stim_breath", "提升", "ben_mood", ["36630953"], effect="每日5分钟呼吸练习改善情绪", population="成人", n="RCT N≈1000", note="Cell Rep Med 2023")
E("stim_breath", "降低", "ben_arousal", ["36630953"], effect="循环叹气降低生理唤醒")
E("stim_app", "减轻", "ben_stress_down", ["31237569"], effect="Calm App 8周干预降低高应激大学生压力", population="大学生", n="RCT")
E("mod_digital", "改善", "ben_anxiety", ["31333198"], effect="数字心理健康干预改善大学生抑郁焦虑", note="JMIR系统综述")
E("mod_digital", "改善", "ben_depression", ["31333198"])
E("stim_vr_nature", "缓解", "ben_pain", ["35993398", "35094802"], effect="VR显著降低医疗操作相关疼痛", note="两项Meta分析")
E("stim_vr_nature", "减轻", "ben_anxiety", ["35993398"], effect="VR降低儿科患者焦虑与恐惧", note="Pediatric Meta 2022")
E("mod_digital", "改善", "ben_wellbeing", ["39312259"], effect="游戏化数字干预改善儿童青少年焦虑抑郁ADHD", note="JAMA Pediatr 2024 Meta")
E("mod_digital", "证据", "ben_wellbeing", ["40371757"], effect="数字疗法需共设计与严格评估，避免过度宣称", note="World Psychiatry 2025 警示")

# 康旅度假
E("mod_wellness_trip", "改善", "ben_stress_down", ["29342844"], effect="4晚短假显著降低压力水平", population="中高层管理者", n="RCT")
E("mod_wellness_trip", "提升", "ben_wellbeing", ["29342844", "36698603"], effect="短假提升幸福感，康旅效益涵盖体能/心理/生活质量/环境四维", note="康旅效益维度综述")

# 设计应用层：设计 -> 采用 -> 刺激/方式；设计 -> 依据 -> 论文
DESIGN_ADOPT = [
    ("des_room", [("stim_window_view", "对视自然植被/水体的客房窗景"), ("stim_warm_light", "低位暖色柔光"), ("mod_view", "自然景观暴露")],
     ["6143402", "30309256"], "术后恢复与儿童生理指标证据支持'每间客房有自然窗景'"),
    ("des_trail", [("mod_forest", "森林浴环线"), ("stim_green_view", "高绿视率林间视野")],
     ["31001682", "28814305", "36864583", "19568835"], "森林浴降压、降皮质醇、升免疫与幸福感的Meta证据"),
    ("des_lake", [("stim_blue_water", "蓝色水体景观"), ("stim_water_sound", "跌水与溪流声"), ("mod_soundscape", "水声声景")],
     ["20617017", "33981262"], "自然声与水声的应激恢复证据（蓝色空间直接证据有限，经声景通道间接支持）"),
    ("des_sound", [("mod_soundscape", "声景分区管控"), ("stim_birdsong", "静谧区虫鸣鸟唱"), ("stim_soft_music", "活化区舒缓音乐"), ("stim_noise", "交通噪声管控（负向规避）")],
     ["20617017", "39019965", "33806377"], "自然声恢复+音乐疗法循证+噪声危害规避"),
    ("des_aroma_garden", [("stim_lavender", "薰衣草主题香氛"), ("stim_citrus", "柑橘类清香"), ("stim_phytoncide", "林木芬多精")],
     ["32663929", "31655395", "33454232", "20074458"], "芳香疗法抗焦虑/改善睡眠的Meta证据+芬多精免疫证据"),
    ("des_spring", [("stim_hot_spring", "矿化物温泉泡池"), ("stim_massage", "按摩浴/手法按摩")],
     ["29908578", "12919115", "16162447", "25172313"], "温泉皮肤获益+按摩降皮质醇证据"),
    ("des_restaurant", [("stim_local_food", "本地风味食材"), ("stim_umami", "鲜味设计"), ("stim_nostalgia", "怀旧风味菜单")],
     ["32601102", "32447382", "36863096"], "饮食-抑郁/焦虑证据+普鲁斯特效应"),
    ("des_meditation", [("stim_mindfulness", "正念冥想课程"), ("stim_breath", "引导式呼吸训练")],
     ["24395196", "36630953"], "正念Meta证据+呼吸训练RCT"),
    ("des_digital", [("stim_vr_nature", "VR自然暴露舱"), ("stim_app", "正念/睡眠App课程"), ("mod_digital", "数字疗法中心")],
     ["31333198", "31237569", "35993398"], "数字干预系统综述+App RCT+VR Meta；注意40371757的实施质量警示"),
    ("des_barefoot", [("stim_natural_mat", "木/石/沙/草多材质"), ("stim_massage", "赤足按压接触")],
     ["25172313", "30991724"], "中等压力接触获益+绿色运动证据"),
]
for did, adopts, pmids, rationale in DESIGN_ADOPT:
    for tid, note in adopts:
        E(did, "采用", tid, [], note=note)
    E(did, "循证依据", "ben_wellbeing", pmids, note=rationale)

# ---- extension edges: colour + shape/spatial-form ----
EMETA = {tuple(k.split("|")): v for k, v in EXT["edge_meta"].items()}
for src, rel, dst, pmids, *rest in EXT["edges"]:
    effect, note, pop, n = (rest + ["", "", "", ""])[:4] if rest else ("", "", "", "")
    m = EMETA.get((src, rel, dst))
    if m:
        effect = effect or m[0]
        note = note or m[1]
        pop = pop or m[2]
        n = n or m[3]
    E(src, rel, dst, pmids, effect=effect, note=note, population=pop, n=n)

# 扩展子体系之间的桥接：形状与颜色共同作用于视觉通道
E("mod_shape_env", "协同", "mod_color_env", ["41929880", "39806242"],
  effect="形态（围合/视野/复杂度）与配色协同时恢复效应最强，单一维度不足",
  note="亲生物设计综述 × 颜色-情绪系统评价", population="患者/成人", n="")
E("des_palette", "协同", "des_geometry", ["41929880"],
  effect="园区配色体系须与空间形态同步规划", note="亲生物设计强调多要素整合", n="")
E("des_viewport", "协同", "des_geometry", ["35996349"],
  effect="窗洞视野与围合布局共同决定庇护-展望体验", note="临床亲生物参数综述", n="")

# ------------------------------------------------------------------ export --
META = {
    "name": "数字疗愈知识图谱",
    "version": "1.1",
    "built": "2026-10-18",
    "sources": "PubMed (NCBI E-utilities)",
    "paper_count": len(EVIDENCE),
    "triple_count": len(EDGES),
    "evidence_levels": LEVEL_NAME,
    "channel_colors": CH_COLOR,
}

GRAPH = {"meta": META, "nodes": NODES, "edges": EDGES, "evidence": EVIDENCE}

import os
os.makedirs(f"{ROOT}/output/data", exist_ok=True)
with open(f"{ROOT}/output/data/knowledge_graph.json", "w", encoding="utf-8") as f:
    json.dump(GRAPH, f, ensure_ascii=False, indent=1)

# CSV: one row per triple
with open(f"{ROOT}/output/data/triples.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["三元组ID", "主体", "关系", "客体", "主体类型", "客体类型", "关联感官通道",
                "证据等级", "效应描述", "人群", "样本量", "PMID", "证据论文", "期刊", "年份", "DOI", "备注"])
    nmap = {n["id"]: n for n in NODES}
    for e in EDGES:
        for pid in e["evidence"]:
            p = EVIDENCE[pid]
            s, t = nmap[e["source"]], nmap[e["target"]]
            w.writerow([e["id"], s["name"], e["relation"], t["name"], s["type"], t["type"],
                        s.get("channel", ""), p["level"], e["effect"], e["population"], e["n"],
                        pid, p["title"], p["journal"], p["year"], p["doi"], e["note"]])
        if not e["evidence"]:
            s, t = nmap[e["source"]], nmap[e["target"]]
            w.writerow([e["id"], s["name"], e["relation"], t["name"], s["type"], t["type"],
                        s.get("channel", ""), "", e["effect"], e["population"], e["n"],
                        "", "", "", "", "", e["note"]])

# Cypher for Neo4j
with open(f"{ROOT}/output/data/neo4j_import.cypher", "w", encoding="utf-8") as f:
    f.write("// 数字疗愈知识图谱 - Neo4j 导入脚本\n")
    f.write("CREATE INDEX FOR (n:Node) ON (n.id);\n\n")
    for n in NODES:
        props = {"id": n["id"], "name": n["name"], "desc": n["desc"], "type": n["type"]}
        if n.get("channel"):
            props["channel"] = n["channel"]
        plist = ", ".join(f'{k}: "{str(v).replace(chr(34), chr(39))}"' for k, v in props.items() if v)
        f.write(f'CREATE (:{n["type"]} {{{plist}}});\n')
    f.write("\n")
    for e in EDGES:
        props = {"id": e["id"], "level": e["level"], "note": e["note"], "effect": e["effect"]}
        plist = ", ".join(f'{k}: "{str(v).replace(chr(34), chr(39))}"' for k, v in props.items() if v)
        rel = e["relation"].replace(" ", "_")
        f.write(f'MATCH (a:Node {{id: "{e["source"]}"}}), (b:Node {{id: "{e["target"]}"}}) '
                f'CREATE (a)-[:{rel} {{{plist}}}]->(b);\n')
    for pid, p in EVIDENCE.items():
        plist = (f'id: "ev_{pid}", name: "{p["title"][:80]}", pmid: "{pid}", level: "{p["level"]}", '
                 f'journal: "{p["journal"]}", year: "{p["year"]}", doi: "{p["doi"]}", url: "{p["url"]}"')
        f.write(f'CREATE (:Evidence {{{plist}}});\n')
    for e in EDGES:
        for pid in e["evidence"]:
            f.write(f'MATCH ()-[r:Node_REL {{id: "{e["id"]}"}}]-(), (ev:Evidence {{id: "ev_{pid}"}}) '
                    f'CREATE (r)-[:SUPPORTED_BY]->(ev);\n')

# JS data for HTML embedding
with open(f"{ROOT}/output/data/kg_data.js", "w", encoding="utf-8") as f:
    f.write("window.KG_DATA = " + json.dumps(GRAPH, ensure_ascii=False) + ";\n")

print("nodes:", len(NODES), "edges:", len(EDGES), "papers:", len(EVIDENCE))
print("missing meta:", missing)
from collections import Counter
print("edge relations:", Counter(e["relation"] for e in EDGES).most_common())
print("evidence per edge (with cites):", sum(1 for e in EDGES if e["evidence"]))
