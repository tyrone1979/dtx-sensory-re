#!/usr/bin/env python3
"""解析 .litematic (gzip+NBT) 蓝图，导出方块坐标/方块名清单。
用途：把网上下载的中式体素建筑底座转成可读数据，接入自己的体素引擎。
用法：python3 parse_litematic.py 文件.litematic [输出json]
"""
import sys, gzip, json, io, struct
from collections import Counter

TAG_END, TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE = 0, 1, 2, 3, 4, 5, 6
TAG_BYTE_ARRAY, TAG_STRING, TAG_LIST, TAG_COMPOUND, TAG_INT_ARRAY, TAG_LONG_ARRAY = 7, 8, 9, 10, 11, 12


class Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def u1(self):
        v = self.d[self.p]; self.p += 1; return v

    def i1(self):
        v = struct.unpack_from('>b', self.d, self.p)[0]; self.p += 1; return v

    def i2(self):
        v = struct.unpack_from('>h', self.d, self.p)[0]; self.p += 2; return v

    def u2(self):
        v = struct.unpack_from('>H', self.d, self.p)[0]; self.p += 2; return v

    def i4(self):
        v = struct.unpack_from('>i', self.d, self.p)[0]; self.p += 4; return v

    def i8(self):
        v = struct.unpack_from('>q', self.d, self.p)[0]; self.p += 8; return v

    def f4(self):
        v = struct.unpack_from('>f', self.d, self.p)[0]; self.p += 4; return v

    def f8(self):
        v = struct.unpack_from('>d', self.d, self.p)[0]; self.p += 8; return v

    def string(self):
        n = self.u2()
        s = self.d[self.p:self.p + n].decode('utf-8', 'replace')
        self.p += n
        return s


def read_payload(r, tag):
    if tag == TAG_BYTE: return r.i1()
    if tag == TAG_SHORT: return r.i2()
    if tag == TAG_INT: return r.i4()
    if tag == TAG_LONG: return r.i8()
    if tag == TAG_FLOAT: return r.f4()
    if tag == TAG_DOUBLE: return r.f8()
    if tag == TAG_BYTE_ARRAY:
        n = r.i4(); v = r.d[r.p:r.p + n]; r.p += n; return v
    if tag == TAG_STRING: return r.string()
    if tag == TAG_LIST:
        it = r.u1(); n = r.i4()
        return [read_payload(r, it) for _ in range(max(0, n))]
    if tag == TAG_COMPOUND:
        out = {}
        while True:
            t = r.u1()
            if t == TAG_END: return out
            name = r.string()
            out[name] = read_payload(r, t)
    if tag == TAG_INT_ARRAY:
        n = r.i4(); v = list(struct.unpack_from('>%di' % n, r.d, r.p)); r.p += 4 * n; return v
    if tag == TAG_LONG_ARRAY:
        n = r.i4(); v = list(struct.unpack_from('>%dq' % n, r.d, r.p)); r.p += 8 * n; return v
    raise ValueError('unknown tag %d at %d' % (tag, r.p))


