#!/usr/bin/env python3
"""Generate layout-risk reports for playable Ouran translation JSON."""

import argparse
import csv
import html
import json
import os
import re
from glob import glob

ENCODING = "shiftjis"
FORMAT_CODE = re.compile(r"#[A-Za-z]+\[[^\]]+\]")
SCALE_CODE = re.compile(r"#Scale\[([0-9.]+)\]")
ENDERS = set("。！？」…?!♪☆★〜~』】")

# Dialogue renderer (arm9 0x203bc18): pen += glyph_w + spacing per drawn char;
# space advances by spacing only; ',' '.' add 4px pause; '~' is a fixed 12px
# blank. Measured letter_spacing = 2; stock textbox budget = 32 chars * 7px.
PIXEL_SPACING = 2
PIXEL_BUDGET = 224

_PIXEL_WIDTHS = None  # char -> glyph_w, loaded from an NFTR via --font


def load_pixel_widths(font_path):
    global _PIXEL_WIDTHS
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from nftr_tool import NFTR
    f = NFTR(font_path)
    widths = {}
    for code in range(0x21, 0x7F):
        g = f.char_to_glyph.get(code)
        if g is not None:
            widths[chr(code)] = f.data[f.metrics_off(g) + 1]
    _PIXEL_WIDTHS = widths


def pixel_len(line):
    """Effective dialogue width in px; None when pixel mode is off."""
    if _PIXEL_WIDTHS is None:
        return None
    total = 0
    for ch in line:
        if ch == " ":
            total += PIXEL_SPACING
        elif ch == "~":
            total += 12
        else:
            total += _PIXEL_WIDTHS.get(ch, 11) + PIXEL_SPACING
            if ch in ",.":
                total += 4
    return total


def strip_codes(text):
    return FORMAT_CODE.sub("", text)


def has_japanese(text):
    return any(
        0x3040 <= ord(ch) <= 0x30FF
        or 0x4E00 <= ord(ch) <= 0x9FFF
        or 0xFF66 <= ord(ch) <= 0xFF9D
        for ch in text or ""
    )


def classify(pointer):
    text = pointer.get("New Text") or ""
    original = pointer.get("Original Text") or ""
    if original.startswith("#") or text.startswith("#Color") or text.startswith("#Pos"):
        return "formatted-overlay"
    if original.startswith("　") or text.startswith(" "):
        return "centered/title-card"
    if pointer.get("Type") == "Choice":
        return "choice"
    if pointer.get("Type") == "Chapter name":
        return "chapter"
    return "dialog"


def scale_factor(text):
    matches = SCALE_CODE.findall(text or "")
    if not matches:
        return 1.0
    try:
        return float(matches[-1])
    except ValueError:
        return 1.0


def limits(kind):
    if kind == "choice":
        return 30, 1
    if kind == "chapter":
        return 34, 1
    if kind == "formatted-overlay":
        return 32, 2
    if kind == "centered/title-card":
        return 32, 2
    return 32, 3


def risk_reasons(pointer):
    text = pointer.get("New Text") or ""
    kind = classify(pointer)
    width, max_lines = limits(kind)
    lines = text.splitlines() or [""]
    visible_lengths = [len(strip_codes(line)) for line in lines]
    reasons = []

    if not text.strip() and has_japanese(pointer.get("Original Text", "")):
        reasons.append("blank")
    if has_japanese(text):
        reasons.append("jp-in-en")
    if len(lines) > max_lines:
        reasons.append(f"too-many-lines:{len(lines)}>{max_lines}")
    if visible_lengths and max(visible_lengths) > width:
        reasons.append(f"line-too-long:{max(visible_lengths)}>{width}")
    if "It looks like" in text or "please provide" in text.lower() or "without context" in text.lower():
        reasons.append("model-explanation")
    if "　" in text:
        reasons.append("fullwidth-space")
    if re.search(r"\b(Kane|Kaname|Hikari|Nekuzawa|predecessor)\b", text):
        reasons.append("name/term-risk")
    return kind, width, max_lines, visible_lengths, reasons


def ends_sentence(jp):
    s = (jp or "").rstrip()
    if not s:
        return True
    if s.endswith("――") or s.endswith("―"):
        return True
    return s[-1] in ENDERS


def dialog_group_rows(name, pointers):
    cur = []
    for idx, pointer in enumerate(pointers):
        if pointer.get("Type") != "Dialog" or classify(pointer) != "dialog":
            if cur:
                yield group_risk_row(name, pointers, cur)
                cur = []
            continue
        cur.append(idx)
        if ends_sentence(pointer.get("Original Text", "")):
            yield group_risk_row(name, pointers, cur)
            cur = []
    if cur:
        yield group_risk_row(name, pointers, cur)


