#!/usr/bin/env python3
"""Apply manually reviewed layout fixes from JSONL.

Input JSONL format:
  {"file":"101_1_1.json","ids":[658,659,660],"en":"Short English line."}

The tool wraps `en` to 32x3, writes it to the first pointer in `ids`, blanks
continuation pointers with `_force_empty`, and refuses anything that does not
fit.
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

ENCODING = "shiftjis"
WIDTH = 32
MAX_LINES = 3


def wrap_checked(text: str, width: int, max_lines: int) -> str:
    normalized = " ".join((text or "").split())
    lines = textwrap.wrap(
        normalized,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    if len(lines) > max_lines:
        raise ValueError(f"too many lines: {len(lines)}>{max_lines}: {normalized!r}")
    too_long = [line for line in lines if len(line) > width]
    if too_long:
        raise ValueError(f"line too long: {too_long[0]!r}")
    return "\n".join(lines)


def load(path: Path) -> dict:
    with path.open(encoding=ENCODING) as f:
        return json.load(f)


def save(path: Path, data: dict) -> None:
    with path.open("w", encoding=ENCODING) as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_dir")
    parser.add_argument("fixes_jsonl")
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    json_dir = Path(args.json_dir)
    by_file: dict[str, list[dict]] = {}
    with Path(args.fixes_jsonl).open(encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            rec = json.loads(line)
            if "id" in rec and "ids" not in rec:
                rec["ids"] = [int(part) for part in str(rec["id"]).split(",")]
            rec["ids"] = [int(i) for i in rec["ids"]]
            rec["_line"] = ln
            by_file.setdefault(rec["file"], []).append(rec)

    changed = 0
    for name, fixes in sorted(by_file.items()):
        path = json_dir / name
        data = load(path)
        pointers = data["pointers"]
        for rec in fixes:
            ids = rec["ids"]
            wrapped = wrap_checked(rec["en"], args.width, args.max_lines)
            for pos, idx in enumerate(ids):
                pointer = pointers[idx]
                pointer["New Text"] = wrapped if pos == 0 else ""
                if pos == 0:
                    pointer.pop("_force_empty", None)
                else:
                    pointer["_force_empty"] = True
                if "MT Text" in pointer:
                    pointer["MT Text"] = pointer["New Text"]
                pointer["Status"] = "ai"
                pointer["Note"] = rec.get("note", "manual layout fix")
            changed += 1
            print(f"{name} {','.join(map(str, ids))}: {wrapped!r}")
        if fixes and not args.dry_run:
            save(path, data)

    print(f"applied={changed} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
