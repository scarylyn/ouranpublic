#!/usr/bin/env python3
"""Render ED_*.NCGR/NCLR graphics to PNG contact sheets for visual review.

This is a lightweight previewer for the ending graphics. It renders the raw
4bpp tiled NCGR data with the matching NCLR palette, laid out 16 tiles wide.
That is enough to identify which assets contain Japanese text before deciding
whether to redraw or subtitle them.
"""

import argparse
import math
import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError as exc:
    raise SystemExit("Pillow is required: .venv/bin/pip install pillow") from exc


def read_u32(data, offset):
    return int.from_bytes(data[offset:offset + 4], "little")


def bgr555_to_rgba(value):
    r = (value & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x1F) * 255 // 31
    b = ((value >> 10) & 0x1F) * 255 // 31
    return (r, g, b, 255)


def load_palette(nclr_path):
    data = Path(nclr_path).read_bytes()
    if data[:4] != b"RLCN":
        raise ValueError(f"not an NCLR file: {nclr_path}")
    palette_size = read_u32(data, 0x20)
    palette_offset = 0x28
    colors = []
    for i in range(0, palette_size, 2):
        colors.append(bgr555_to_rgba(int.from_bytes(data[palette_offset + i:palette_offset + i + 2], "little")))
    return colors[:16]


def load_tiles(ncgr_path):
    data = Path(ncgr_path).read_bytes()
    if data[:4] != b"RGCN":
        raise ValueError(f"not an NCGR file: {ncgr_path}")
    char_size = read_u32(data, 0x28)
    char_offset = read_u32(data, 0x2C)
    return data[char_offset:char_offset + char_size]


def render_ncgr(ncgr_path, nclr_path, tiles_wide=16, scale=2):
    palette = load_palette(nclr_path)
    tiles = load_tiles(ncgr_path)
    tile_count = len(tiles) // 32
    tiles_high = max(math.ceil(tile_count / tiles_wide), 1)
    img = Image.new("RGBA", (tiles_wide * 8, tiles_high * 8), palette[0])

    for tile_index in range(tile_count):
        tx = tile_index % tiles_wide
        ty = tile_index // tiles_wide
        tile = tiles[tile_index * 32:(tile_index + 1) * 32]
        for y in range(8):
            for x_pair in range(4):
                value = tile[y * 4 + x_pair]
                for half, color_index in enumerate((value & 0x0F, value >> 4)):
                    x = tx * 8 + x_pair * 2 + half
                    img.putpixel((x, ty * 8 + y), palette[color_index])

    if scale != 1:
        img = img.resize((img.width * scale, img.height * scale), Image.Resampling.NEAREST)
    return img


def export_images(ncgr_dir, nclr_dir, out_dir, pattern, tiles_wide, scale):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exported = []
    for ncgr in sorted(Path(ncgr_dir).glob(pattern)):
        nclr = Path(nclr_dir) / (ncgr.stem + ".NCLR")
        if not nclr.exists():
            continue
        img = render_ncgr(ncgr, nclr, tiles_wide=tiles_wide, scale=scale)
        out = out_dir / (ncgr.stem + ".png")
        img.save(out)
        exported.append(out)
        print(f"wrote {out}")
    return exported


def make_contact_sheet(images, out_path, thumb_width=256):
    loaded = []
    for path in images:
        img = Image.open(path).convert("RGBA")
        ratio = thumb_width / img.width
        thumb = img.resize((thumb_width, max(1, int(img.height * ratio))), Image.Resampling.NEAREST)
        loaded.append((path, thumb))
    if not loaded:
        return

    cols = 4
    label_h = 22
    cell_w = thumb_width
    cell_h = max(img.height for _, img in loaded) + label_h
    rows = math.ceil(len(loaded) / cols)
    sheet = Image.new("RGBA", (cols * cell_w, rows * cell_h), (245, 245, 248, 255))
    draw = ImageDraw.Draw(sheet)
    for idx, (path, img) in enumerate(loaded):
        x = (idx % cols) * cell_w
        y = (idx // cols) * cell_h
        sheet.alpha_composite(img, (x, y + label_h))
        draw.text((x + 4, y + 4), path.stem, fill=(20, 20, 24, 255))
    sheet.save(out_path)
    print(f"wrote {out_path}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export Ouran ED Nitro graphics previews")
    parser.add_argument("--ncgr-dir", default="Game Files/data/chr/NCGR")
    parser.add_argument("--nclr-dir", default="Game Files/data/chr/NCLR")
    parser.add_argument("--out-dir", default="asset_previews/ed")
    parser.add_argument("--pattern", default="ED_*.NCGR")
    parser.add_argument("--tiles-wide", type=int, default=16)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--sheet", default="asset_previews/ed_contact_sheet.png")
    args = parser.parse_args(argv)

    images = export_images(args.ncgr_dir, args.nclr_dir, args.out_dir, args.pattern, args.tiles_wide, args.scale)
    make_contact_sheet(images, args.sheet)


if __name__ == "__main__":
    main()
