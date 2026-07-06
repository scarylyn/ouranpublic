#!/usr/bin/env python3
"""Render simple Nintendo DS Nitro NCGR/NCLR/NSCR/NCER assets.

This produces composed screen images from tile graphics, palettes, and screen
maps (NSCR backgrounds) or cell/sprite banks (NCER, e.g. UI buttons, icons,
and other OBJ-based art). These PNGs are the right inputs for art review or
image-editing tools; raw NCGR tile sheets are usually not arranged the way
the player sees them.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from PIL import Image


def u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def bgr555_to_rgb(value: int) -> tuple[int, int, int]:
    r = (value & 0x1F) * 255 // 31
    g = ((value >> 5) & 0x1F) * 255 // 31
    b = ((value >> 10) & 0x1F) * 255 // 31
    return r, g, b


def read_nclr(path: Path) -> list[tuple[int, int, int]]:
    data = path.read_bytes()
    if data[:4] != b"RLCN" or data[0x10:0x14] != b"TTLP":
        raise ValueError(f"not a supported NCLR: {path}")
    palette_size = u32(data, 0x20)
    palette_offset = 0x28
    return [
        bgr555_to_rgb(u16(data, palette_offset + i))
        for i in range(0, palette_size, 2)
    ]


def read_ncgr(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:4] != b"RGCN" or data[0x10:0x14] != b"RAHC":
        raise ValueError(f"not a supported NCGR: {path}")
    char_size = u32(data, 0x28)
    char_offset = 0x18 + u32(data, 0x2C)
    if char_offset + char_size > len(data):
        raise ValueError(f"NCGR character data points past EOF: {path}")
    return data[char_offset:char_offset + char_size]


def read_nscr(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:4] != b"RCSN" or data[0x10:0x14] != b"NRCS":
        raise ValueError(f"not a supported NSCR: {path}")
    width = u16(data, 0x18)
    height = u16(data, 0x1A)
    map_size = u32(data, 0x20)
    map_offset = 0x24
    if map_offset + map_size > len(data):
        raise ValueError(f"NSCR map data points past EOF: {path}")
    return width, height, data[map_offset:map_offset + map_size]


def render_nscr(ncgr: Path, nclr: Path, nscr: Path) -> Image.Image:
    tile_data = read_ncgr(ncgr)
    palette = read_nclr(nclr)
    width, height, screen = read_nscr(nscr)
    if width % 8 or height % 8:
        raise ValueError(f"screen size is not tile-aligned: {width}x{height}")
    tiles_x = width // 8
    tiles_y = height // 8
    if len(screen) < tiles_x * tiles_y * 2:
        raise ValueError("screen map is shorter than the declared dimensions")

    img = Image.new("P", (width, height), 0)
    flat_palette: list[int] = []
    for r, g, b in palette[:256]:
        flat_palette.extend([r, g, b])
    flat_palette.extend([0] * (768 - len(flat_palette)))
    img.putpalette(flat_palette)
    px = img.load()

    screen_entries = [
        u16(screen, i * 2)
        for i in range(tiles_x * tiles_y)
    ]
    max_tile = max((entry & 0x03FF) for entry in screen_entries) if screen_entries else 0
    if len(tile_data) % 64 == 0 and max_tile < len(tile_data) // 64 and len(palette) >= 256:
        bits_per_pixel = 8
        tile_size = 64
    elif len(tile_data) % 32 == 0 and max_tile < len(tile_data) // 32:
        bits_per_pixel = 4
        tile_size = 32
    else:
        raise ValueError("could not match NCGR tile data size to NSCR tile references")
    tile_count = len(tile_data) // tile_size
    for map_y in range(tiles_y):
        for map_x in range(tiles_x):
            entry = screen_entries[map_y * tiles_x + map_x]
            tile_index = entry & 0x03FF
            hflip = bool(entry & 0x0400)
            vflip = bool(entry & 0x0800)
            palette_bank = (entry >> 12) & 0x0F
            if tile_index >= tile_count:
                continue
            base = tile_index * tile_size
            for y in range(8):
                sy = 7 - y if vflip else y
                if bits_per_pixel == 8:
                    for sx in range(8):
                        color = tile_data[base + sy * 8 + sx]
                        dx = 7 - sx if hflip else sx
                        px[map_x * 8 + dx, map_y * 8 + y] = color % 256
                else:
                    for x_pair in range(4):
                        byte = tile_data[base + sy * 4 + x_pair]
                        values = (byte & 0x0F, byte >> 4)
                        for half, color in enumerate(values):
                            sx = x_pair * 2 + half
                            dx = 7 - sx if hflip else sx
                            px[map_x * 8 + dx, map_y * 8 + y] = (palette_bank * 16 + color) % 256
    return img


_KIND_FOLDERS = ("NSCR", "NCER", "NANR", "NCGR", "NCLR")


def matching_file(source_path: Path, suffix: str) -> Path | None:
    stem = source_path.stem
    candidates = [source_path.with_suffix(suffix)]
    parts = list(source_path.parts)
    for kind in _KIND_FOLDERS:
        if kind in parts:
            idx = parts.index(kind)
            for folder in ("NCGR", "NCLR"):
                folder_parts = parts[:]
                folder_parts[idx] = folder
                candidates.append(Path(*folder_parts).with_suffix(suffix))
            break
    for candidate in candidates:
        if candidate.exists():
            return candidate
    parent = (
        source_path.parent.parent
        if source_path.parent.name.upper() in _KIND_FOLDERS
        else source_path.parent
    )
    found = sorted(parent.rglob(stem + suffix))
    return found[0] if found else None


def render_one(nscr: Path, out_png: Path, ncgr: Path | None = None, nclr: Path | None = None) -> dict[str, str]:
    ncgr = ncgr or matching_file(nscr, ".NCGR")
    nclr = nclr or matching_file(nscr, ".NCLR")
    if not ncgr:
        raise FileNotFoundError(f"no matching NCGR found for {nscr}")
    if not nclr:
        raise FileNotFoundError(f"no matching NCLR found for {nscr}")
    img = render_nscr(ncgr, nclr, nscr)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return {
        "nscr": str(nscr),
        "ncgr": str(ncgr),
        "nclr": str(nclr),
        "png": str(out_png),
        "size": f"{img.size[0]}x{img.size[1]}",
    }


# OBJ shape+size -> (width, height) in pixels, per the NDS/GBA OAM spec.
_OBJ_SIZE_TABLE = {
    (0, 0): (8, 8), (0, 1): (16, 16), (0, 2): (32, 32), (0, 3): (64, 64),
    (1, 0): (16, 8), (1, 1): (32, 8), (1, 2): (32, 16), (1, 3): (64, 32),
    (2, 0): (8, 16), (2, 1): (8, 32), (2, 2): (16, 32), (2, 3): (32, 64),
}


def _signed(value: int, bits: int) -> int:
    span = 1 << bits
    if value & (span >> 1):
        return value - span
    return value


def decode_oam(attr0: int, attr1: int, attr2: int) -> dict | None:
    rotation = bool(attr0 & 0x0100)
    double_or_disable = bool(attr0 & 0x0200)
    if not rotation and double_or_disable:
        return None  # OBJ disabled
    shape = (attr0 >> 14) & 0x3
    size = (attr1 >> 14) & 0x3
    dims = _OBJ_SIZE_TABLE.get((shape, size))
    if dims is None:
        return None
    return {
        "y": _signed(attr0 & 0xFF, 8),
        "x": _signed(attr1 & 0x1FF, 9),
        "width": dims[0],
        "height": dims[1],
        "bpp": 8 if attr0 & 0x2000 else 4,
        "hflip": bool(not rotation and attr1 & 0x1000),
        "vflip": bool(not rotation and attr1 & 0x2000),
        "rotation": rotation,
        "tile_index": attr2 & 0x03FF,
        "palette_bank": (attr2 >> 12) & 0xF,
    }


def read_ncer(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] != b"RECN":
        raise ValueError(f"not a supported NCER: {path}")
    block = 0x10
    if data[block:block + 4] != b"KBEC":
        raise ValueError(f"NCER missing CEBK block: {path}")
    num_cells = u16(data, block + 8)
    extended = bool(u16(data, block + 10))
    cell_data_offset = u32(data, block + 12)
    mapping_type = u32(data, block + 16)
    entry_size = 16 if extended else 8
    cell_array_start = block + 8 + cell_data_offset
    oam_array_start = cell_array_start + num_cells * entry_size

    cells: list[list[dict]] = []
    for i in range(num_cells):
        entry_off = cell_array_start + i * entry_size
        num_oam = u16(data, entry_off)
        oam_offset = u32(data, entry_off + 4)
        oams: list[dict] = []
        for j in range(num_oam):
            oam_off = oam_array_start + oam_offset + j * 6
            attr0 = u16(data, oam_off)
            attr1 = u16(data, oam_off + 2)
            attr2 = u16(data, oam_off + 4)
            decoded = decode_oam(attr0, attr1, attr2)
            if decoded:
                oams.append(decoded)
        cells.append(oams)
    return {"mapping_type": mapping_type, "cells": cells}


def render_cell(
    tile_data: bytes,
    palette: list[tuple[int, int, int]],
    oams: list[dict],
    mapping_type: int = 0,
) -> Image.Image | None:
    if not oams:
        return None
    # NCER 1D OBJ tile addressing scales the tile-index unit by a per-bank
    # boundary (empirically 32 << mapping_type across this game's files;
    # sub-tiles within one OBJ stay packed at the normal 32/64-byte stride).
    boundary_bytes = 32 << mapping_type
    min_x = min(o["x"] for o in oams)
    min_y = min(o["y"] for o in oams)
    max_x = max(o["x"] + o["width"] for o in oams)
    max_y = max(o["y"] + o["height"] for o in oams)
    width, height = max_x - min_x, max_y - min_y
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = img.load()

    for oam in oams:
        tiles_x = oam["width"] // 8
        tiles_y = oam["height"] // 8
        tile_size = 32 if oam["bpp"] == 4 else 64
        ox = oam["x"] - min_x
        oy = oam["y"] - min_y
        obj_base = oam["tile_index"] * boundary_bytes
        for row in range(tiles_y):
            for col in range(tiles_x):
                base = obj_base + (row * tiles_x + col) * tile_size
                if base + tile_size > len(tile_data):
                    continue
                dst_col = (tiles_x - 1 - col) if oam["hflip"] else col
                dst_row = (tiles_y - 1 - row) if oam["vflip"] else row
                for y in range(8):
                    sy = 7 - y if oam["vflip"] else y
                    if oam["bpp"] == 8:
                        for sx in range(8):
                            color = tile_data[base + sy * 8 + sx]
                            if color == 0:
                                continue
                            dx = 7 - sx if oam["hflip"] else sx
                            r, g, b = palette[color % len(palette)]
                            px[ox + dst_col * 8 + dx, oy + dst_row * 8 + y] = (r, g, b, 255)
                    else:
                        for x_pair in range(4):
                            byte = tile_data[base + sy * 4 + x_pair]
                            for half, color in enumerate((byte & 0x0F, byte >> 4)):
                                if color == 0:
                                    continue
                                sx = x_pair * 2 + half
                                dx = 7 - sx if oam["hflip"] else sx
                                idx = oam["palette_bank"] * 16 + color
                                r, g, b = palette[idx % len(palette)]
                                px[ox + dst_col * 8 + dx, oy + dst_row * 8 + y] = (r, g, b, 255)
    return img


def render_ncer_one(ncer: Path, out_dir: Path, ncgr: Path | None = None, nclr: Path | None = None) -> dict[str, str]:
    ncgr = ncgr or matching_file(ncer, ".NCGR")
    nclr = nclr or matching_file(ncer, ".NCLR")
    if not ncgr:
        raise FileNotFoundError(f"no matching NCGR found for {ncer}")
    if not nclr:
        raise FileNotFoundError(f"no matching NCLR found for {ncer}")
    tile_data = read_ncgr(ncgr)
    palette = read_nclr(nclr)
    bank = read_ncer(ncer)

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = ncer.stem
    rendered: list[Image.Image] = []
    for i, oams in enumerate(bank["cells"]):
        img = render_cell(tile_data, palette, oams, bank["mapping_type"])
        if img is None:
            continue
        img.save(out_dir / f"{stem}_cell{i:02d}.png")
        rendered.append(img)

    if rendered:
        pad = 4
        sheet_w = sum(im.width for im in rendered) + pad * (len(rendered) + 1)
        sheet_h = max(im.height for im in rendered) + pad * 2
        sheet = Image.new("RGBA", (sheet_w, sheet_h), (32, 32, 32, 255))
        x = pad
        for im in rendered:
            sheet.paste(im, (x, pad), im)
            x += im.width + pad
        sheet.save(out_dir / f"{stem}_sheet.png")

    return {
        "ncer": str(ncer),
        "ncgr": str(ncgr),
        "nclr": str(nclr),
        "cells": str(len(bank["cells"])),
        "rendered": str(len(rendered)),
    }


def render_all_ncer(data_root: Path, out_dir: Path) -> None:
    rows: list[dict[str, str]] = []
    for ncer in sorted(data_root.rglob("*.NCER")):
        rel = ncer.relative_to(data_root)
        target_dir = out_dir / rel.parent / rel.stem
        try:
            row = render_ncer_one(ncer, target_dir)
            rows.append(row)
            print(f"rendered {rel} -> {target_dir} ({row['rendered']}/{row['cells']} cells)")
        except Exception as exc:
            rows.append({"ncer": str(ncer), "error": str(exc)})
            print(f"FAILED {rel}: {exc}")
    manifest = out_dir / "manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ncer", "ncgr", "nclr", "cells", "rendered", "error"]
    with manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {manifest} rows={len(rows)}")


def render_all(data_root: Path, out_dir: Path) -> None:
    rows: list[dict[str, str]] = []
    for nscr in sorted(data_root.rglob("*.NSCR")):
        rel = nscr.relative_to(data_root)
        out_png = out_dir / rel.with_suffix(".png")
        try:
            row = render_one(nscr, out_png)
            rows.append(row)
            print(f"rendered {rel} -> {out_png}")
        except Exception as exc:
            rows.append({"nscr": str(nscr), "png": str(out_png), "error": str(exc)})
            print(f"FAILED {rel}: {exc}")
    manifest = out_dir / "manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = ["nscr", "ncgr", "nclr", "png", "size", "error"]
    with manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {manifest} rows={len(rows)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("render-nscr")
    p.add_argument("nscr")
    p.add_argument("out_png")
    p.add_argument("--ncgr")
    p.add_argument("--nclr")

    p = sub.add_parser("render-all-nscr")
    p.add_argument("data_root")
    p.add_argument("out_dir")

    p = sub.add_parser("render-ncer")
    p.add_argument("ncer")
    p.add_argument("out_dir")
    p.add_argument("--ncgr")
    p.add_argument("--nclr")

    p = sub.add_parser("render-all-ncer")
    p.add_argument("data_root")
    p.add_argument("out_dir")

    args = parser.parse_args(argv)
    if args.cmd == "render-nscr":
        render_one(
            Path(args.nscr),
            Path(args.out_png),
            Path(args.ncgr) if args.ncgr else None,
            Path(args.nclr) if args.nclr else None,
        )
    elif args.cmd == "render-all-nscr":
        render_all(Path(args.data_root), Path(args.out_dir))
    elif args.cmd == "render-ncer":
        render_ncer_one(
            Path(args.ncer),
            Path(args.out_dir),
            Path(args.ncgr) if args.ncgr else None,
            Path(args.nclr) if args.nclr else None,
        )
    elif args.cmd == "render-all-ncer":
        render_all_ncer(Path(args.data_root), Path(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
