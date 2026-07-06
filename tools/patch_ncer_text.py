#!/usr/bin/env python3
"""Redraw translated English text into NCER sprite cells (UI buttons/labels).

This does NOT touch the palette or tile addressing scheme discovered in
nitro_render.py: it decodes the target cell's OAM tile data, flat-fills each
OAM's own tile region with its sampled background color, draws the English
replacement text on top quantized to the nearest existing palette entries,
and repacks the tile bytes back into a copy of the source NCGR. Only the
byte ranges used by the patched OAMs are touched; everything else in the
NCGR (header, other tiles/cells sharing the file) is left byte-identical.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from nitro_render import (  # noqa: E402
    read_ncer, read_ncgr, read_nclr, matching_file, render_cell, u32,
)

FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def nearest_palette_index(rgb: tuple[int, int, int], palette: list[tuple[int, int, int]], bank_start: int, bank_size: int) -> int:
    best_i, best_d = 0, None
    for i in range(bank_start, min(bank_start + bank_size, len(palette))):
        pr, pg, pb = palette[i]
        d = (pr - rgb[0]) ** 2 + (pg - rgb[1]) ** 2 + (pb - rgb[2]) ** 2
        if best_d is None or d < best_d:
            best_d, best_i = d, i
    return best_i


def cluster_oams(oams: list[dict], n: int) -> list[list[dict]]:
    """Split OAMs into n left-to-right groups by the largest x gaps."""
    ordered = sorted(oams, key=lambda o: o["x"])
    if n <= 1 or len(ordered) <= n:
        # not enough OAMs to split meaningfully; fall back to even chunks
        chunk = max(1, len(ordered) // n)
        return [ordered[i:i + chunk] for i in range(0, len(ordered), chunk)][:n] or [ordered]
    gaps = []
    for i in range(1, len(ordered)):
        gap = ordered[i]["x"] - (ordered[i - 1]["x"] + ordered[i - 1]["width"])
        gaps.append((gap, i))
    gaps.sort(reverse=True)
    cut_points = sorted(idx for _, idx in gaps[: n - 1])
    groups, start = [], 0
    for cp in cut_points:
        groups.append(ordered[start:cp])
        start = cp
    groups.append(ordered[start:])
    return groups


def region_bbox(oams: list[dict]) -> tuple[int, int, int, int]:
    min_x = min(o["x"] for o in oams)
    min_y = min(o["y"] for o in oams)
    max_x = max(o["x"] + o["width"] for o in oams)
    max_y = max(o["y"] + o["height"] for o in oams)
    return min_x, min_y, max_x, max_y


def _patch_mode(cell_img: Image.Image, cx: int, cy: int, radius: int, x0: int, y0: int, x1: int, y1: int) -> Counter:
    counts = Counter()
    for yy in range(max(y0, cy - radius), min(y1, cy + radius + 1)):
        for xx in range(max(x0, cx - radius), min(x1, cx + radius + 1)):
            px = cell_img.getpixel((xx, yy))
            if len(px) == 4 and px[3] == 0:
                continue
            counts[px[:3]] += 1
    return counts


def sample_colors(cell_img: Image.Image, oams: list[dict], min_x: int, min_y: int) -> tuple[tuple, tuple]:
    """Return (background_rgb, text_rgb) sampled from the rendered region.

    Many of this game's buttons have a decorative border running the full
    perimeter (not just corners), so sampling the outer edge picks up border
    color, not fill color. Instead: sample small patches inset from the
    edges at the left/right-middle (background, between border and centered
    text) and at dead-center (text, since labels are centered).
    """
    x0 = min(o["x"] for o in oams) - min_x
    y0 = min(o["y"] for o in oams) - min_y
    x1 = max(o["x"] + o["width"] for o in oams) - min_x
    y1 = max(o["y"] + o["height"] for o in oams) - min_y
    w, h = x1 - x0, y1 - y0
    inset = max(1, min(w, h) // 6)
    radius = max(1, min(w, h) // 8)

    bg_counts = Counter()
    for cx, cy in [(x0 + inset, y0 + h // 2), (x1 - 1 - inset, y0 + h // 2)]:
        bg_counts += _patch_mode(cell_img, cx, cy, radius, x0, y0, x1, y1)
    if not bg_counts:
        bg_counts = _patch_mode(cell_img, x0 + w // 2, y0 + h // 2, max(w, h), x0, y0, x1, y1)
    bg = bg_counts.most_common(1)[0][0]

    def brightness(c):
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

    bg_b = brightness(bg)
    center_counts = _patch_mode(cell_img, x0 + w // 2, y0 + h // 2, max(radius, min(w, h) // 3), x0, y0, x1, y1)
    fg_candidates = [c for c, n in center_counts.most_common(8) if c != bg]
    fg = max(fg_candidates, key=lambda c: abs(brightness(c) - bg_b)) if fg_candidates else (
        (255, 255, 255) if bg_b < 128 else (0, 0, 0)
    )
    return bg, fg


MIN_FONT_SIZE = 5


def restrict_to_text_oams(cell_img: Image.Image, oams: list[dict], min_x: int, min_y: int) -> list[dict]:
    """Some cells combine a big decorative frame with a small inline text area
    as one set of OAMs (e.g. a dialog box with a 2-line message baked in the
    middle). Blindly replacing every OAM stretches the new text across the
    whole frame and corrupts the border. Detect this by finding the tight
    pixel bbox of the sampled foreground color and keeping only the OAMs
    that actually overlap it; if the text already spans ~the whole area
    (the common case: a plain button), this is a no-op.
    """
    bg, fg = sample_colors(cell_img, oams, min_x, min_y)
    full_x0 = min(o["x"] for o in oams) - min_x
    full_y0 = min(o["y"] for o in oams) - min_y
    full_x1 = max(o["x"] + o["width"] for o in oams) - min_x
    full_y1 = max(o["y"] + o["height"] for o in oams) - min_y
    full_area = (full_x1 - full_x0) * (full_y1 - full_y0)

    def close(a, b, tol=40):
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 <= tol

    xs, ys = [], []
    for x in range(full_x0, full_x1):
        for y in range(full_y0, full_y1):
            px = cell_img.getpixel((x, y))
            if len(px) == 4 and px[3] == 0:
                continue
            if close(px[:3], fg):
                xs.append(x)
                ys.append(y)
    if not xs:
        return oams
    tx0, tx1 = min(xs), max(xs) + 1
    ty0, ty1 = min(ys), max(ys) + 1
    text_area = (tx1 - tx0) * (ty1 - ty0)
    if text_area >= 0.6 * full_area:
        return oams  # no separate frame detected; treat whole cell as text

    kept = []
    for o in oams:
        ox0, oy0 = o["x"] - min_x, o["y"] - min_y
        ox1, oy1 = ox0 + o["width"], oy0 + o["height"]
        ix = max(0, min(ox1, tx1) - max(ox0, tx0))
        iy = max(0, min(oy1, ty1) - max(oy0, ty0))
        overlap = ix * iy
        if overlap >= 0.3 * (o["width"] * o["height"]):
            kept.append(o)
    return kept or oams


def fit_font(text: str, max_w: int, max_h: int) -> tuple[ImageFont.FreeTypeFont, str]:
    """Shrink to fit; if still too wide at the minimum size, truncate the text."""
    size = max_h
    font = ImageFont.truetype(FONT_PATH, max(size, MIN_FONT_SIZE))
    while size > MIN_FONT_SIZE:
        font = ImageFont.truetype(FONT_PATH, size)
        bbox = font.getbbox(text)
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if w <= max_w and h <= max_h:
            return font, text
        size -= 1
    font = ImageFont.truetype(FONT_PATH, MIN_FONT_SIZE)
    truncated = text
    while len(truncated) > 1 and font.getbbox(truncated)[2] > max_w:
        truncated = truncated[:-1]
    return font, truncated


def render_region_pixels(text: str, width: int, height: int, bg: tuple, fg: tuple) -> Image.Image:
    canvas = Image.new("RGB", (width, height), bg)
    font, text = fit_font(text, width - 2, height - 1)
    draw = ImageDraw.Draw(canvas)
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = max(0, (width - tw) // 2) - bbox[0]
    y = max(0, (height - th) // 2) - bbox[1]
    draw.text((x, y), text, font=font, fill=fg)
    return canvas


def patch_ncgr_bytes(tile_data: bytearray, oams: list[dict], region_img: Image.Image,
                      min_x: int, min_y: int, palette: list[tuple[int, int, int]],
                      mapping_type: int) -> None:
    boundary_bytes = 32 << mapping_type
    for oam in oams:
        tiles_x = oam["width"] // 8
        tiles_y = oam["height"] // 8
        tile_size = 32 if oam["bpp"] == 4 else 64
        bank_start = 0 if oam["bpp"] == 8 else oam["palette_bank"] * 16
        bank_size = 256 if oam["bpp"] == 8 else 16
        obj_base = oam["tile_index"] * boundary_bytes
        ox, oy = oam["x"] - min_x, oam["y"] - min_y
        for row in range(tiles_y):
            for col in range(tiles_x):
                base = obj_base + (row * tiles_x + col) * tile_size
                if base + tile_size > len(tile_data):
                    continue
                dst_col = (tiles_x - 1 - col) if oam["hflip"] else col
                dst_row = (tiles_y - 1 - row) if oam["vflip"] else row
                for y in range(8):
                    sy = 7 - y if oam["vflip"] else y
                    row_indices = []
                    for x in range(8):
                        dx = 7 - x if oam["hflip"] else x
                        px = region_img.getpixel((ox + dst_col * 8 + dx, oy + dst_row * 8 + y))
                        idx = nearest_palette_index(px, palette, bank_start, bank_size)
                        row_indices.append(idx if oam["bpp"] == 8 else idx % 16)
                    if oam["bpp"] == 8:
                        for x in range(8):
                            tile_data[base + sy * 8 + x] = row_indices[x]
                    else:
                        for x_pair in range(4):
                            lo, hi = row_indices[x_pair * 2], row_indices[x_pair * 2 + 1]
                            tile_data[base + sy * 4 + x_pair] = (lo & 0x0F) | ((hi & 0x0F) << 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data_root", help="Game Files/data root")
    ap.add_argument("manifest", help="ui_text_cells.json")
    ap.add_argument("translations", nargs="+", help="ui_strings_translated.json ui_names_translated.json ...")
    ap.add_argument("out_dir", help="output dir for patched NCGR + comparison PNGs")
    args = ap.parse_args()

    data_root = Path(args.data_root)
    out_dir = Path(args.out_dir)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))

    en_by_jp, en_by_name = {}, {}
    for tpath in args.translations:
        for entry in json.loads(Path(tpath).read_text(encoding="utf-8")):
            if "jp" in entry:
                en_by_jp[entry["jp"]] = entry["en"]
            elif "jp_name" in entry:
                en_by_name[entry["jp_name"]] = entry["en"]

    by_ncer: dict[str, list[dict]] = {}
    for entry in manifest:
        by_ncer.setdefault(entry["ncer"], []).append(entry)

    for rel, entries in sorted(by_ncer.items()):
        ncer_path = data_root / rel
        ncgr_path = matching_file(ncer_path, ".NCGR")
        nclr_path = matching_file(ncer_path, ".NCLR")
        if not ncgr_path or not nclr_path:
            print(f"SKIP {rel}: missing NCGR/NCLR")
            continue

        bank = read_ncer(ncer_path)
        palette = read_nclr(nclr_path)
        tile_data = bytearray(read_ncgr(ncgr_path))
        raw = ncgr_path.read_bytes()
        char_offset = 0x18 + u32(raw, 0x2C)

        stem_out = out_dir / rel
        stem_out.parent.mkdir(parents=True, exist_ok=True)
        before_dir = stem_out.parent / f"{ncer_path.stem}_before"
        after_dir = stem_out.parent / f"{ncer_path.stem}_after"
        before_dir.mkdir(parents=True, exist_ok=True)
        after_dir.mkdir(parents=True, exist_ok=True)

        touched_cells = set()
        for entry in entries:
            for cell_idx in entry["cells"]:
                oams = bank["cells"][cell_idx]
                if not oams:
                    print(f"  WARN {rel} cell{cell_idx}: no OAMs")
                    continue
                cell_img = render_cell(bytes(tile_data), palette, oams, bank["mapping_type"])
                cell_img_orig = cell_img.copy()
                min_x = min(o["x"] for o in oams)
                min_y = min(o["y"] for o in oams)
                oams = restrict_to_text_oams(cell_img_orig, oams, min_x, min_y)

                if "jp_multi" in entry:
                    groups = cluster_oams(oams, len(entry["jp_multi"]))
                    labels = [en_by_jp.get(jp, jp) for jp in entry["jp_multi"]]
                elif "jp_name" in entry:
                    groups = [oams]
                    labels = [en_by_name.get(entry["jp_name"], entry["jp_name"])]
                else:
                    groups = [oams]
                    labels = [en_by_jp.get(entry["jp"], entry["jp"])]

                for group, label in zip(groups, labels):
                    gx0, gy0, gx1, gy1 = region_bbox(group)
                    bg, fg = sample_colors(cell_img_orig, group, min_x, min_y)
                    region_img = render_region_pixels(label, gx1 - gx0, gy1 - gy0, bg, fg)
                    patch_ncgr_bytes(tile_data, group, region_img, gx0, gy0, palette, bank["mapping_type"])

                touched_cells.add(cell_idx)
                cell_img_orig.save(before_dir / f"cell{cell_idx:02d}.png")

        new_ncgr_bytes = bytearray(raw)
        new_ncgr_bytes[char_offset:char_offset + len(tile_data)] = tile_data
        out_ncgr = stem_out.with_name(ncgr_path.name)
        out_ncgr.write_bytes(bytes(new_ncgr_bytes))

        for cell_idx in sorted(touched_cells):
            oams = bank["cells"][cell_idx]
            img = render_cell(bytes(tile_data), palette, oams, bank["mapping_type"])
            if img:
                img.save(after_dir / f"cell{cell_idx:02d}.png")

        print(f"patched {rel}: {len(touched_cells)} cells -> {out_ncgr}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
