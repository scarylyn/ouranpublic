#!/usr/bin/env python3
"""Ouran (and similar pointer-table NDS scripts) extract / insert toolkit.

This is a refactor of the original community extraction_script.py by jaga8285
(with thanks to JJJewel and azerty1). The binary format logic is preserved
verbatim -- it is verified to round-trip losslessly, including heavy English
expansion and offsets past the 0x7fff encoding boundary. What changed:

  * functions take explicit file paths instead of operating on the cwd basename
  * importable as a module (no auto-run menu); CLI is via argparse
  * insertion runs every string through sanitize.sanitize() so Shift-JIS-unsafe
    machine-translation output fails loudly on one string instead of corrupting
    a batch midway through
  * a built-in `selftest` proves the round-trip on any .bin

Binary format (per script .bin)
  bytes 0..3    reserved (00000000)
  bytes 4..7    text block start address  (textaddr)
  bytes 8..11   text block size           (size)        <- rewritten on insert
  bytes 12..19  reserved (8 bytes)
  bytes 20..23  code block start address  (codeaddr)
  ...           pointer table, each live pointer prefixed by 03 01
  textaddr..    Shift-JIS text block

Each pointer in the table encodes a Size (2 bytes) and an Offset (4 bytes, using
the game's quirky 15-bit 0x7fff scheme) into the text block.
"""

import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sanitize import sanitize  # noqa: E402

# opcode -> human label for the pointer's "Type" field
CODEDICT = {
    b"\x00\x3c": "Dialog",
    b"\x00\x3e": "Speaker",
    b"\x00\x39": "Choice",
    b"\x00\x46": "Chapter name",
    b"\x01\x04": "INVALID",
}

ENCODING = "shiftjis"


def int2bytes(num, size=2):
    """Encode an int into the game's little-endian / 15-bit-offset byte form.

    Preserved verbatim from the original tool. For size>2 the high half is
    scaled by 0x7fff (not 0x8000) -- unusual, but self-consistent with the
    decode in findPointers, so it round-trips."""
    result = bytearray(size)
    if size > 2:
        lastbytes = num // 0x7fff
        result[2] = lastbytes % 256
        result[3] = lastbytes // 256
    num = num % 0x7fff
    result[0] = num % 256
    result[1] = num // 256
    return result


# --------------------------------------------------------------------------- #
# EXTRACT
# --------------------------------------------------------------------------- #
def find_pointers(bin_path, json_path):
    """Scan the pointer table of `bin_path` and write the table to `json_path`."""
    pointers = []
    with open(bin_path, "rb") as fbin:
        fbin.read(4)
        textaddr = int.from_bytes(fbin.read(4), "little")
        size = int.from_bytes(fbin.read(4), "little")
        fbin.read(8)
        codeaddr = int.from_bytes(fbin.read(4), "little")

        while fbin.tell() < codeaddr:
            fbin.read(2)
        while fbin.tell() < textaddr:
            buffer = (fbin.read(1), fbin.read(1))
            peek = fbin.read(8)
            fbin.seek(-8, 1)
            if peek[0:1] == b"\x03" and peek[1:2] == b"\x01":
                scripttype = buffer[1] + buffer[0]
                bytescount = peek[3] * 256 + peek[2]
                offset = (peek[7] * 256 + peek[6]) * 0x7fff + peek[5] * 256 + peek[4]
                pointer = {
                    "Type": "",
                    "Size": bytescount,
                    "Offset": offset,
                    "Text Position": offset + textaddr,
                    "Pointer Position": fbin.tell(),
                }
                pointer["Type"] = CODEDICT.get(scripttype, int.from_bytes(scripttype, "little"))
                pointers.append(pointer)

    payload = {
        "Code Address": codeaddr,
        "Text Address": textaddr,
        "Original Text Block Size": size,
        "pointers": pointers,
    }
    with open(json_path, "w", encoding=ENCODING) as fjson:
        json.dump(payload, fjson, ensure_ascii=False, indent=4)


def validate_json(json_path):
    """Drop pointers whose Offset is not contiguous with the running total.

    This mirrors the original tool. NOTE: it silently discards non-contiguous
    pointers, which can lose text -- count is reported so callers can watch it."""
    with open(json_path, "r", encoding=ENCODING) as f:
        contents = json.load(f)
    offset = 0
    kept = []
    dropped = 0
    for pointer in contents["pointers"]:
        if offset != pointer["Offset"]:
            dropped += 1
            continue
        kept.append(pointer)
        offset += pointer["Size"]
    contents["pointers"] = kept
    with open(json_path, "w", encoding=ENCODING) as f:
        json.dump(contents, f, ensure_ascii=False, indent=4)
    return dropped


def read_pointers(bin_path, json_path):
    """Read each pointer's Shift-JIS text into 'Original Text'; seed 'New Text'."""
    with open(json_path, "r", encoding=ENCODING) as f:
        contents = json.load(f)
    with open(bin_path, "rb") as fbin:
        for pointer in contents["pointers"]:
            fbin.seek(pointer["Text Position"])
            decoded = fbin.read(pointer["Size"]).decode(ENCODING)
            pointer["Original Text"] = decoded
            pointer.setdefault("New Text", "")
    with open(json_path, "w", encoding=ENCODING) as f:
        json.dump(contents, f, ensure_ascii=False, indent=4)


