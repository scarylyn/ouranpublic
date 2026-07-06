#!/usr/bin/env python3
"""Build the 4px-wide ASCII variant of the dialogue font (variant C).

The dialogue renderer blits exactly glyph_w columns and advances by
glyph_w + letter_spacing (2px in normal dialogue), so narrowing means
redrawing ink, not just metrics. Wide (5px) glyphs are squeezed to 4px by
removing the most redundant column; letters where that breaks the shape
use hand-drawn 4px bitmaps below.

Usage: make_narrow_font.py [--src PATH] [--out PATH] [--preview PNG]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nftr_tool import NFTR

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_SRC = os.path.join(ROOT, 'Game Files/data/fonts/LD937714LD937742.NFTR')
BACKUP_SRC = os.path.join(ROOT, 'backups/fonts_20260702/LD937714LD937742.NFTR')

# Glyphs that stay 5px wide: squeezing them breaks the shape, and since the
# renderer is proportional per glyph they can simply keep their width.
KEEP5 = set('mwMW@#$%&08D')


def squeeze_5to4(bm, cell_w):
    """Remove the interior column most similar to a neighbour (cols 0-4 -> 4)."""
    cols = [[row[x] for row in bm] for x in range(5)]
    best, bestscore = None, None
    for x in (1, 2, 3):
        score = min(sum(a != b for a, b in zip(cols[x], cols[x-1])),
                    sum(a != b for a, b in zip(cols[x], cols[x+1])))
        if bestscore is None or score < bestscore:
            best, bestscore = x, score
    out = []
    for row in bm:
        keep = [row[x] for x in range(5) if x != best]
        # OR the removed column into its nearest neighbour to preserve ink
        merged = keep[:]
        nb = best - 1 if best > 0 else best
        idx = nb if nb < best else nb - 1
        merged[idx] = merged[idx] or row[best]
        out.append(merged + [0]*(cell_w-4))
    return out


def pack_bitmap(rows, cell_w, cell_size):
    flat = []
    for row in rows:
        flat.extend((row + [0]*cell_w)[:cell_w])
    by = bytearray(cell_size)
    for i, v in enumerate(flat):
        if v:
            by[i//8] |= 0x80 >> (i % 8)
    return by


def build(src_path, out_path):
    if not os.path.exists(src_path):
        raise SystemExit(f"missing source font: {src_path}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    f = NFTR(src_path)
    edited = 0
    for c in range(0x21, 0x7F):
        g = f.char_to_glyph.get(c)
        if g is None:
            continue
        o = f.metrics_off(g)
        gw = f.data[o+1]
        if gw != 5:
            continue
        ch = chr(c)
        if ch in KEEP5:
            continue
        bm = f.glyph_bitmap(g)
        new = squeeze_5to4(bm, f.cell_w)
        off = f.glyph_data_off + g*f.cell_size
        f.data[off:off+f.cell_size] = pack_bitmap(new, f.cell_w, f.cell_size)
        f.data[o+1] = 4  # glyph_w: what the dialogue renderer blits/advances
        edited += 1
    with open(out_path, 'wb') as fh:
        fh.write(f.data)
    print(f'wrote {out_path}: {edited} glyphs redrawn at 4px')
    return f


def preview(font, png_path, spacing=2, scale=3):
    """Simulate the dialogue blitter: blit glyph_w cols at pen, pen += glyph_w+spacing."""
    lines = [
        "The Host Club is packed with",
        "guests again today. MW mw @#$%&",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "abcdefghijklmnopqrstuvwxyz 0123456789",
        "\"Kyoya, what would you say?\" (huh?!)",
    ]
    H = (font.cell_h + 3) * len(lines)
    W = 260
    img = [[0]*W for _ in range(H)]
    for li, line in enumerate(lines):
        pen = 2
        oy = li*(font.cell_h+3)
        for ch in line:
            if ch == ' ':
                pen += spacing
                continue
            g = font.char_to_glyph.get(ord(ch))
            if g is None:
                pen += spacing
                continue
            gw = font.data[font.metrics_off(g)+1]
            bm = font.glyph_bitmap(g)
            for y in range(font.cell_h):
                for x in range(min(gw, font.cell_w)):
                    if bm[y][x] and pen+x < W:
                        img[oy+y][pen+x] = 255
            pen += gw + spacing
            if ch in ',.':
                pen += 4
    import struct, zlib
    big = [[img[y//scale][x//scale] for x in range(W*scale)] for y in range(H*scale)]
    raw = b''.join(b'\x00'+bytes(r) for r in big)
    def chunk(t, d):
        c = t+d
        return struct.pack('>I', len(d))+c+struct.pack('>I', zlib.crc32(c))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', W*scale, H*scale, 8, 0, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    open(png_path, 'wb').write(png)
    print('preview:', png_path)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC,
                    help='source LD937714LD937742.NFTR from your extracted game files')
    ap.add_argument('--out', default=os.path.join(ROOT, 'build/testfonts/LD_narrow4.NFTR'))
    ap.add_argument('--preview')
    a = ap.parse_args()
    if not os.path.exists(a.src) and a.src == DEFAULT_SRC and os.path.exists(BACKUP_SRC):
        a.src = BACKUP_SRC
    font = build(a.src, a.out)
    if a.preview:
        preview(font, a.preview)