def group_risk_row(name, pointers, ids):
    width, max_lines = limits("dialog")
    text = "".join(pointers[i].get("New Text") or "" for i in ids)
    jp = "".join(pointers[i].get("Original Text") or "" for i in ids)
    lines = text.splitlines() or [""]
    visible_lengths = [len(strip_codes(line)) for line in lines]
    reasons = []
    if not text.strip() and has_japanese(jp):
        reasons.append("blank")
    if has_japanese(text):
        reasons.append("jp-in-en")
    if len(lines) > max_lines:
        reasons.append(f"display-too-many-lines:{len(lines)}>{max_lines}")
    scale = scale_factor(text)
    pixel_lengths = [pixel_len(strip_codes(line)) for line in lines]
    if _PIXEL_WIDTHS is not None:
        if pixel_lengths and max(pixel_lengths) > PIXEL_BUDGET:
            reasons.append(f"display-line-too-wide:{max(pixel_lengths)}px>{PIXEL_BUDGET}px")
    else:
        scaled_lengths = [length * scale for length in visible_lengths]
        if scaled_lengths and max(scaled_lengths) > width:
            reasons.append(f"display-line-too-long:{max(visible_lengths)}@{scale:g}>{width}")
    for left_idx, right_idx in zip(ids, ids[1:]):
        left = pointers[left_idx].get("New Text") or ""
        right = pointers[right_idx].get("New Text") or ""
        if left and right and re.search(r"[A-Za-z]$", left) and re.search(r"^[A-Z]", right):
            reasons.append("possible-missing-space")
            break
    if "It looks like" in text or "please provide" in text.lower() or "without context" in text.lower():
        reasons.append("model-explanation")
    if "　" in text:
        reasons.append("fullwidth-space")
    if re.search(r"\b(Kane|Kaname|Hikari|Nekuzawa|predecessor)\b", text):
        reasons.append("name/term-risk")
    if not reasons:
        return None
    return {
        "file": name,
        "id": ",".join(str(i) for i in ids),
        "type": "Dialog group",
        "kind": "dialog-display",
        "limit_width": width,
        "limit_lines": max_lines,
        "line_count": len(lines),
        "max_line_len": max(visible_lengths or [0]),
        "reasons": ";".join(reasons),
        "jp": jp,
        "en": text,
    }


def load(path):
    with open(path, encoding=ENCODING) as f:
        return json.load(f)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate Ouran layout QA reports")
    parser.add_argument("json_dir")
    parser.add_argument("--out-prefix", default="transcripts/layout_qa")
    parser.add_argument("--font", help="NFTR font path: switch dialogue checks to "
                        "pixel widths (use build/testfonts/LD_narrow4.NFTR or the "
                        "stock backup font)")
    args = parser.parse_args(argv)
    if args.font:
        load_pixel_widths(args.font)

    rows = []
    for path in sorted(glob(os.path.join(args.json_dir, "*.json"))):
        name = os.path.basename(path)
        if name.startswith(".tmp-") or ".corrupt-" in name:
            continue
        data = load(path)
        for row in dialog_group_rows(name, data["pointers"]):
            if row:
                rows.append(row)
        for idx, pointer in enumerate(data["pointers"]):
            if pointer.get("Type") not in ("Choice", "Chapter name"):
                continue
            kind, width, max_lines, visible_lengths, reasons = risk_reasons(pointer)
            if not reasons:
                continue
            rows.append({
                "file": name,
                "id": idx,
                "type": pointer.get("Type", ""),
                "kind": kind,
                "limit_width": width,
                "limit_lines": max_lines,
                "line_count": len((pointer.get("New Text") or "").splitlines() or [""]),
                "max_line_len": max(visible_lengths or [0]),
                "reasons": ";".join(reasons),
                "jp": pointer.get("Original Text", ""),
                "en": pointer.get("New Text", ""),
            })

    os.makedirs(os.path.dirname(args.out_prefix) or ".", exist_ok=True)
    tsv_path = args.out_prefix + ".tsv"
    html_path = args.out_prefix + ".html"

    fieldnames = [
        "file", "id", "type", "kind", "limit_width", "limit_lines",
        "line_count", "max_line_len", "reasons", "jp", "en",
    ]
    with open(tsv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    style = (
        "body{font:14px system-ui;margin:24px;color:#1f2937;background:#fafafa}"
        "table{border-collapse:collapse;width:100%;background:white}"
        "th,td{border:1px solid #d1d5db;padding:7px;vertical-align:top}"
        "th{position:sticky;top:0;background:#f3f4f6}.txt{white-space:pre-wrap}"
        ".meta{color:#6b7280}.reasons{font-weight:700;color:#991b1b}"
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<!doctype html><meta charset='utf-8'><title>Layout QA</title>")
        f.write(f"<style>{style}</style><h1>Layout QA Report</h1>")
        f.write(f"<p class='meta'>{len(rows)} risky entries from <code>{html.escape(args.json_dir)}</code>.</p>")
        f.write("<table><tr><th>File</th><th>#</th><th>Kind</th><th>Reasons</th><th>JP</th><th>EN</th></tr>")
        for row in rows:
            f.write("<tr>")
            f.write(f"<td>{html.escape(row['file'])}</td>")
            f.write(f"<td>{row['id']}</td>")
            f.write(f"<td>{html.escape(row['kind'])}<br><span class='meta'>{row['line_count']} lines, max {row['max_line_len']}</span></td>")
            f.write(f"<td class='reasons'>{html.escape(row['reasons'])}</td>")
            f.write(f"<td class='txt'>{html.escape(row['jp'])}</td>")
            f.write(f"<td class='txt'>{html.escape(row['en'])}</td>")
            f.write("</tr>")
        f.write("</table>")

    print(f"rows={len(rows)}")
    print(f"wrote {tsv_path}")
    print(f"wrote {html_path}")


if __name__ == "__main__":
    main()
