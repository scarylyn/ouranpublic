#!/usr/bin/env python3
"""Render/edit simple DS NCER object sprites backed by NCGR/NCLR art.

This is intentionally small and focused on UI assets such as
ui/Title/TouchStartButton. It renders OAM entries from an NCER cell into a
normal image, can draw START on the composed image, then writes the edited
pixels back into the NCGR tiles used by the sprite.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

from art_sheet_tool import ncgr_payload, read_palette


SHAPES = {
    0: [(8, 8), (16, 16), (32, 32), (64, 64)],
    1: [(16, 8), (32, 8), (32, 16), (64, 32)],
    2: [(8, 16), (8, 32), (16, 32), (32, 64)],
}

OBJ_2D_TILES_WIDE = 32


def s8(v: int) -> int:
    return v - 256 if v >= 128 else v


def s9(v: int) -> int:
    v &= 0x1FF
    return v - 512 if v >= 256 else v


def u16(data: bytes, off: int) -> int:
    return int.from_bytes(data[off:off + 2], "little")


def parse_touchstyle_ncer(path: Path) -> list[dict]:
    data = path.read_bytes()
    if data[:4] != b"RECN":
        raise ValueError(f"not NCER: {path}")
    # This covers the simple cell bank assets in this project. At 0x30 the
    # first cell record gives the OAM count; entries are 6 bytes from 0x40.
    count = u16(data, 0x30)
    entries = []
    off = 0x40
    for _ in range(count):
        attr0 = u16(data, off)
        attr1 = u16(data, off + 2)
        attr2 = u16(data, off + 4)
        off += 6
        y = s8(attr0 & 0xFF)
        x = s9(attr1 & 0x1FF)
        shape = (attr0 >> 14) & 0x3
        size = (attr1 >> 14) & 0x3
        if shape not in SHAPES:
            continue
        w, h = SHAPES[shape][size]
        entries.append({
            "x": x,
            "y": y,
            "w": w,
            "h": h,
            "tile": attr2 & 0x3FF,
            "hflip": bool(attr1 & 0x1000),
            "vflip": bool(attr1 & 0x2000),
        })
    return entries


def decode_tile_indices(ncgr_path: Path) -> tuple[bytearray, int, int]:
    data = bytearray(ncgr_path.read_bytes())
    off, size = ncgr_payload(data)
    return data, off, size // 32


def get_pixel(tile_data: bytearray, tile: int, x: int, y: int) -> int:
    pos = tile * 32 + y * 4 + (x // 2)
    b = tile_data[pos]
    return (b & 0x0F) if x % 2 == 0 else (b >> 4)


def set_pixel(tile_data: bytearray, tile: int, x: int, y: int, value: int) -> None:
    pos = tile * 32 + y * 4 + (x // 2)
    b = tile_data[pos]
    if x % 2 == 0:
        b = (b & 0xF0) | (value & 0x0F)
    else:
        b = (b & 0x0F) | ((value & 0x0F) << 4)
    tile_data[pos] = b


def render(ncgr_path: Path, nclr_path: Path, ncer_path: Path) -> tuple[Image.Image, list[dict], tuple[int, int]]:
    img, entries, origin, _owners = render_with_owners(ncgr_path, nclr_path, ncer_path)
    return img, entries, origin


def render_with_owners(ncgr_path: Path, nclr_path: Path, ncer_path: Path):
    ncgr, payload_off, _ = decode_tile_indices(ncgr_path)
    tile_data = ncgr[payload_off:]
    palette = read_palette(nclr_path)
    entries = parse_touchstyle_ncer(ncer_path)
    min_x = min(e["x"] for e in entries)
    min_y = min(e["y"] for e in entries)
    max_x = max(e["x"] + e["w"] for e in entries)
    max_y = max(e["y"] + e["h"] for e in entries)
    img = Image.new("P", (max_x - min_x, max_y - min_y), 0)
    flat = []
    for r, g, b in palette[:256]:
        flat.extend([r, g, b])
    flat.extend([0] * (768 - len(flat)))
    img.putpalette(flat)
    px = img.load()
    owners = [[None for _ in range(img.width)] for _ in range(img.height)]
    for entry_i, e in enumerate(entries):
        tiles_per_row = e["w"] // 8
        for sy in range(e["h"]):
            for sx in range(e["w"]):
                src_x = e["w"] - 1 - sx if e["hflip"] else sx
                src_y = e["h"] - 1 - sy if e["vflip"] else sy
                tile = e["tile"] + (src_y // 8) * OBJ_2D_TILES_WIDE + (src_x // 8)
                idx = get_pixel(tile_data, tile, src_x % 8, src_y % 8)
                img_x = e["x"] - min_x + sx
                img_y = e["y"] - min_y + sy
                if idx:
                    px[img_x, img_y] = idx
                if idx or owners[img_y][img_x] is None:
                    owners[img_y][img_x] = (entry_i, src_x, src_y)
    return img, entries, (min_x, min_y), owners


def write_back(ncgr_path: Path, nclr_path: Path, ncer_path: Path, edited: Image.Image, out_ncgr: Path) -> None:
    ncgr, payload_off, tile_count = decode_tile_indices(ncgr_path)
    tile_data = ncgr[payload_off:payload_off + tile_count * 32]
    _orig_img, entries, _origin, owners = render_with_owners(ncgr_path, nclr_path, ncer_path)
    px = edited.convert("P").load()
    for img_y, row in enumerate(owners):
        for img_x, owner in enumerate(row):
            if owner is None:
                continue
            entry_i, src_x, src_y = owner
            e = entries[entry_i]
            tiles_per_row = e["w"] // 8
            val = int(px[img_x, img_y]) & 0x0F
            tile = e["tile"] + (src_y // 8) * OBJ_2D_TILES_WIDE + (src_x // 8)
            set_pixel(tile_data, tile, src_x % 8, src_y % 8, val)
    ncgr[payload_off:payload_off + len(tile_data)] = tile_data
    out_ncgr.parent.mkdir(parents=True, exist_ok=True)
    out_ncgr.write_bytes(ncgr)


def draw_start(img: Image.Image) -> Image.Image:
    out = img.copy()
    px = out.load()
    w, h = out.size
    dark = 1
    brown = 3
    gold = 8
    gold2 = 10
    white = 15
    gray = 13
    x0, y0, x1, y1 = 82, 8, 174, 26
    for y in range(y0, min(y1 + 1, h)):
        for x in range(x0, min(x1 + 1, w)):
            px[x, y] = brown
    for x in range(x0, min(x1 + 1, w)):
        if 0 <= y0 < h:
            px[x, y0] = gold2
        if 0 <= y0 + 1 < h:
            px[x, y0 + 1] = gold
        if 0 <= y1 < h:
            px[x, y1] = dark
    for y in range(y0, min(y1 + 1, h)):
        px[x0, y] = gold
        px[min(x1, w - 1), y] = dark

    font = {
        "S": ["11111", "10000", "10000", "11110", "00001", "00001", "11110"],
        "T": ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
        "A": ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
        "R": ["11110", "10001", "10001", "11110", "10100", "10010", "10001"],
    }
    text = "START"
    scale = 2
    cw = 5 * scale
    gap = scale
    tw = len(text) * cw + (len(text) - 1) * gap
    tx = (w - tw) // 2
    ty = 10

    def draw(dx: int, dy: int, color: int):
        x = tx + dx
        for ch in text:
            for yy, row in enumerate(font[ch]):
                for xx, bit in enumerate(row):
                    if bit == "1":
                        for sy in range(scale):
                            for sx in range(scale):
                                px2 = x + xx * scale + sx
                                py2 = ty + dy + yy * scale + sy
                                if 0 <= px2 < w and 0 <= py2 < h:
                                    px[px2, py2] = color
            x += cw + gap

    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1), (1, 1)]:
        draw(dx, dy, dark)
    draw(0, 0, white)
    x = tx
    for ch in text:
        for yy, row in enumerate(font[ch]):
            for xx, bit in enumerate(row):
                if bit == "1" and yy >= 5:
                    for sx in range(scale):
                        px2 = x + xx * scale + sx
                        py2 = ty + yy * scale + scale - 1
                        if 0 <= px2 < w and 0 <= py2 < h:
                            px[px2, py2] = gray
        x += cw + gap
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ncgr")
    parser.add_argument("nclr")
    parser.add_argument("ncer")
    parser.add_argument("--render-out")
    parser.add_argument("--draw-start-out")
    parser.add_argument("--out-ncgr")
    args = parser.parse_args(argv)

    img, _, _ = render(Path(args.ncgr), Path(args.nclr), Path(args.ncer))
    if args.render_out:
        Path(args.render_out).parent.mkdir(parents=True, exist_ok=True)
        img.save(args.render_out)
    if args.draw_start_out or args.out_ncgr:
        edited = draw_start(img)
        if args.draw_start_out:
            Path(args.draw_start_out).parent.mkdir(parents=True, exist_ok=True)
            edited.save(args.draw_start_out)
            preview = Path(args.draw_start_out).with_name(Path(args.draw_start_out).stem + "_12x.png")
            edited.convert("RGB").resize((edited.width * 12, edited.height * 12), Image.Resampling.NEAREST).save(preview)
        if args.out_ncgr:
            write_back(Path(args.ncgr), Path(args.nclr), Path(args.ncer), edited, Path(args.out_ncgr))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
