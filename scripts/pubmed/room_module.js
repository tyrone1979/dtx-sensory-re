/* ---------- 室内体块补建 ----------
   为什么需要：Sketchfab 四合院是**纯外壳模型**（作者原话"要是再有内饰就更好了"），
   射线全境扫描只检出唯一半室内区（正房檐廊 4×3 m）。若不补建，
   "客房松间""茶室""瑜伽禅修"三个循证空间只能靠家具围合表达，
   与"睡眠环境""私密性""安静"这类证据主张相矛盾——环境心理学里
   **可控性/私密性**本身就是干预变量，露天布置等于把这半个变量抹掉。

   做法：中式木构小屋（体块 + 双坡瓦顶 + 木格窗 + 格栅门），
   风格与本体一致（青砖/朱木/灰瓦），每间约 3.2×3.6 m，
   净空 2.5 m，置于实测有地面且净空足够的院落位置。
   坐标由 scan_layers.cjs 实测确定，不是估的。 */

/* 单间参数：cx,cz 中心；w,d 宽深；ry 朝向
   坐标来自 probe_ground.cjs 实测（1m 网格，逐格单射线，247 点）：
     真实开阔地面 y=0.49 的连续区域：
       东区  X +3..+7 / Z -4..+6   （5×11 m，最大连续面）
       西区  X -7..-6   / Z -4..+6   （2×11 m 窄带）
       中区  X -2..-1   / Z -1..+3   （2×5 m）
     Y=1.08 的条带是**花台/台基**（此前粗扫误判为树冠），不可建；
     Y=0.92~0.94 是正房台基（X -1..+2 / Z -4..-2）。
   三间房分别落在东、西、中三块开阔面，互不重叠，且都避开台基。 */
const ROOMS=[
  // 东区：客房松间 3.2×3.6，占 X 4.4..7.6 / Z -3.4..0.2 —— 全 0.49 开阔面
  { id:'guest', cx: 6.0, cz:-1.6, w:3.2, d:3.6, ry:0, name:'客房松间' },
  // 西区：茶室 2.2×3.0，占 X -7.4..-5.2 / Z -3.6..-0.6
  // （西带宽仅 2 m，故取 2.2 略探入花台，落地时以实测地面为准）
  { id:'tea',  cx:-6.2, cz:-2.1, w:2.2, d:3.0, ry:0, name:'西北茶室' },
  // 中区：禅修静室 2.0×2.4，占 X -2.6..-0.6 / Z -0.4..2.0
  { id:'yoga', cx:-1.6, cz: 0.8, w:2.0, d:2.4, ry:0, name:'禅修静室' },
];

const MAT={
  wall : new THREE.MeshStandardMaterial({color:0xe8e2d6,roughness:0.94}),  // 白粉墙
  wall2: new THREE.MeshStandardMaterial({color:0xd8d0c0,roughness:0.94}),
  wood : new THREE.MeshStandardMaterial({color:0x6b4a34,roughness:0.72}),
  wood2: new THREE.MeshStandardMaterial({color:0x4e3526,roughness:0.75}),
  tile : new THREE.MeshStandardMaterial({color:0x4a4f56,roughness:0.88}),
  tile2: new THREE.MeshStandardMaterial({color:0x3c4147,roughness:0.88}),
  paper: new THREE.MeshStandardMaterial({color:0xf2ece0,roughness:0.95,
          transparent:true,opacity:0.72}),
  frame: new THREE.MeshStandardMaterial({color:0x5c3f2c,roughness:0.7}),
  floor: new THREE.MeshStandardMaterial({color:0xb9ac93,roughness:0.9}),
};

/* 中式双坡瓦顶：两片斜面 + 两道正脊 + 檐口微翘 */
function chineseRoof(w,d,h,over){
  const g=new THREE.Group();
  const W=w+over*2, D=d+over*2;
  const slope=Math.atan2(h,(D/2));
  const len=Math.hypot(D/2,h);
  [-1,1].forEach(s=>{
    const p=new THREE.Mesh(new THREE.BoxGeometry(W,0.10,len),s<0?MAT.tile:MAT.tile2);
    p.rotation.x=s*slope;
    p.position.set(0,h/2,s*(D/4));
    p.castShadow=true; p.receiveShadow=true;
    g.add(p);
  });
  // 正脊
  const ridge=new THREE.Mesh(new THREE.BoxGeometry(W+0.10,0.16,0.24),MAT.tile2);
  ridge.position.y=h; ridge.castShadow=true; g.add(ridge);
  // 脊端翘角（简化为两枚小三角块）
  [-1,1].forEach(s=>{
    const e=new THREE.Mesh(new THREE.BoxGeometry(0.5,0.12,0.5),MAT.tile2);
    e.position.set(s*(W/2+0.12),h+0.06,0); e.castShadow=true; g.add(e);
  });
  return g;
}

/* 木格窗：格栅条 + 半透纸（程序化，不用贴图） */
function latticeWindow(w,h){
  const g=new THREE.Group();
  const frame=new THREE.Mesh(new THREE.BoxGeometry(w+0.10,h+0.10,0.08),MAT.frame);
  g.add(frame);
  const pane=new THREE.Mesh(new THREE.BoxGeometry(w,h,0.03),MAT.paper);
  pane.position.z=0.04; g.add(pane);
  const n=Math.max(2,Math.round(w/0.22));
  for(let i=1;i<n;i++){
    const b=new THREE.Mesh(new THREE.BoxGeometry(0.032,h,0.05),MAT.frame);
    b.position.set(-w/2+w*i/n,0,0.06); g.add(b);
  }
  for(let j=1;j<3;j++){
    const b=new THREE.Mesh(new THREE.BoxGeometry(w,0.028,0.05),MAT.frame);
    b.position.set(0,-h/2+h*j/3,0.06); g.add(b);
  }
  return g;
}

