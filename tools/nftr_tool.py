#!/usr/bin/env python3
"""NFTR (Nitro FonT Resource) inspector/editor for the Ouran EN patch.

Subcommands:
  info FONT.NFTR                 - dump header + FINF/CGLP/CWDH/CMAP summary
  widths FONT.NFTR               - dump per-char metrics for ASCII 0x20-0x7E
  render FONT.NFTR OUT.png       - render ASCII glyph sheet to PNG
  narrow FONT.NFTR OUT.NFTR N    - reduce ASCII advance widths by N pixels
                                   (advance only; bitmaps untouched). Use
                                   --min to clamp (default 3), --pct for
                                   percentage mode instead of fixed N.
"""
import argparse
import struct
import sys


def u8(b, o): return b[o]
def u16(b, o): return struct.unpack_from('<H', b, o)[0]
def u32(b, o): return struct.unpack_from('<I', b, o)[0]


class NFTR:
    def __init__(self, path):
        self.path = path
        self.data = bytearray(open(path, 'rb').read())
        d = self.data
        assert d[0:4] in (b'RTFN', b'NFTR'), 'not an NFTR'
        self.header_size = u16(d, 0x0C)
        self.nblocks = u16(d, 0x0E)
        # FINF block directly after header
        fo = self.header_size
        assert d[fo:fo+4] == b'FNIF', d[fo:fo+4]
        self.finf_off = fo
        self.font_type = u8(d, fo+8)
        self.line_feed = u8(d, fo+9)
        self.alter_char = u16(d, fo+10)
        self.def_left = u8(d, fo+12)
        self.def_glyph_w = u8(d, fo+13)
        self.def_char_w = u8(d, fo+14)
        self.encoding = u8(d, fo+15)
        # offsets stored are +8 (point at block data, past magic+size)
        self.cglp_off = u32(d, fo+16) - 8
        self.cwdh_off = u32(d, fo+20) - 8
        self.cmap_off = u32(d, fo+24) - 8
        finf_size = u32(d, fo+4)
        if finf_size >= 0x20:
            self.glyph_h = u8(d, fo+28)
            self.glyph_w = u8(d, fo+29)
            self.bearing_y = u8(d, fo+30)
            self.bearing_x = u8(d, fo+31)
        # CGLP
        co = self.cglp_off
        assert d[co:co+4] == b'PLGC', d[co:co+4]
        self.cell_w = u8(d, co+8)
        self.cell_h = u8(d, co+9)
        self.cell_size = u16(d, co+10)
        self.baseline = u8(d, co+12)
        self.max_w = u8(d, co+13)
        self.bpp = u8(d, co+14)
        self.rotation = u8(d, co+15)
        self.glyph_data_off = co + 16
        cglp_size = u32(d, co+4)
        self.nglyphs = (cglp_size - 16) // self.cell_size
        # CWDH chain
        self.cwdh = []  # list of (first, last, data_off)
        o = self.cwdh_off
        while o:
            assert d[o:o+4] == b'HDWC', (hex(o), d[o:o+4])
            first = u16(d, o+8)
            last = u16(d, o+10)
            nxt = u32(d, o+12)
            self.cwdh.append((first, last, o+16))
            o = nxt - 8 if nxt else 0
        # CMAP chain
        self.char_to_glyph = {}
        o = self.cmap_off
        while o:
            assert d[o:o+4] == b'PAMC', (hex(o), d[o:o+4])
            first = u16(d, o+8)
            last = u16(d, o+10)
            typ = u16(d, o+12)
            nxt = u32(d, o+16)
            p = o + 20
            if typ == 0:
                g0 = u16(d, p)
                for i, c in enumerate(range(first, last+1)):
                    self.char_to_glyph[c] = g0 + i
            elif typ == 1:
                for i, c in enumerate(range(first, last+1)):
                    g = u16(d, p + i*2)
                    if g != 0xFFFF:
                        self.char_to_glyph[c] = g
            elif typ == 2:
                n = u16(d, p)
                for i in range(n):
                    c = u16(d, p+2 + i*4)
                    g = u16(d, p+4 + i*4)
                    self.char_to_glyph[c] = g
            o = nxt - 8 if nxt else 0

    def glyph_index(self, ch):
        return self.char_to_glyph.get(ord(ch))

    def metrics_off(self, gidx):
        """byte offset of (left, glyph_w, char_w) triple for glyph index"""
        for first, last, off in self.cwdh:
            if first <= gidx <= last:
                return off + (gidx - first) * 3
        return None

    def metrics(self, gidx):
        o = self.metrics_off(gidx)
        if o is None:
            return (self.def_left, self.def_glyph_w, self.def_char_w)
        left = struct.unpack_from('<b', self.data, o)[0]
        return (left, self.data[o+1], self.data[o+2])

    def glyph_bitmap(self, gidx):
        off = self.glyph_data_off + gidx * self.cell_size
        raw = self.data[off:off+self.cell_size]
        bits = []
        acc = 0
        nb = 0
        for byte in raw:
            for k in range(7, -1, -1):
                bits.append((byte >> k) & 1 if self.bpp == 1 else None)
        if self.bpp != 1:
            # generic bpp unpack
            bits = []
            val = int.from_bytes(raw, 'big')
            total = (len(raw)*8)//self.bpp
            for i in range(total):
                shift = len(raw)*8 - (i+1)*self.bpp
                bits.append((val >> shift) & ((1 << self.bpp)-1))
        rows = []
        for y in range(self.cell_h):
            rows.append(bits[y*self.cell_w:(y+1)*self.cell_w])
        return rows


