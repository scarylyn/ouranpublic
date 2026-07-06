#!/usr/bin/env python3
"""Sentence-group export/merge bridge for AI retranslation.

The game script splits Japanese sentences across consecutive Dialog textboxes.
Translating each box in isolation (what the MT pass did) invents subjects,
genders and meanings. This tool:

  export : joins consecutive Dialog fragments into full sentences and emits
           one JSONL record per *group*, so the translator sees whole sentences.
  merge  : takes reviewed JSONL ({"gid": N, "en": "..."}), splits the English
           back across the group's textboxes (balanced by word count), wraps
           each box at the playable width, and writes it into New Text.

Groups are stable for a given JSON file: gid is the running group index.
"""

import argparse
import json
import os
import re
import sys
import textwrap

sys.path.insert(0, os.path.dirname(__file__))
from status_model import is_translatable  # noqa: E402
from sanitize import sanitize  # noqa: E402

ENCODING = "shiftjis"
WIDTH = 32
MAX_LINES = 3
# JP characters that end a textbox-final sentence (box is NOT continued)
ENDERS = set("。！？」…?!♪☆★〜~』】")
FORMAT_CODE = re.compile(r"#(?:Color|Scale)\[[^\]]+\]")
FORMAT_PREFIX = re.compile(r"^(?:#(?:Color|Scale)\[[^\]]+\])+")


def ends_sentence(jp):
    s = jp.rstrip()
    if not s:
        return True
    if s.endswith("――") or s.endswith("―"):
        return True
    return s[-1] in ENDERS


def is_title_card(p):
    # Original Text is the stable source of truth: format-code overlays and
    # centered title cards carry their marker in the JP source itself. Also
    # check New Text for older files translated before this was fixed.
    ot = p.get("Original Text") or ""
    return ot.startswith("　") or bool(FORMAT_PREFIX.match(ot)) or \
           (p.get("New Text") or "").startswith("#")


def build_groups(pointers):
    """Return list of groups; each group is a list of pointer indices."""
    groups = []
    cur = []
    for idx, p in enumerate(pointers):
        if not is_translatable(p):
            continue
        if p.get("Type") != "Dialog" or is_title_card(p):
            if cur:
                groups.append(cur)
                cur = []
            groups.append([idx])
            continue
        cur.append(idx)
        if ends_sentence(p["Original Text"]):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def _speaker_for(pointers, idx):
    for j in range(idx - 1, max(idx - 8, -1), -1):
        if pointers[j].get("Type") == "Speaker":
            return pointers[j].get("New Text") or pointers[j].get("Original Text", "")
    return ""


def export(json_path, out_path):
    d = json.load(open(json_path, encoding=ENCODING))
    pts = d["pointers"]
    groups = build_groups(pts)
    n = 0
    with open(out_path, "w", encoding="utf-8") as f:
        for gid, ids in enumerate(groups):
            first = pts[ids[0]]
            rec = {
                "gid": gid,
                "ids": ids,
                "type": first.get("Type"),
                "boxes": len(ids),
                "speaker": _speaker_for(pts, ids[0]) if first.get("Type") == "Dialog" else "",
                "jp": "".join(pts[i]["Original Text"] for i in ids),
                "cur": " | ".join((pts[i].get("New Text") or "") for i in ids),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"exported {n} groups ({sum(len(g) for g in groups)} entries) -> {out_path}")


def visible_len(s):
    return len(FORMAT_CODE.sub("", s))


def wrap_display_text(en):
    """Wrap one displayed textbox at word boundaries."""
    en = " ".join(en.split())
    lines = textwrap.wrap(en, WIDTH, break_long_words=False,
                          break_on_hyphens=False) or [""]
    if any(visible_len(line) > WIDTH for line in lines):
        raise ValueError(f"unbreakable line over {WIDTH} chars: {en!r}")
    if len(lines) > MAX_LINES:
        raise ValueError(f"overflow: {len(lines)} lines in 1 box: {en!r}")
    return "\n".join(lines)


