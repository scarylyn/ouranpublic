#!/usr/bin/env python3
"""Apply small #Scale[...] prefixes to layout-failing formatted groups.

Normal dialogue boxes render #Scale literally, so this tool must not be used
for ordinary `dialog-display` rows. It is retained only for formatted overlay
rows whose source text already uses script formatting codes.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import textwrap
from pathlib import Path

ENCODING = "shiftjis"
FORMAT_PREFIX = re.compile(r"^(?:#[A-Za-z]+\[[^\]]+\])+")
SCALES = [0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5]


def wrap_for_scale(text: str, scale: float) -> str | None:
    width = int(32 / scale)
    lines = textwrap.wrap(
        " ".join((text or "").split()),
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    if len(lines) > 3:
        return None
    if any(len(line) * scale > 32.01 for line in lines):
        return None
    return "\n".join(lines)


def choose_scaled(text: str, min_scale: float) -> tuple[float, str] | None:
    clean = FORMAT_PREFIX.sub("", text or "")
    for scale in SCALES:
        if scale < min_scale:
            continue
        wrapped = wrap_for_scale(clean, scale)
        if wrapped is not None:
            return scale, f"#Scale[{scale:g}]{wrapped}"
    return None


def load_json(path: Path) -> dict:
    with path.open(encoding=ENCODING) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding=ENCODING) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_dir")
    parser.add_argument("layout_qa_tsv")
    parser.add_argument("--min-scale", type=float, default=0.85)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rows = list(csv.DictReader(open(args.layout_qa_tsv, encoding="utf-8"), delimiter="\t"))
    by_file: dict[str, list[dict]] = {}
    for row in rows:
        if row.get("kind") != "formatted-overlay":
            continue
        by_file.setdefault(row["file"], []).append(row)

    changed = skipped = 0
    for name, file_rows in sorted(by_file.items()):
        path = Path(args.json_dir) / name
        data = load_json(path)
        pointers = data["pointers"]
        file_changed = False
        for row in file_rows:
            ids = [int(part) for part in row["id"].split(",")]
            chosen = choose_scaled(row["en"], args.min_scale)
            if not chosen:
                skipped += 1
                continue
            scale, scaled_text = chosen
            for pos, idx in enumerate(ids):
                pointer = pointers[idx]
                pointer["New Text"] = scaled_text if pos == 0 else ""
                if pos == 0:
                    pointer.pop("_force_empty", None)
                else:
                    pointer["_force_empty"] = True
                if "MT Text" in pointer:
                    pointer["MT Text"] = pointer["New Text"]
                pointer["Status"] = "ai"
                pointer["Note"] = f"layout scale fit {scale:g}"
            changed += 1
            file_changed = True
            print(f"{name} {row['id']} scale={scale:g}")
        if file_changed and not args.dry_run:
            save_json(path, data)

    print(f"changed={changed} skipped={skipped} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