def cmd_info(a):
    f = NFTR(a.font)
    print(f'{f.path}')
    print(f'  glyphs: {f.nglyphs}  cell {f.cell_w}x{f.cell_h}  bpp {f.bpp}  baseline {f.baseline}  max_w {f.max_w}')
    print(f'  line_feed {f.line_feed}  encoding {f.encoding}  default widths L/G/C: {f.def_left}/{f.def_glyph_w}/{f.def_char_w}')
    print(f'  CWDH regions: {[(first,last) for first,last,_ in f.cwdh]}')
    codes = sorted(f.char_to_glyph)
    print(f'  mapped chars: {len(codes)}  range U+{codes[0]:04X}..U+{codes[-1]:04X}')
    asc = [c for c in codes if 0x20 <= c < 0x7F]
    print(f'  ASCII coverage: {len(asc)} chars')
    ws = {f.metrics(f.char_to_glyph[c])[2] for c in asc}
    print(f'  ASCII advance widths: {sorted(ws)} ({"proportional" if len(ws)>1 else "monospace"})')


def cmd_widths(a):
    f = NFTR(a.font)
    print('char\tglyph\tleft\tglyph_w\tadvance')
    for c in range(0x20, 0x7F):
        g = f.char_to_glyph.get(c)
        if g is None:
            continue
        l, gw, cw = f.metrics(g)
        print(f'{chr(c)!r}\t{g}\t{l}\t{gw}\t{cw}')


def cmd_render(a):
    f = NFTR(a.font)
    chars = [chr(c) for c in range(0x20, 0x7F) if ord(chr(c)) in f.char_to_glyph]
    if a.chars:
        chars = list(a.chars)
    cols = 16
    rows = (len(chars) + cols - 1) // cols
    W = cols * (f.cell_w + 2)
    H = rows * (f.cell_h + 2)
    img = [[255]*W for _ in range(H)]
    for i, ch in enumerate(chars):
        g = f.char_to_glyph.get(ord(ch))
        if g is None:
            continue
        bm = f.glyph_bitmap(g)
        ox = (i % cols) * (f.cell_w + 2)
        oy = (i // cols) * (f.cell_h + 2)
        mx = (1 << f.bpp) - 1
        for y, row in enumerate(bm):
            for x, v in enumerate(row):
                if v:
                    img[oy+y][ox+x] = 255 - int(255*v/mx)
    import zlib
    def png(w, h, pix):
        raw = b''.join(b'\x00' + bytes(r) for r in pix)
        def chunk(t, d):
            c = t + d
            return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c))
        return (b'\x89PNG\r\n\x1a\n'
                + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 0, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw))
                + chunk(b'IEND', b''))
    open(a.out, 'wb').write(png(W, H, img))
    print(f'wrote {a.out} ({len(chars)} glyphs)')


def cmd_narrow(a):
    f = NFTR(a.font)
    changed = 0
    for c in range(0x21, 0x7F):  # skip space unless --space
        g = f.char_to_glyph.get(c)
        if g is None:
            continue
        o = f.metrics_off(g)
        if o is None:
            continue
        cw = f.data[o+2]
        if a.pct:
            new = max(a.min, round(cw * (100 - a.amount) / 100))
        else:
            new = max(a.min, cw - a.amount)
        if new != cw:
            f.data[o+2] = new
            changed += 1
    if a.space:
        g = f.char_to_glyph.get(0x20)
        if g is not None:
            o = f.metrics_off(g)
            if o is not None:
                cw = f.data[o+2]
                new = max(2, cw - a.space)
                f.data[o+2] = new
                changed += 1
    open(a.out, 'wb').write(f.data)
    print(f'wrote {a.out}: {changed} advances changed')


def _main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('info'); s.add_argument('font'); s.set_defaults(fn=cmd_info)
    s = sub.add_parser('widths'); s.add_argument('font'); s.set_defaults(fn=cmd_widths)
    s = sub.add_parser('render'); s.add_argument('font'); s.add_argument('out'); s.add_argument('--chars'); s.set_defaults(fn=cmd_render)
    s = sub.add_parser('narrow'); s.add_argument('font'); s.add_argument('out')
    s.add_argument('amount', type=int); s.add_argument('--pct', action='store_true')
    s.add_argument('--min', type=int, default=3); s.add_argument('--space', type=int, default=0)
    s.set_defaults(fn=cmd_narrow)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    _main()
