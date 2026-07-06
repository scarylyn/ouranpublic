#!/usr/bin/env python3
"""Build a temporary ROM that shows one target layout line near game start.

This copies the current wrapped build, injects a selected translated group into
an early prologue dialog group, patches only 101_1_1.bin, and repacks a separate
ROM at build/ouran-layout-test/ouran-layout-test.nds.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENCODING = "shiftjis"
SOURCE_JSON_DIR = ROOT / "translated_sergio_playable_wrapped"
BASE_BUILD = ROOT / "build/ouran-sergio-wrapped"
TEST_BUILD = ROOT / "build/ouran-layout-test"
BASE_BIN = ROOT / "Game Files/data/scr/bin/101_1_1.bin"
INJECT_IDS = [67, 68]
NDSTOOL = ROOT / "tools/bin/ndstool"

sys.path.insert(0, str(ROOT / "tools"))
from ouran_tool import insert  # noqa: E402


def ids_from(value: str) -> list[int]:
    return [int(part) for part in value.split(",") if part.strip()]


def strip_scale(text: str) -> str:
    # Pointer 30 is normal dialog. Keep #Scale for visual testing, but drop
    # overlay positioning/color codes if a formatted overlay row is tested.
    text = re.sub(r"#(?:Color|Pos)\[[^\]]+\]", "", text)
    return text


def current_group_text(file_name: str, ids: list[int]) -> str:
    path = SOURCE_JSON_DIR / file_name
    data = json.load(open(path, encoding=ENCODING))
    return " ".join(
        " ".join((data["pointers"][idx].get("New Text") or "").split())
        for idx in ids
        if (data["pointers"][idx].get("New Text") or "").strip()
    ).strip()


def prepare_build_dir() -> None:
    if TEST_BUILD.exists():
        shutil.rmtree(TEST_BUILD)
    shutil.copytree(BASE_BUILD, TEST_BUILD)


def make_test_json(text: str) -> Path:
    out_dir = TEST_BUILD / "_json"
    out_dir.mkdir(parents=True, exist_ok=True)
    data = json.load(open(SOURCE_JSON_DIR / "101_1_1.json", encoding=ENCODING))
    text = strip_scale(text)
    for pos, idx in enumerate(INJECT_IDS):
        pointer = data["pointers"][idx]
        pointer["New Text"] = text if pos == 0 else ""
        if pos == 0:
            pointer.pop("_force_empty", None)
        else:
            pointer["_force_empty"] = True
        pointer["Status"] = "ai"
        pointer["Note"] = "temporary layout test injection"
    out_path = out_dir / "101_1_1.json"
    json.dump(data, open(out_path, "w", encoding=ENCODING), ensure_ascii=False, indent=4)
    return out_path


def repack() -> Path:
    out_bin = TEST_BUILD / "data/scr/bin/101_1_1.bin"
    test_json = TEST_BUILD / "_json/101_1_1.json"
    insert(str(BASE_BIN), str(test_json), str(out_bin))
    out_rom = TEST_BUILD / "ouran-layout-test.nds"
    subprocess.run(
        [
            str(NDSTOOL),
            "-c",
            out_rom.name,
            "-9",
            "arm9.bin",
            "-7",
            "arm7.bin",
            "-y9",
            "y9.bin",
            "-y7",
            "y7.bin",
            "-d",
            "data",
            "-y",
            "overlay",
            "-t",
            "banner.bin",
            "-h",
            "header.bin",
        ],
        cwd=TEST_BUILD,
        check=True,
    )
    return out_rom


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="source JSON file, e.g. 101_1_1.json")
    parser.add_argument("--id", required=True, help="comma-separated pointer ids from QA")
    parser.add_argument("--text", help="literal text to inject instead of reading --file/--id")
    args = parser.parse_args(argv)

    text = args.text if args.text is not None else current_group_text(args.file, ids_from(args.id))
    if not text:
        raise SystemExit("target text is blank")
    prepare_build_dir()
    make_test_json(text)
    rom = repack()
    print(rom)
    print("Injected text:")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
