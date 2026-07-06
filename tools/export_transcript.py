#!/usr/bin/env python3
"""Export readable transcripts from extracted/translated Ouran JSON files."""

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from status_model import is_translatable, status_of  # noqa: E402

ENCODING = "shiftjis"


def speaker_for(pointers, idx):
    if pointers[idx].get("Type") == "Speaker":
        return ""
    for j in range(idx - 1, max(idx - 8, -1), -1):
        if pointers[j].get("Type") == "Speaker":
            return pointers[j].get("New Text") or pointers[j].get("Original Text", "")
    return ""


def iter_rows(json_path, include_speakers=True):
    data = json.load(open(json_path, encoding=ENCODING))
    pointers = data["pointers"]
    for idx, pointer in enumerate(pointers):
        if not is_translatable(pointer):
            continue
        if pointer.get("Type") == "Speaker" and not include_speakers:
            continue
        yield {
            "id": idx,
            "type": pointer.get("Type", ""),
            "speaker": speaker_for(pointers, idx),
            "status": status_of(pointer),
            "jp": pointer.get("Original Text", ""),
            "mt": pointer.get("MT Text", ""),
            "en": pointer.get("New Text", ""),
        }


def clean_cell(value):
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def write_markdown(json_path, out, include_speakers=True):
    name = os.path.basename(json_path)
    out.write(f"# {name}\n\n")
    for row in iter_rows(json_path, include_speakers=include_speakers):
        speaker = f" | {row['speaker']}" if row["speaker"] else ""
        out.write(f"## {row['id']} | {row['type']} | {row['status']}{speaker}\n\n")
        out.write("JP:\n")
        out.write(f"{clean_cell(row['jp'])}\n\n")
        if row["mt"]:
            out.write("Machine draft:\n")
            out.write(f"{clean_cell(row['mt'])}\n\n")
        if row["en"]:
            out.write("Current English:\n")
            out.write(f"{clean_cell(row['en'])}\n\n")


def write_delimited(json_path, out, fmt, include_speakers=True):
    delimiter = "\t" if fmt == "tsv" else ","
    writer = csv.DictWriter(
        out,
        fieldnames=["id", "type", "speaker", "status", "jp", "mt", "en"],
        delimiter=delimiter,
        lineterminator="\n",
    )
    writer.writeheader()
    for row in iter_rows(json_path, include_speakers=include_speakers):
        writer.writerow(row)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export a readable transcript from an Ouran JSON file")
    parser.add_argument("json", help="source JSON, usually translated/<file>.json")
    parser.add_argument("-o", "--out", help="output path; defaults to stdout")
    parser.add_argument("--format", choices=["md", "csv", "tsv"], default="md")
    parser.add_argument("--no-speakers", action="store_true", help="omit Speaker rows")
    args = parser.parse_args(argv)

    if args.out:
        out = open(args.out, "w", encoding="utf-8", newline="")
    else:
        out = sys.stdout
    try:
        if args.format == "md":
            write_markdown(args.json, out, include_speakers=not args.no_speakers)
        else:
            write_delimited(args.json, out, args.format, include_speakers=not args.no_speakers)
    finally:
        if args.out:
            out.close()


if __name__ == "__main__":
    main()