def extract(bin_path, json_path):
    """Full extract: pointer table -> validate -> read text -> JSON."""
    find_pointers(bin_path, json_path)
    dropped = validate_json(json_path)
    read_pointers(bin_path, json_path)
    return dropped


# --------------------------------------------------------------------------- #
# INSERT
# --------------------------------------------------------------------------- #
def insert(bin_path, json_path, out_path):
    """Rewrite the text block + pointer table of `bin_path` into `out_path`,
    using each pointer's 'New Text' (falling back to 'Original Text').

    All inserted text is sanitized to Shift-JIS first; an un-encodable string
    raises ValueError naming the file/pointer, before anything is written."""
    with open(json_path, "r", encoding=ENCODING) as f:
        contents = json.load(f)

    # Pre-flight: sanitize everything up front so a bad string aborts cleanly.
    for idx, pointer in enumerate(contents["pointers"]):
        if pointer.get("_force_empty"):
            text = ""
        else:
            text = pointer.get("New Text") or pointer["Original Text"]
        try:
            pointer["_clean"] = sanitize(text)
        except ValueError as e:
            raise ValueError(f"{os.path.basename(json_path)} pointer #{idx} "
                             f"(pos {pointer['Pointer Position']}): {e}")

    shutil.copy(bin_path, out_path)
    text_addr = contents["Text Address"]

    total_offset = 0
    previous_size = 0
    newsize = 0
    with open(out_path, "rb+") as fout:
        fout.seek(text_addr)
        for pointer in contents["pointers"]:
            newtextbin = bytearray(pointer.pop("_clean"), ENCODING)
            newsize = len(newtextbin)
            fout.write(newtextbin)
            pointer["Size"] = newsize
            pointer["Offset"] = total_offset + previous_size
            pointer["Text Position"] = text_addr + total_offset + previous_size
            total_offset += previous_size
            previous_size = newsize
        new_block_size = total_offset + newsize
        contents["New Text Block Size"] = new_block_size
        fout.seek(8)
        fout.write(int2bytes(new_block_size))

        # update pointer table sizes/offsets in place
        for pointer in contents["pointers"]:
            fout.seek(pointer["Pointer Position"])
            assert fout.read(2) == b"\x03\x01", "pointer table desync"
            fout.write(int2bytes(pointer["Size"]))
            fout.write(int2bytes(pointer["Offset"], 4))

    with open(json_path, "w", encoding=ENCODING) as f:
        json.dump(contents, f, ensure_ascii=False, indent=4)


# --------------------------------------------------------------------------- #
# SELF-TEST  (proves the round-trip on a real .bin without touching originals)
# --------------------------------------------------------------------------- #
def selftest(bin_path, workdir="/tmp/ouran_selftest"):
    """Extract -> fill every Japanese line with a long ASCII string -> insert ->
    re-extract -> assert text matches. Returns (matched, mismatched)."""
    os.makedirs(workdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(bin_path))[0]
    j = os.path.join(workdir, base + ".json")
    patched = os.path.join(workdir, base + ".patched.bin")

    extract(bin_path, j)
    d = json.load(open(j, encoding=ENCODING))
    has_jp = lambda s: any(ord(c) > 0x2000 for c in s)
    for i, p in enumerate(d["pointers"]):
        if has_jp(p["Original Text"]):
            p["New Text"] = f"[{i}] long english translation line forcing block growth"
    json.dump(d, open(j, "w", encoding=ENCODING), ensure_ascii=False, indent=4)

    insert(bin_path, j, patched)
    edited = json.load(open(j, encoding=ENCODING))

    vj = os.path.join(workdir, base + ".verify.json")
    extract(patched, vj)
    v = json.load(open(vj, encoding=ENCODING))

    matched = mismatched = 0
    for a, b in zip(edited["pointers"], v["pointers"]):
        expected = a["New Text"] if a.get("New Text") else a["Original Text"]
        if b["Original Text"] == expected:
            matched += 1
        else:
            mismatched += 1
    return matched, mismatched


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None):
    ap = argparse.ArgumentParser(description="Ouran NDS script extract/insert toolkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="bin -> json")
    pe.add_argument("bin")
    pe.add_argument("json")

    pi = sub.add_parser("insert", help="bin + json -> patched bin")
    pi.add_argument("bin")
    pi.add_argument("json")
    pi.add_argument("out")

    ps = sub.add_parser("selftest", help="prove round-trip on a .bin")
    ps.add_argument("bin")

    args = ap.parse_args(argv)
    if args.cmd == "extract":
        dropped = extract(args.bin, args.json)
        print(f"extracted -> {args.json} ({dropped} non-contiguous pointers dropped)")
    elif args.cmd == "insert":
        insert(args.bin, args.json, args.out)
        print(f"patched -> {args.out}")
    elif args.cmd == "selftest":
        m, mm = selftest(args.bin)
        print(f"selftest: {m} matched, {mm} mismatched -> {'PASS' if mm == 0 else 'FAIL'}")
        sys.exit(0 if mm == 0 else 1)


if __name__ == "__main__":
    main()