def split_into_boxes(en, n):
    """Compatibility helper for old callers.

    Consecutive Dialog pointers are text fragments for one displayed textbox,
    not separate textboxes. Put the full wrapped display string in the first
    pointer and leave continuation fragments empty so the engine concatenates
    cleanly with no missing spaces or mid-word wraps.
    """
    wrapped = wrap_display_text(en)
    if n == 1:
        return [wrapped]
    return [wrapped] + [""] * (n - 1)
    words = en.split(" ")
    total = sum(len(w) + 1 for w in words)
    # initial proportional cut points, then adjust to satisfy line limits
    boxes, start = [], 0
    for k in range(n):
        if k == n - 1:
            chunk = words[start:]
        else:
            target = total * (k + 1) // n
            acc, cut = 0, start
            for i in range(start, len(words) - (n - 1 - k)):
                acc += len(words[i]) + 1
                cut = i + 1
                run = sum(len(w) + 1 for w in words[:cut])
                if run >= target:
                    break
            chunk = words[start:cut]
            start = cut
        boxes.append(chunk)
    # rebalance forward if any box overflows MAX_LINES
    def wrap_chunk(chunk):
        return textwrap.wrap(" ".join(chunk), WIDTH, break_long_words=False,
                             break_on_hyphens=False) or [""]
    for _ in range(200):
        ok = True
        for k in range(n - 1):
            while len(wrap_chunk(boxes[k])) > MAX_LINES and len(boxes[k]) > 1:
                boxes[k + 1].insert(0, boxes[k].pop())
                ok = False
        if ok:
            break
    if len(wrap_chunk(boxes[-1])) > MAX_LINES:
        raise ValueError(f"overflow after rebalance ({n} boxes): {en!r}")
    return ["\n".join(wrap_chunk(c)) for c in boxes]


def merge(json_path, reviewed_path, note=None):
    d = json.load(open(json_path, encoding=ENCODING))
    pts = d["pointers"]
    groups = build_groups(pts)
    merged = flagged = 0
    for ln, line in enumerate(open(reviewed_path, encoding="utf-8"), 1):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        gid, en = rec["gid"], rec.get("en", "")
        if not en.strip():
            continue
        ids = groups[gid]
        try:
            en = sanitize(en)
            first = pts[ids[0]]
            # Translators (human or model) sometimes drop a leading format-code
            # overlay marker (#Color[7]#Scale[1.8]...) that's present in the JP
            # source; restore it verbatim so is_title_card stays stable next run.
            jp_prefix_match = FORMAT_PREFIX.match(first.get("Original Text") or "")
            if jp_prefix_match and not en.startswith(jp_prefix_match.group(0)):
                en = jp_prefix_match.group(0) + FORMAT_PREFIX.sub("", en, count=1)
            if first.get("Type") != "Dialog" or is_title_card(first):
                # choices/chapters/speakers/title-cards: single entry, keep as-is
                pts[ids[0]]["New Text"] = en
            else:
                for i, boxtext in zip(ids, split_into_boxes(en, len(ids))):
                    pts[i]["New Text"] = boxtext
                    if boxtext:
                        pts[i].pop("_force_empty", None)
                    else:
                        pts[i]["_force_empty"] = True
            for i in ids:
                pts[i]["Status"] = "ai"
                pts[i]["Note"] = rec.get("note") or note or "group retranslation"
            merged += 1
        except ValueError as e:
            print(f"  FLAG gid {gid}: {e}")
            flagged += 1
    json.dump(d, open(json_path, "w", encoding=ENCODING), ensure_ascii=False, indent=4)
    print(f"merged {merged} groups into {os.path.basename(json_path)} ({flagged} flagged)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pe = sub.add_parser("export")
    pe.add_argument("json"); pe.add_argument("out")
    pm = sub.add_parser("merge")
    pm.add_argument("json"); pm.add_argument("reviewed")
    pm.add_argument("--note")
    a = ap.parse_args()
    if a.cmd == "export":
        export(a.json, a.out)
    else:
        merge(a.json, a.reviewed, a.note)


if __name__ == "__main__":
    main()
