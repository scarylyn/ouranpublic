#!/usr/bin/env python3
"""Show backend-tagged translation progress for a JSON folder."""

import argparse
import glob
import json
import os
import time


def has_japanese(text):
    return any(0x3040 <= ord(ch) <= 0x30FF or 0x4E00 <= ord(ch) <= 0x9FFF
               or 0xFF66 <= ord(ch) <= 0xFF9D for ch in text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Report translation backend progress")
    parser.add_argument("dir", nargs="?", default="translated_sergio")
    parser.add_argument("--backend", default="sugoi-local")
    args = parser.parse_args(argv)

    tagged = total = 0
    rows = []
    skipped = []
    for path in sorted(glob.glob(os.path.join(args.dir, "*.json"))):
        file_tagged = file_total = 0
        data = None
        for attempt in range(5):
            try:
                data = json.load(open(path, encoding="shiftjis"))
                break
            except json.JSONDecodeError:
                time.sleep(0.2 * (attempt + 1))
        if data is None:
            skipped.append(os.path.basename(path))
            continue
        for pointer in data["pointers"]:
            if has_japanese(pointer.get("Original Text", "")):
                total += 1
                file_total += 1
                if pointer.get("Backend") == args.backend:
                    tagged += 1
                    file_tagged += 1
        if file_total:
            rows.append((os.path.basename(path), file_tagged, file_total))

    pct = tagged / total * 100 if total else 100
    print(f"{args.backend}: {tagged}/{total} ({pct:.1f}%)")
    for name, file_tagged, file_total in rows:
        if file_tagged and file_tagged < file_total:
            print(f"  active/partial: {name} {file_tagged}/{file_total}")
        elif file_tagged == file_total:
            print(f"  done: {name} {file_tagged}/{file_total}")
    if skipped:
        print("  skipped unreadable while being written: " + ", ".join(skipped))


if __name__ == "__main__":
    main()
