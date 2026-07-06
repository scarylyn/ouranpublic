#!/usr/bin/env python3
"""Conservative word-boundary wrapping for playable Ouran JSON text.

The game concatenates consecutive Dialog script fragments before displaying a
textbox. This pass wraps the concatenated text at word boundaries, writes the
full display text into the first fragment, and blanks the continuation
fragments so the game cannot join words without spaces at fragment boundaries.
"""

import argparse
import glob
import json
import os
import re
import textwrap

ENCODING = "shiftjis"
FORMAT_CODE = re.compile(r"#(?:Color|Scale)\[[^\]]+\]")
ENDERS = set("。！？」…?!♪☆★〜~』】")
MAX_LINES = 3


def visible_len(text):
    return len(FORMAT_CODE.sub("", text))


def wrap_line(line, width):
    if visible_len(line) <= width:
        return line

    prefix = ""
    while True:
        match = FORMAT_CODE.match(line[len(prefix):])
        if not match:
            break
        prefix += match.group(0)

    body = line[len(prefix):]
    leading = len(body) - len(body.lstrip(" 　"))
    indent = body[:leading]
    body = body[leading:]

    wrapped = textwrap.wrap(
        body,
        width=max(width - visible_len(prefix + indent), 10),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not wrapped:
        return line
    wrapped[0] = prefix + indent + wrapped[0]
    return "\n".join(wrapped)


def wrap_text(text, width):
    return "\n".join(wrap_line(line, width) for line in text.splitlines())


def ends_sentence(jp):
    s = (jp or "").rstrip()
    if not s:
        return True
    if s.endswith("――") or s.endswith("―"):
        return True
    return s[-1] in ENDERS


def is_title_card(pointer):
    original = pointer.get("Original Text") or ""
    text = pointer.get("New Text") or ""
    return original.startswith("　") or text.startswith("#")


def dialog_groups(pointers):
    cur = []
    for idx, pointer in enumerate(pointers):
        if pointer.get("Type") != "Dialog" or is_title_card(pointer):
            if cur:
                yield cur
                cur = []
            continue
        cur.append(idx)
        if ends_sentence(pointer.get("Original Text", "")):
            yield cur
            cur = []
    if cur:
        yield cur


def collapse_display_text(pointers, ids):
    parts = []
    for idx in ids:
        text = pointers[idx].get("New Text") or ""
        if text.strip():
            parts.append(" ".join(text.split()))
    return " ".join(parts)


def wrap_display_text(text, width):
    text = " ".join((text or "").split())
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    return "\n".join(lines), lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="Wrap long playable dialog text at word boundaries")
    parser.add_argument("json_dir")
    parser.add_argument("--width", type=int, default=32)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    changed_files = changed_lines = 0
    for path in sorted(glob.glob(os.path.join(args.json_dir, "*.json"))):
        name = os.path.basename(path)
        if name.startswith(".tmp-") or ".corrupt-" in name:
            continue
        with open(path, encoding=ENCODING) as f:
            data = json.load(f)

        file_changed = False
        for ids in dialog_groups(data["pointers"]):
            text = collapse_display_text(data["pointers"], ids)
            if not text:
                continue
            wrapped, lines = wrap_display_text(text, args.width)
            if len(lines) > args.max_lines:
                continue
            old = [data["pointers"][i].get("New Text", "") for i in ids]
            new = [wrapped] + [""] * (len(ids) - 1)
            if old != new:
                for idx, value in zip(ids, new):
                    pointer = data["pointers"][idx]
                    old_text = pointer.get("New Text", "")
                    pointer["New Text"] = value
                    if value:
                        pointer.pop("_force_empty", None)
                    else:
                        pointer["_force_empty"] = True
                    if pointer.get("MT Text") == old_text:
                        pointer["MT Text"] = value
                file_changed = True
                changed_lines += len(ids)

        if file_changed:
            changed_files += 1
            if not args.dry_run:
                with open(path, "w", encoding=ENCODING) as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"changed_files={changed_files} changed_lines={changed_lines}")


if __name__ == "__main__":
    main()
