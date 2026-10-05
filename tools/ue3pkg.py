"""Minimal UE3 (v859) package reader: decompress, read name/import/export tables, dump export bytes."""
import struct, sys, zlib, io

TAG = 0x9E2A83C1


class R:
    def __init__(s, b, o=0): s.b, s.o = b, o
    def i32(s): v = struct.unpack_from('<i', s.b, s.o)[0]; s.o += 4; return v
    def u32(s): v = struct.unpack_from('<I', s.b, s.o)[0]; s.o += 4; return v
    def u16(s): v = struct.unpack_from('<H', s.b, s.o)[0]; s.o += 2; return v
    def i64(s): v = struct.unpack_from('<q', s.b, s.o)[0]; s.o += 8; return v
    def fstr(s):
        n = s.i32()
        if n == 0: return ''
        if n > 0:
            v = s.b[s.o:s.o + n - 1].decode('latin1'); s.o += n; return v
        n = -n; v = s.b[s.o:s.o + 2 * n - 2].decode('utf-16le'); s.o += 2 * n; return v
    def skip(s, n): s.o += n


def decompress_lzo(src, dst_len):
    import lzo  # python-lzo
    return lzo.decompress(src, False, dst_len)


def read_header(b):
    r = R(b)
    h = {}
    assert r.u32() == TAG
    h['ver'] = r.u16(); h['lic'] = r.u16()
    h['header_size'] = r.i32(); h['folder'] = r.fstr()
    h['flags'] = r.u32()
    h['name_count'], h['name_off'] = r.i32(), r.i32()
    h['export_count'], h['export_off'] = r.i32(), r.i32()
    h['import_count'], h['import_off'] = r.i32(), r.i32()
    h['depends_off'] = r.i32()
    h['iex_guids_off'], h['iex_import_guids'], h['iex_export_guids'] = r.i32(), r.i32(), r.i32()
    h['thumb_off'] = r.i32()
    r.skip(16)  # guid
    gens = r.i32(); r.skip(gens * 12)
    h['engine_ver'] = r.i32(); h['cooker_ver'] = r.i32()
    h['comp_flags'] = r.u32()
    n = r.i32()
    h['chunks'] = [(r.i32(), r.i32(), r.i32(), r.i32()) for _ in range(n)]
    h['_end'] = r.o
    return h


def decompress(b):
    h = read_header(b)
    if not h['chunks']:
        return b, h
    total = max(uo + us for uo, us, co, cs in h['chunks'])
    out = bytearray(total)
    out[:h['_end']] = b[:h['_end']]
    for uo, us, co, cs in h['chunks']:
        r = R(b, co)
        assert r.u32() == TAG, 'bad chunk tag'
        bsz = r.i32(); csum = r.i32(); usum = r.i32()
        nblk = (usum + bsz - 1) // bsz
        blocks = [(r.i32(), r.i32()) for _ in range(nblk)]
        p = r.o; w = uo
        for c, u in blocks:
            src = b[p:p + c]; p += c
            if h['comp_flags'] & 1: d = zlib.decompress(src)
            elif h['comp_flags'] & 2: d = decompress_lzo(src, u)
            else: raise SystemExit(f"unsupported compression {h['comp_flags']}")
            out[w:w + len(d)] = d; w += len(d)
    return bytes(out), h


class Package:
    def __init__(s, path):
        raw = open(path, 'rb').read()
        s.data, s.h = decompress(raw)
        r = R(s.data, s.h['name_off'])
        s.names = []
        for _ in range(s.h['name_count']):
            s.names.append(r.fstr()); r.i64()  # flags
        r.o = s.h['import_off']
        s.imports = []
        for _ in range(s.h['import_count']):
            cpkg = s.nm(r); cls = s.nm(r); outer = r.i32(); name = s.nm(r)
            s.imports.append(dict(cpkg=cpkg, cls=cls, outer=outer, name=name))
        r.o = s.h['export_off']
        s.exports = []
        for _ in range(s.h['export_count']):
            e = dict(cls=r.i32(), sup=r.i32(), outer=r.i32(), name=s.nm(r), arch=r.i32(),
                     oflags=r.i64(), size=r.i32(), off=r.i32(), eflags=r.u32())
            n = r.i32(); r.skip(n * 4)  # generation net object counts
            r.skip(16); r.u32()  # package guid, package flags
            s.exports.append(e)

    def nm(s, r):
        i = r.i32(); n = r.i32()
        base = s.names[i] if 0 <= i < len(s.names) else f'?{i}'
        return base if n == 0 else f'{base}_{n - 1}'

    def ref(s, i):
        if i > 0: return s.exports[i - 1]['name']
        if i < 0: return s.imports[-i - 1]['name']
        return 'None'

    def cls_of(s, e): return s.ref(e['cls']) if e['cls'] else 'Class'

    def path(s, i):
        parts = []
        while i:
            if i > 0: e = s.exports[i - 1]; parts.append(e['name']); i = e['outer']
            else: m = s.imports[-i - 1]; parts.append(m['name']); i = m['outer']
        return '.'.join(reversed(parts))

    def blob(s, e): return s.data[e['off']:e['off'] + e['size']]


if __name__ == '__main__':
    p = Package(sys.argv[1])
    h = p.h
    print(f"ver={h['ver']} lic={h['lic']} engine={h['engine_ver']} cooker={h['cooker_ver']} comp={h['comp_flags']} "
          f"names={len(p.names)} imports={len(p.imports)} exports={len(p.exports)}")