def load(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    r = Reader(raw)
    t = r.u1()
    if t != TAG_COMPOUND: raise ValueError('root not compound: %d' % t)
    r.string()  # root name
    return read_payload(r, TAG_COMPOUND)


def unpack_litematica_longs(longs):
    """Litematica v6 把方块状态 id 以 9 bit 一个值、每个 long 打包 7 个的方式存储。
    返回解码后的 id 序列（顺序对应 x + z*SX + y*SX*SZ 的立方体遍历）。"""
    vals = []
    for L in longs:
        if isinstance(L, (bytes, bytearray)):
            L = int.from_bytes(L[:8], 'little', signed=True)
        for i in range(7):
            vals.append((L >> (9 * i)) & 0x1FF)
    return vals


def parse_litematic_v6(nbt):
    """Litematica v6：Regions[name] -> BlockStates(long[] 每 long 打包 7 个 9bit id)
    + BlockStatePalette(list[{Name,Properties}])。按 (x,z,y) 立方体顺序还原坐标。"""
    md = nbt.get('Metadata', {}) or {}
    es = md.get('EnclosingSize', {}) or {}
    size = [es.get('x', 0), es.get('y', 0), es.get('z', 0)]

    blocks = []
    regs = nbt.get('Regions', {}) or {}
    if isinstance(regs, dict):
        regs = list(regs.values())
    for region in regs:
        if not isinstance(region, dict):
            continue
        rp = region.get('Position', {}) or {}
        rs = region.get('Size', {}) or {}
        rx, ry, rz = rp.get('x', 0), rp.get('y', 0), rp.get('z', 0)
        sx = abs(rs.get('x', 1)); sy = abs(rs.get('y', 1)); sz = abs(rs.get('z', 1))
        palette = region.get('BlockStatePalette', []) or []
        pnames = []
        for st in palette:
            if isinstance(st, dict):
                pnames.append((st.get('Name', ''), st.get('Properties', {}) or {}))
            else:
                pnames.append((str(st), {}))
        data = region.get('BlockStates', []) or []
        if not data:
            continue
        flat = unpack_litematica_longs(data)
        # 立方体遍历顺序：x 最快，其次 z，再 y
        idx = 0
        for ly in range(sy):
            for lz in range(sz):
                for lx in range(sx):
                    if idx >= len(flat):
                        break
                    sid = flat[idx]; idx += 1
                    if sid >= len(pnames):
                        continue
                    name, props = pnames[sid]
                    if not name or name == 'minecraft:air':
                        continue
                    blocks.append({'x': rx + lx, 'y': ry + ly, 'z': rz + lz,
                                   'name': name, 'props': props})
    return size, blocks


def varint_reader(data, pos=0):
    """Litematica v6 Entries 用 zigzag varint 编码的一维数组。"""
    out = []
    p = pos
    n = len(data)
    while p < n:
        val = 0
        shift = 0
        while True:
            b = data[p]; p += 1
            val |= (b & 0x7F) << shift
            shift += 7
            if not (b & 0x80):
                break
        # zigzag 解码
        if val & 1:
            out.append(-(val >> 1) - 1)
        else:
            out.append(val >> 1)
    return out, p


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else None
    nbt = load(src)
    print('顶层键:', list(nbt.keys()))
    print('Version:', nbt.get('Version'), ' DataVersion:', nbt.get('MinecraftDataVersion'))
    md = nbt.get('Metadata', {}) or {}
    print('Metadata:', json.dumps({k: str(v) for k, v in md.items()}, ensure_ascii=False)[:300])

    if 'Regions' in nbt:
        size, blocks = parse_litematic_v6(nbt)
        print('尺寸 XYZ:', size)
        cnt = Counter()
        for b in blocks:
            cnt[b['name'] or '(air)'] += 1
        print('方块记录数:', len(blocks))
        if blocks:
            xs = [b['x'] for b in blocks]; ys = [b['y'] for b in blocks]; zs = [b['z'] for b in blocks]
            print('包围盒: x[%d..%d] y[%d..%d] z[%d..%d]' % (
                min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
        print('--- 方块种类 Top20 ---')
        for k, v in cnt.most_common(20):
            print('  %-46s %d' % (k, v))
        if out:
            json.dump({'size': size, 'blocks': blocks}, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
            print('已写出:', out)
        return

    # 老式单块列表
    meta = {k: nbt.get(k) for k in ('Version', 'DataVersion', 'Size', 'MinPos', 'PaletteMax') if k in nbt}
    print('元信息:', json.dumps(meta, ensure_ascii=False, default=str)[:300])
    size = nbt.get('Size', [0, 0, 0])
    print('尺寸 XYZ:', size)
    pal = nbt.get('Palette', {})
    name2id = {v: k for k, v in pal.items()}
    blocks = nbt.get('Blocks') or []
    print('方块记录数:', len(blocks))
    cnt = Counter()
    coords = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        x, y, z = b.get('x', 0), b.get('y', 0), b.get('z', 0)
        st = b.get('State', 0)
        cnt[name2id.get(st, 'state:%d' % st)] += 1
        coords.append((x, y, z))
    if coords:
        xs = [c[0] for c in coords]; ys = [c[1] for c in coords]; zs = [c[2] for c in coords]
        print('实际包围盒: x[%d..%d] y[%d..%d] z[%d..%d]' % (
            min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)))
    print('--- 方块种类 Top20 ---')
    for k, v in cnt.most_common(20):
        print('  %-46s %d' % (k, v))
    if out:
        data = {'size': size, 'blocks': [{'x': x, 'y': y, 'z': z} for x, y, z in coords], 'palette': pal, 'counts': dict(cnt)}
        json.dump(data, open(out, 'w', encoding='utf-8'), ensure_ascii=False)
        print('已写出:', out)


if __name__ == '__main__':
    main()
