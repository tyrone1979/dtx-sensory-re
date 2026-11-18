/* 程序化低多边形人形（1.71 m）—— 作为尺度参照与"体验者"叙事。
   为什么不用外部人物模型：KayKit 仓库路径已失效（404），人物资源不在 Poly Haven；
   程序化方案零下载、零许可风险、draw call 可控（每人一组 mesh，共享几何）。
   r128 无 CapsuleGeometry → 用 Cylinder + Sphere 近似。 */
const _humanG={};
function humanGeo(){
  if(_humanG.done) return _humanG;
  // 各部件：半径、上下半径、高度、y 中心（相对脚底 0）
  _humanG.leg  = new THREE.CylinderGeometry(0.062,0.052,0.82,7);
  _humanG.torso= new THREE.CylinderGeometry(0.145,0.115,0.56,9);
  _humanG.neck = new THREE.CylinderGeometry(0.048,0.052,0.07,7);
  _humanG.head = new THREE.SphereGeometry(0.105,14,11);
  _humanG.arm  = new THREE.CylinderGeometry(0.048,0.040,0.58,7);
  _humanG.foot = new THREE.BoxGeometry(0.09,0.055,0.20);
  // 各部件中心高度（脚底=0，总高 1.71）
  _humanG.yLeg=0.41; _humanG.yTorso=1.10; _humanG.yNeck=1.415;
  _humanG.yHead=1.545; _humanG.yArm=1.10; _humanG.zFoot=0.045;
  _humanG.done=true;
  return _humanG;
}

/* 柔和的"疗愈场景"配色：低饱和莫兰迪色，避免塑料感抢戏 */
const HUMAN_PAL=[
  { cloth:0x8f9e8b, pant:0x5d6b70, skin:0xd8b89a },  // 苔绿
  { cloth:0xa89a8b, pant:0x6b6257, skin:0xe0c4a6 },  // 陶土
  { cloth:0x7c8894, pant:0x4e5a63, skin:0xd2b294 },  // 黛蓝
  { cloth:0xb0a68f, pant:0x6e6553, skin:0xdcc0a2 },  // 麻灰
];

/* 建一个人。x,z 为站立点，y 由调用方给（通常是该点真实地面）。
   pose: 'stand' | 'sit' | 'walk'，用于轻微调整手臂与躯干，避免"木头人"。 */
function makeHuman(x,y,z,ry,pose,seed){
  const G=humanGeo();
  const pal=HUMAN_PAL[(seed||0)%HUMAN_PAL.length];
  const grp=new THREE.Group();
  const mk=(geo,color,px,py,pz,rx)=>{
    const m=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({color,roughness:0.86,metalness:0.0}));
    m.position.set(px,py,pz); if(rx) m.rotation.x=rx;
    m.castShadow=true; m.receiveShadow=true; grp.add(m); return m;
  };
  const sit = pose==='sit';
  // 腿：坐姿时前伸
  [-0.055,0.055].forEach((ox,i)=>{
    const leg=mk(G.leg,pal.pant,ox,sit?0.44:0.41,0, sit?-0.42:0);
    leg.rotation.x = sit ? -0.45 : (pose==='walk' ? (i?0.22:-0.22) : 0);
  });
  [-0.055,0.055].forEach(ox=>{
    const f=mk(G.foot,pal.pant,ox,sit?0.16:0.028, sit?0.20:G.zFoot, sit?0.5:0);
    if(!sit) f.position.z=G.zFoot;
  });
  const torsoY = sit?0.98:1.10;
  const torso=mk(G.torso,pal.cloth,0,torsoY,0);
  if(sit) torso.rotation.x=-0.10;
  mk(G.neck,pal.skin,0,sit?1.27:1.415,0);
  const head=mk(G.head,pal.skin,0,sit?1.395:1.545,0);
  if(sit) head.position.z=0.02;
  // 手臂：坐姿搭在膝上，站立自然下垂
  [-0.185,0.185].forEach((ox,i)=>{
    const arm=mk(G.arm,pal.cloth,ox,sit?0.92:1.10, sit?0.10:0);
    if(sit) arm.rotation.x=-0.75;
    else if(pose==='walk') arm.rotation.x=(i?0.35:-0.35);
    else arm.rotation.x=0.06*(i?-1:1);
    arm.rotation.z=(i?-1:1)*0.05;
  });
  grp.position.set(x,y,z);
  grp.rotation.y=ry||0;
  return grp;
}
window.__makeHuman=makeHuman;