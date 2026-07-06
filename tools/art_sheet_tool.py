#!/usr/bin/env python3
"""Export/import simple Nintendo DS NCGR/NCLR 4bpp tile sheets as PNG.

This is intended for art-localization review and simple round-trips:

  export-all  Game Files/data art_work/exported_sheets
  export      Game Files/data/bg/BG_SUB/TouchStartBG.NCGR out.png --nclr ...
  import      original.NCGR edited.png out.NCGR --nclr original.NCLR

The importer preserves the original NCGR header and tile count. It quantizes
edited pixels to the existing NCLR palette and writes tile data back in the
same sequential tile-sheet order used by export.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import shutil
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


def read_palette(nclr_path: Path) -> list[tuple[int, int, int]]:
    data = nclr_path.read_bytes()
    if data[:4] != b"RLCN":
        raise ValueError(f"not an NCLR file: {nclr_path}")
    palette_size = u32(data, 0x20)
    palette_offset = 0x28
    return [
        bgr555_to_rgb(int.from_bytes(data[palette_offset + i:palette_offset + i + 2], "little"))
        for i in range(0, palette_size, 2)
    ]


def ncgr_payload(data: bytes) -> tuple[int, int]:
    if data[:4] != b"RGCN":
        raise ValueError("not an NCGR file")
    char_size = u32(data, 0x28)
    char_offset = u32(data, 0x2C)
    if char_offset + char_size > len(data):
        raise ValueError("NCGR character data points past EOF")
    return char_offset, char_size


def tile_count_for(data_size: int) -> int:
    if data_size % 32:
        raise ValueError(f"4bpp tile data size is not divisible by 32: {data_size}")
    return data_size // 32


def default_sheet_width(tile_count: int) -> int:
    if tile_count <= 16:
        return tile_count
    return 32


def decode_tiles(tile_data: bytes, palette: list[tuple[int, int, int]], tiles_wide: int | None = None) -> Image.Image:
    tile_count = tile_count_for(len(tile_data))
    tiles_wide = tiles_wide or default_sheet_width(tile_count)
    tiles_high = math.ceil(tile_count / tiles_wide)
    img = Image.new("P", (tiles_wide * 8, tiles_high * 8), 0)
    flat_palette: list[int] = []
    for r, g, b in palette[:256]:
        flat_palette.extend([r, g, b])
    flat_palette.extend([0] * (768 - len(flat_palette)))
    img.putpalette(flat_palette)
    px = img.load()
    for tile_index in range(tile_count):
        ox = (tile_index % tiles_wide) * 8
        oy = (tile_index // tiles_wide) * 8
        base = tile_index * 32
        for y in range(8):
            for x_pair in range(4):
                byte = tile_data[base + y * 4 + x_pair]
                for half, idx in enumerate((byte & 0x0F, byte >> 4)):
                    x = x_pair * 2 + half
                    px[ox + x, oy + y] = idx % len(palette)
    return img


def nearest_palette_index(rgb: tuple[int, int, int], palette: list[tuple[int, int, int]]) -> int:
    r, g, b = rgb
    best_i = 0
    best_d = None
    for i, (pr, pg, pb) in enumerate(palette[:16]):
        d = (r - pr) * (r - pr) + (g - pg) * (g - pg) + (b - pb) * (b - pb)
        if best_d is None or d < best_d:
            best_i, best_d = i, d
    return best_i


def encode_tiles(img: Image.Image, tile_count: int, palette: list[tuple[int, int, int]], tiles_wide: int | None = None) -> bytes:
    tiles_wide = tiles_wide or default_sheet_width(tile_count)
    expected_h = math.ceil(tile_count / tiles_wide) * 8
    expected_w = tiles_wide * 8
    if img.size[0] < expected_w or img.size[1] < expected_h:
        raise ValueError(f"edited PNG is too small: {img.size}, expected at least {(expected_w, expected_h)}")
    if img.mode == "P":
        indexed = img
        palette_values = indexed.getpalette() or []
        source_palette = [
            tuple(palette_values[i:i + 3])
            for i in range(0, min(len(palette_values), 48), 3)
        ]
        direct_palette = source_palette[:16] == palette[:len(source_palette[:16])]
    else:
        indexed = None
        direct_palette = False
    rgb = img.convert("RGB")
    px = rgb.load()
    ipx = indexed.load() if indexed is not None else None
    out = bytearray(tile_count * 32)
    for tile_index in range(tile_count):
        ox = (tile_index % tiles_wide) * 8
        oy = (tile_index // tiles_wide) * 8
        base = tile_index * 32
        for y in range(8):
            for x_pair in range(4):
                if direct_palette and ipx is not None:
                    lo = int(ipx[ox + x_pair * 2, oy + y]) & 0x0F
                    hi = int(ipx[ox + x_pair * 2 + 1, oy + y]) & 0x0F
                else:
                    lo = nearest_palette_index(px[ox + x_pair * 2, oy + y], palette)
                    hi = nearest_palette_index(px[ox + x_pair * 2 + 1, oy + y], palette)
                out[base + y * 4 + x_pair] = lo | (hi << 4)
    return bytes(out)


def matching_nclr(ncgr_path: Path) -> Path | None:
    stem = ncgr_path.stem
    parts = list(ncgr_path.parts)
    candidates: list[Path] = []
    if "NCGR" in parts:
        parts[parts.index("NCGR")] = "NCLR"
        candidates.append(Path(*parts).with_suffix(".NCLR"))
    candidates.append(ncgr_path.with_suffix(".NCLR"))
    for c in candidates:
        if c.exists():
            return c
    parent = ncgr_path.parent.parent if ncgr_path.parent.name.upper() == "NCGR" else ncgr_path.parent
    found = sorted(parent.rglob(stem + ".NCLR"))
    return found[0] if found else None


def export_one(ncgr_path: Path, out_png: Path, nclr_path: Path | None = None, tiles_wide: int | None = None) -> dict:
    nclr_path = nclr_path or matching_nclr(ncgr_path)
    if not nclr_path:
        raise FileNotFoundError(f"no matching NCLR found for {ncgr_path}")
    ncgr = ncgr_path.read_bytes()
    char_offset, char_size = ncgr_payload(ncgr)
    palette = read_palette(nclr_path)
    img = decode_tiles(ncgr[char_offset:char_offset + char_size], palette, tiles_wide)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return {
        "ncgr": str(ncgr_path),
        "nclr": str(nclr_path),
        "png": str(out_png),
        "tiles": tile_count_for(char_size),
        "size": f"{img.size[0]}x{img.size[1]}",
    }


def import_one(ncgr_path: Path, edited_png: Path, out_ncgr: Path, nclr_path: Path | None = None, tiles_wide: int | None = None) -> None:
    nclr_path = nclr_path or matching_nclr(ncgr_path)
    if not nclr_path:
        raise FileNotFoundError(f"no matching NCLR found for {ncgr_path}")
    ncgr = bytearray(ncgr_path.read_bytes())
    char_offset, char_size = ncgr_payload(ncgr)
    palette = read_palette(nclr_path)
    tile_count = tile_count_for(char_size)
    tile_data = encode_tiles(Image.open(edited_png), tile_count, palette, tiles_wide)
    ncgr[char_offset:char_offset + char_size] = tile_data
    out_ncgr.parent.mkdir(parents=True, exist_ok=True)
    out_ncgr.write_bytes(ncgr)


def export_all(data_root: Path, out_dir: Path) -> None:
    rows = []
    for ncgr in sorted(data_root.rglob("*.NCGR")):
        nclr = matching_nclr(ncgr)
        if not nclr:
            continue
        rel = ncgr.relative_to(data_root)
        out = out_dir / rel.with_suffix(".png")
        try:
            row = export_one(ncgr, out, nclr)
            rows.append(row)
            print(f"exported {rel} -> {out}")
        except Exception as exc:
            rows.append({"ncgr": str(ncgr), "nclr": str(nclr), "png": str(out), "error": str(exc)})
            print(f"FAILED {rel}: {exc}")
    manifest = out_dir / "manifest.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ncgr", "nclr", "png", "tiles", "size", "error"]
    with manifest.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {manifest} rows={len(rows)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("export")
    p.add_argument("ncgr")
    p.add_argument("out_png")
    p.add_argument("--nclr")
    p.add_argument("--tiles-wide", type=int)

    p = sub.add_parser("import")
    p.add_argument("ncgr")
    p.add_argument("edited_png")
    p.add_argument("out_ncgr")
    p.add_argument("--nclr")
    p.add_argument("--tiles-wide", type=int)

    p = sub.add_parser("export-all")
    p.add_argument("data_root")
    p.add_argument("out_dir")

    args = parser.parse_args(argv)
    if args.cmd == "export":
        export_one(Path(args.ncgr), Path(args.out_png), Path(args.nclr) if args.nclr else None, args.tiles_wide)
    elif args.cmd == "import":
        import_one(Path(args.ncgr), Path(args.edited_png), Path(args.out_ncgr), Path(args.nclr) if args.nclr else None, args.tiles_wide)
    elif args.cmd == "export-all":
        if Path(args.out_dir).exists():
            shutil.rmtree(args.out_dir)
        export_all(Path(args.data_root), Path(args.out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
