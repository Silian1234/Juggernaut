# Minimal UnityFS bundle reader/writer helpers (pure Python), enough to:
#  - decompress a bundle (LZ4/LZ4HC/none) into its inner files
#  - parse a SerializedFile (format >= 22) object table + externals
#  - write an uncompressed UnityFS bundle back
import struct, io, sys


def lz4_block_decompress(src, usize):
    dst = bytearray()
    i = 0
    n = len(src)
    while i < n:
        tok = src[i]; i += 1
        lit = tok >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1; lit += b
                if b != 255: break
        dst += src[i:i + lit]; i += lit
        if i >= n: break
        off = src[i] | (src[i + 1] << 8); i += 2
        ml = tok & 15
        if ml == 15:
            while True:
                b = src[i]; i += 1; ml += b
                if b != 255: break
        ml += 4
        start = len(dst) - off
        for k in range(ml):
            dst.append(dst[start + k])
    assert len(dst) == usize, (len(dst), usize)
    return bytes(dst)


def decomp(data, flags, usize):
    c = flags & 0x3F
    if c == 0: return data
    if c in (2, 3): return lz4_block_decompress(data, usize)
    if c == 1:
        import lzma
        props = data[:5]
        dec = lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[{"id": lzma.FILTER_LZMA1, "dict_size": struct.unpack('<I', props[1:5])[0],
                                                                 "lc": props[0] % 9, "lp": (props[0] // 9) % 5, "pb": props[0] // 45}])
        return dec.decompress(data[5:], usize)
    raise ValueError("compression %d" % c)


def cstr(b, o):
    e = b.index(b'\0', o)
    return b[o:e].decode('utf-8', 'replace'), e + 1


def read_bundle(path):
    b = open(path, 'rb').read()
    sig, o = cstr(b, 0)
    assert sig == 'UnityFS', sig
    ver = struct.unpack('>I', b[o:o + 4])[0]; o += 4
    pv, o = cstr(b, o); ev, o = cstr(b, o)
    size, csz, usz, flags = struct.unpack('>qIII', b[o:o + 20]); o += 20
    if ver >= 7: o = (o + 15) & ~15
    if flags & 0x80:
        info = b[len(b) - csz:]
    else:
        info = b[o:o + csz]; o += csz
    if flags & 0x200: o = (o + 15) & ~15
    info = decomp(info, flags, usz)
    p = 16
    nb = struct.unpack('>i', info[p:p + 4])[0]; p += 4
    blocks = []
    for _ in range(nb):
        u, c, f = struct.unpack('>IIH', info[p:p + 10]); p += 10
        blocks.append((u, c, f))
    nn = struct.unpack('>i', info[p:p + 4])[0]; p += 4
    nodes = []
    for _ in range(nn):
        off, sz, fl = struct.unpack('>qqI', info[p:p + 20]); p += 20
        name, p = cstr(info, p)
        nodes.append((off, sz, fl, name))
    data = bytearray()
    for u, c, f in blocks:
        data += decomp(b[o:o + c], f, u); o += c
    files = {name: bytes(data[off:off + sz]) for off, sz, fl, name in nodes}
    meta = dict(version=ver, player=pv, engine=ev, nodes=[(n[3], n[2]) for n in nodes])
    return meta, files


def write_bundle(path, meta, files):
    """Write uncompressed UnityFS (single block per file set)."""
    names = [n for n, _ in meta['nodes']]
    flagsmap = dict(meta['nodes'])
    data = bytearray(); nodes = []
    for n in names:
        nodes.append((len(data), len(files[n]), flagsmap[n], n)); data += files[n]
    # blocks: split into <=128KB uncompressed blocks (flag 0x40 = streamed? use 0)
    blocks = []
    BS = 0x20000
    for i in range(0, len(data), BS):
        ln = min(BS, len(data) - i); blocks.append((ln, ln, 0))
    info = bytearray(b'\0' * 16)
    info += struct.pack('>i', len(blocks))
    for u, c, f in blocks: info += struct.pack('>IIH', u, c, f)
    info += struct.pack('>i', len(nodes))
    for off, sz, fl, n in nodes: info += struct.pack('>qqI', off, sz, fl) + n.encode() + b'\0'
    hdr = bytearray(b'UnityFS\0') + struct.pack('>I', meta['version']) + meta['player'].encode() + b'\0' + meta['engine'].encode() + b'\0'
    flags = 0x40 | 0x200 if meta['version'] >= 7 else 0x40  # block info combined with header; 0x200 = padding before blocks
    # compute size later
    def build(total):
        h = bytearray(hdr) + struct.pack('>qIII', total, len(info), len(info), flags)
        if meta['version'] >= 7:
            while len(h) % 16: h += b'\0'
        h += info
        if flags & 0x200:
            while len(h) % 16: h += b'\0'
        return h
    h = build(0)
    total = len(h) + len(data)
    out = build(total) + data
    open(path, 'wb').write(out)


class SF:
    """SerializedFile (format >= 22, little endian data)."""
    def __init__(self, b):
        self.b = b
        msz, fsz, self.fmt, doff = struct.unpack('>IIII', b[:16])
        assert self.fmt >= 22, self.fmt
        self.big = b[16]
        msz, fsz, doff, _ = struct.unpack('>IqqQ', b[20:48])
        self.dataoff = doff
        o = 48
        e = '>' if self.big else '<'
        self.e = e
        self.ver, o = cstr(b, o)
        self.platform = struct.unpack(e + 'i', b[o:o + 4])[0]; o += 4
        self.typetree = b[o] != 0; o += 1
        tc = struct.unpack(e + 'i', b[o:o + 4])[0]; o += 4
        self.types = []
        for _ in range(tc):
            cid, strip, sidx = struct.unpack(e + 'iBh', b[o:o + 7]); o += 7
            if cid == 114 or sidx >= 0: o += 16
            o += 16
            if self.typetree:
                nn, sbs = struct.unpack(e + 'ii', b[o:o + 8]); o += 8
                o += nn * 32 + sbs
                dc = struct.unpack(e + 'i', b[o:o + 4])[0]; o += 4 + dc * 4
            self.types.append(cid)
        oc = struct.unpack(e + 'i', b[o:o + 4])[0]; o += 4
        self.objects = []
        for _ in range(oc):
            o = (o + 3) & ~3
            pid, start, size, tid = struct.unpack(e + 'qqIi', b[o:o + 24]); o += 24
            self.objects.append(dict(pathID=pid, start=start, size=size, classID=self.types[tid], off=self.dataoff + start))
        sc = struct.unpack(e + 'i', b[o:o + 4])[0]; o += 4
        for _ in range(sc):
            o += 4; o = (o + 3) & ~3; o += 8
        ec = struct.unpack(e + 'i', b[o:o + 4])[0]; o += 4
        self.externals = []
        for _ in range(ec):
            _, o = cstr(b, o); o += 16 + 4
            pn, o = cstr(b, o)
            self.externals.append(pn)

    def obj_bytes(self, ob):
        return self.b[ob['off']:ob['off'] + ob['size']]

    def name_of(self, ob):
        d = self.obj_bytes(ob)
        if len(d) < 4: return None
        n = struct.unpack('<i', d[:4])[0]
        if 0 <= n < 256 and 4 + n <= len(d):
            try: return d[4:4 + n].decode('utf-8')
            except: return None
        return None


def material_pptrs(sf, ob):
    """Material: m_Name (aligned string), m_Shader PPtr(int fileID, int64 pathID)."""
    d = sf.obj_bytes(ob)
    n = struct.unpack('<i', d[:4])[0]
    o = (4 + n + 3) & ~3
    fid, pid = struct.unpack('<iq', d[o:o + 12])
    return d[4:4 + n].decode(), fid, pid


if __name__ == '__main__':
    meta, files = read_bundle(sys.argv[1])
    print(meta)
    for name, data in files.items():
        if name.endswith('.resS') or name.endswith('.resource'): print(' ', name, len(data)); continue
        try:
            sf = SF(data)
        except Exception as ex:
            print(' ', name, len(data), 'not SF', ex); continue
        print(' ', name, 'fmt', sf.fmt, sf.ver, 'objs', len(sf.objects), 'externals', sf.externals)
        for ob in sf.objects:
            if ob['classID'] == 21:
                print('    material', material_pptrs(sf, ob))