/* 格栅门（半开，用于视觉通透但仍界定私密） */
function latticeDoor(w,h){
  const g=new THREE.Group();
  const fr=new THREE.Mesh(new THREE.BoxGeometry(w+0.08,h+0.06,0.07),MAT.frame);
  fr.position.y=h/2; g.add(fr);
  const n=Math.max(3,Math.round(w/0.18));
  for(let i=0;i<n;i++){
    const b=new THREE.Mesh(new THREE.BoxGeometry(0.045,h-0.1,0.04),MAT.wood2);
    b.position.set(-w/2+w*(i+0.5)/n,h/2,0.05); g.add(b);
  }
  const rail=new THREE.Mesh(new THREE.BoxGeometry(w,0.07,0.055),MAT.wood2);
  rail.position.set(0,h*0.68,0.05); g.add(rail);
  return g;
}

/* 建一间房。g0 = 该点真实地面高度（调用方用 walkFloor 求得后传入） */
function buildRoom(r,g0){
  const grp=new THREE.Group();
  const {w,d}=r, H=2.50, T=0.14;      // 净空 2.5 m，墙厚 0.14
  const wallY=g0+H/2;

  /* 台基：比地面高 0.30 m 三级台阶（循证：抬高可增加"领域感"） */
  const base=new THREE.Mesh(new THREE.BoxGeometry(w+0.7,0.30,d+0.7),MAT.wall2);
  base.position.set(0,g0+0.15,0); base.receiveShadow=true; base.castShadow=true;
  grp.add(base);
  const floorY=g0+0.30;
  const fl=new THREE.Mesh(new THREE.BoxGeometry(w,0.06,d),MAT.floor);
  fl.position.set(0,floorY-0.03,0); fl.receiveShadow=true; grp.add(fl);

  /* 四面墙：南面开门洞，北面开窗，东西实墙 */
  const seg=(len,mat)=>new THREE.Mesh(new THREE.BoxGeometry(len,H,T),mat);
  const put=(m,x,z)=>{ m.position.set(x,floorY+H/2,z); m.castShadow=true; m.receiveShadow=true; grp.add(m); };

  // 北墙（-Z）带窗
  const north=new THREE.Group();
  const winW=Math.min(w*0.62,2.0), winH=1.30;
  const side=(w-winW)/2;
  if(side>0.02){
    const l=seg(side,MAT.wall); l.position.set(-(winW+side)/2,H/2,0); l.castShadow=true; north.add(l);
    const r=seg(side,MAT.wall); r.position.set((winW+side)/2,H/2,0); r.castShadow=true; north.add(r);
    const bot=seg(winW,MAT.wall); bot.scale.y=((H-winH)/2)/H; bot.position.set(0,(H-winH)/4*0+0.0,0);
    bot.position.y=(H-winH)/2; bot.scale.set(1,(H-winH)/H,1); north.add(bot);
    const top=seg(winW,MAT.wall); top.position.set(0,winH+(H-winH)/2,0);
    top.scale.set(1,(H-winH)/H,1); north.add(top);
    const win=latticeWindow(winW,winH); win.position.set(0,winH/2+(H-winH)*0.06,0.06); north.add(win);
  }
  north.position.set(0,floorY,-d/2); north.scale.y=1;
  grp.add(north);

  // 南墙（+Z）门洞 + 格栅门
  const south=new THREE.Group();
  const doorW=1.10, doorH=2.05, sideS=(w-doorW)/2;
  if(sideS>0.02){
    const l=seg(sideS,MAT.wall); l.position.set(-(doorW+sideS)/2,H/2,0); l.castShadow=true; south.add(l);
    const r=seg(sideS,MAT.wall); r.position.set((doorW+sideS)/2,H/2,0); r.castShadow=true; south.add(r);
    const top=seg(doorW,MAT.wall); top.position.set(0,doorH+(H-doorH)/2,0);
    top.scale.set(1,(H-doorH)/H,1); south.add(top);
  }
  const dl=latticeDoor(doorW,doorH); dl.position.set(0,0.02,0.04); dl.rotation.y=0.62; south.add(dl);
  south.position.set(0,floorY,d/2);
  grp.add(south);

  // 东西实墙
  put(seg(d,MAT.wall),-w/2,0);
  put(seg(d,MAT.wall2),w/2,0);

  /* 屋顶 */
  const roof=chineseRoof(w,d,0.78,0.34);
  roof.position.y=floorY+H;
  grp.add(roof);

  /* 碰撞：四面墙（门洞放行 → 南墙分两段） */
  const cxw=w/2+T, cxd=d/2+T;
  const hx0=-cxw-w/2, hx1=-cxw+ (w-doorW)/2;
  const hx2= cxw- (w-doorW)/2, hx3=cxw+w/2;
  grp.userData.boxes=[
    [hx0,hx1,-cxd,cxd], [hx2,hx3,-cxd,cxd],          // 南墙左右两段
    [-cxw,cxw,-cxd-0.02,-cxd],                        // 北墙
    [-cxw-0.02,-cxw,cxd-0.01,cxd],                    // 西墙
    [cxw,cxd+0.02,cxd-0.01,cxd],                      // 东墙
  ];
  grp.position.set(r.cx,0,r.cz);
  grp.rotation.y=r.ry||0;
  grp.userData.floorY=floorY;
  grp.userData.id=r.id;
  return grp;
}
window.__buildRoom=buildRoom;
window.__ROOMS=ROOMS;