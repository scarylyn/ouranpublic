#!/usr/bin/env python3
"""AI review bridge: export JP + machine draft for any AI to check, merge back.

This is the model-agnostic way to let "another AI come in and check the work".
It does not call any API itself -- you point it at a JSON file, get a compact
review file, hand that to whatever AI you like (Claude / Gemini / Codex / a future
session of me), and merge the corrections back.

Workflow
  1. export:  python3 tools/ai_review.py export translated/118_4_2.json review.jsonl
  2. hand review.jsonl + REVIEW_PROMPT.md to an AI; it writes corrected English
     into each line's "en" field, producing reviewed.jsonl
  3. merge:   python3 tools/ai_review.py merge translated/118_4_2.json reviewed.jsonl

Export line (one JSON object per line, JSONL):
  {"id": 42, "type": "Dialog", "speaker": "Haruhi", "jp": "...", "mt": "...",
   "context": ["prev jp line", "this jp line", "next jp line"]}

Reviewed line the AI returns:
  {"id": 42, "en": "corrected english", "note": "optional"}

Only lines needing review (status mt or untranslated) are exported by default;
use --all to export everything. Merging sets Status='ai' and never touches
Original Text or MT Text, so nothing is lost and the change is auditable.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sanitize import sanitize  # noqa: E402
from status_model import is_translatable, status_of  # noqa: E402

ENCODING = "shiftjis"
CONTEXT_WINDOW = 2  # JP lines of surrounding dialogue for the AI's context


def _speaker_for(pointers, idx):
    """Nearest preceding Speaker label, as context for a dialog line."""
    for j in range(idx - 1, max(idx - 8, -1), -1):
        if pointers[j].get("Type") == "Speaker":
            return pointers[j].get("New Text") or pointers[j].get("Original Text", "")
    return ""


def _context(pointers, idx):
    """A small window of surrounding Japanese for disambiguation."""
    out = []
    for j in range(max(idx - CONTEXT_WINDOW, 0), min(idx + CONTEXT_WINDOW + 1, len(pointers))):
        if is_translatable(pointers[j]):
            out.append(pointers[j]["Original Text"])
    return out


def export(json_path, out_path, include_all=False):
    d = json.load(open(json_path, encoding=ENCODING))
    pts = d["pointers"]
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for idx, p in enumerate(pts):
            if not is_translatable(p):
                continue
            if not include_all and status_of(p) in ("ai", "approved"):
                continue
            rec = {
                "id": idx,
                "type": p.get("Type"),
                "speaker": _speaker_for(pts, idx) if p.get("Type") != "Speaker" else "",
                "jp": p["Original Text"],
                "mt": p.get("MT Text", p.get("New Text", "")),
                "context": _context(pts, idx),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"exported {n} lines -> {out_path}")
    return n


def merge(json_path, reviewed_path):
    d = json.load(open(json_path, encoding=ENCODING))
    pts = d["pointers"]
    merged = flagged = 0
    with open(reviewed_path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  skip line {ln}: bad JSON ({e})")
                continue
            idx = rec.get("id")
            en = rec.get("en", "")
            if idx is None or not isinstance(idx, int) or idx >= len(pts):
                print(f"  skip line {ln}: bad id {idx!r}")
                continue
            if not en.strip():
                continue
            try:
                pts[idx]["New Text"] = sanitize(en)
                pts[idx]["Status"] = "ai"
                if rec.get("note"):
                    pts[idx]["Note"] = rec["note"]
                merged += 1
            except ValueError as e:
                pts[idx]["Note"] = f"AI text un-encodable: {e}"
                flagged += 1
    json.dump(d, open(json_path, "w", encoding=ENCODING), ensure_ascii=False, indent=4)
    print(f"merged {merged} AI corrections into {os.path.basename(json_path)} "
          f"({flagged} flagged un-encodable)")
    return merged, flagged


def main(argv=None):
    ap = argparse.ArgumentParser(description="AI review export/merge bridge")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("export")
    pe.add_argument("json"); pe.add_argument("out")
    pe.add_argument("--all", action="store_true", help="include already-reviewed lines")
    pm = sub.add_parser("merge")
    pm.add_argument("json"); pm.add_argument("reviewed")
    args = ap.parse_args(argv)
    if args.cmd == "export":
        export(args.json, args.out, args.all)
    else:
        merge(args.json, args.reviewed)


if __name__ == "__main__":
    main()
