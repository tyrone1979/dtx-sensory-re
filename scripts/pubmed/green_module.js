/* ---------- 园区绿化 ----------
   7 个 Poly Haven CC0 资产（1k 档，共 ~18 MB）：
     moss_01 / grass_medium_01 / fern_02 / boulder_01
     tree_stump_01 / rock_moss_set_01 / planter_box_02

   摆放原则（循证相关，均为 A/B 级证据支持的自然暴露与绿视）：
   1. **乔木遮阴优先**：tree_stump / boulder 沿墙根与院角，围合"可视绿量"
   2. **草丛成片而非散点**：grass 成簇布置形成"低层视界"，避免孤立感
   3. **盆栽作为"可移动绿源"**：入口/转折处放 planter_box，
      环境心理学中"可控性"与"私密度"是核心变量，可移动盆栽同时满足
   4. **避开真实可走面**：不占用 scan_layers 实测的 G 区域中心，
      沿边缘（距可走区 ≥0.6 m）布置，不阻断动线

   draw call 控制：草/苔用 InstancedMesh（一片一次 draw），
   单株石/树桩用普通 Mesh。目标总 draw call 增量 < 40。 */

const GREEN=[
  /* id, x, z, ry, scale, repeat(草丛簇数) */
  { id:'boulder_01',        x:-6.20, z: 4.20, ry:0.4, sc:1.1 },
  { id:'boulder_01',        x: 7.30, z: 4.60, ry:1.9, sc:0.8 },
  { id:'rock_moss_set_01',  x:-6.60, z: 5.30, ry:0.2, sc:0.9 },
  { id:'tree_stump_01',     x:-6.00, z: 5.60, ry:1.2, sc:1.0 },
  { id:'tree_stump_01',     x: 6.80, z:-4.30, ry:2.4, sc:0.85 },
  { id:'rock_moss_set_01',  x: 6.40, z:-3.90, ry:1.5, sc:0.75 },
  { id:'planter_box_02',    x: 7.20, z: 0.20, ry:0.1, sc:1.0 },
  { id:'planter_box_02',    x:-6.90, z:-0.40, ry:2.9, sc:1.0 },
  /* 草丛：成片，沿墙根与院角 */
  { id:'grass_medium_01',   x:-5.60, z: 5.40, ry:0, sc:1.0, rep:5 },
  { id:'grass_medium_01',   x: 6.60, z: 5.20, ry:1.1, sc:1.0, rep:5 },
  { id:'grass_medium_01',   x:-5.20, z: 6.20, ry:2.2, sc:0.9, rep:4 },
  { id:'grass_medium_01',   x: 7.10, z: 3.20, ry:0.7, sc:0.95, rep:4 },
  { id:'grass_medium_01',   x:-6.30, z: 2.60, ry:1.6, sc:0.9, rep:4 },
  { id:'grass_medium_01',   x: 6.80, z: 2.00, ry:0.3, sc:0.9, rep:4 },
  { id:'grass_medium_01',   x:-5.80, z: 3.60, ry:2.7, sc:1.0, rep:5 },
  /* 苔与蕨：贴墙根与石边，低层视界 */
  { id:'moss_01',           x:-5.40, z: 4.60, ry:0.5, sc:1.0, rep:3 },
  { id:'moss_01',           x: 7.00, z:-2.60, ry:1.8, sc:0.9, rep:3 },
  { id:'moss_01',           x:-6.70, z: 1.20, ry:2.5, sc:0.85, rep:3 },
  { id:'fern_02',           x:-5.70, z: 4.00, ry:1.2, sc:1.0, rep:3 },
  { id:'fern_02',           x: 7.20, z: 1.40, ry:2.8, sc:0.95, rep:3 },
  { id:'fern_02',           x:-6.40, z:-1.20, ry:0.6, sc:0.9, rep:3 },
];

/* 草丛簇的确定性伪随机（保证每次刷新位置一致，便于复现截图） */
function seeded(n){ const s=Math.sin(n*127.1+311.7)*43758.5453; return s-Math.floor(s); }
window.__GREEN=GREEN;
window.__seeded=seeded;