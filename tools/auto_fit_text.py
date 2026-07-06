#!/usr/bin/env python3
"""Auto-shorten displayed dialog groups so they fit the DS textbox.

This uses a local OpenAI-compatible endpoint such as Ollama. It never writes a
model answer unless the answer is Shift-JIS safe and wraps within WIDTH x
MAX_LINES at word boundaries.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
import time
import urllib.error
import urllib.request
from glob import glob
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import group_review  # noqa: E402
from layout_qa_report import ends_sentence, strip_codes  # noqa: E402
from sanitize import sanitize  # noqa: E402
from translate import has_japanese  # noqa: E402

ENCODING = "shiftjis"
WIDTH = 32
MAX_LINES = 3
TRANSLATABLE_TYPES = {"Dialog"}
FORBIDDEN_RE = re.compile(
    r"\b(Kyouya|Kyooya|Nekoze|Nekuzawa|Catzawa|Nezumizawa|Ring senpai|"
    r"Morino-senpai|Haruhi Fujio|Suou Tamaki)\b",
    re.I,
)


def wrap_ok(text: str, width: int = WIDTH, max_lines: int = MAX_LINES) -> tuple[bool, str]:
    text = " ".join((text or "").split())
    lines = textwrap.wrap(
        text,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    ) or [""]
    wrapped = "\n".join(lines)
    if len(lines) > max_lines:
        return False, wrapped
    if any(len(strip_codes(line)) > width for line in lines):
        return False, wrapped
    return True, wrapped


def dialog_display_groups(pointers: list[dict]) -> list[list[int]]:
    groups: list[list[int]] = []
    cur: list[int] = []
    for idx, pointer in enumerate(pointers):
        if pointer.get("Type") not in TRANSLATABLE_TYPES or group_review.is_title_card(pointer):
            if cur:
                groups.append(cur)
                cur = []
            continue
        cur.append(idx)
        if ends_sentence(pointer.get("Original Text", "")):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return groups


def current_display_text(pointers: list[dict], ids: list[int]) -> str:
    return " ".join(
        " ".join((pointers[idx].get("New Text") or "").split())
        for idx in ids
        if (pointers[idx].get("New Text") or "").strip()
    ).strip()


def original_text(pointers: list[dict], ids: list[int]) -> str:
    return "".join(pointers[idx].get("Original Text") or "" for idx in ids)


def needs_fit(pointers: list[dict], ids: list[int], width: int, max_lines: int) -> bool:
    text = current_display_text(pointers, ids)
    if not text:
        return False
    ok, _ = wrap_ok(text, width, max_lines)
    if not ok:
        return True
    for left_idx, right_idx in zip(ids, ids[1:]):
        left = pointers[left_idx].get("New Text") or ""
        right = pointers[right_idx].get("New Text") or ""
        if left and right and re.search(r"[A-Za-z]$", left) and re.search(r"^[A-Z]", right):
            return True
    return False


def chat(api_url: str, model: str, prompt: str, timeout: int) -> str:
    url = api_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You shorten English localizations for a Nintendo DS visual novel. "
                    "Return only one English rewrite. No notes. No quotes around the full line. "
                    "Keep names and honorifics. Keep meaning. Use plain ASCII punctuation. "
                    "The answer must fit in at most 3 lines of 32 monospaced characters. "
                    "Use these exact names: Tamaki, Kyoya, Hikaru, Kaoru, Honey, Mori, "
                    "Haruhi, Sayuri, Kurakano, Kamikamo, Nekozawa, Ootori."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer sk-dummy"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def clean_answer(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip().strip('"')
    text = re.sub(r"^(?:English|Rewrite|Answer)\s*:\s*", "", text, flags=re.I)
    text = re.sub(r"\.\.\.(?=[A-Za-z])", "... ", text)
    return sanitize(" ".join(text.split()))


def validate_answer(answer: str) -> None:
    if has_japanese(answer):
        raise ValueError("answer still contains Japanese")
    match = FORBIDDEN_RE.search(answer)
    if match:
        raise ValueError(f"forbidden name/term: {match.group(0)}")
    if len(answer.split()) > 3 and not re.search(r"[.!?…~]$", answer):
        raise ValueError("answer lacks sentence-ending punctuation")


def prompt_for(jp: str, cur: str, width: int, max_lines: int) -> str:
    return (
        f"Japanese source:\n{jp}\n\n"
        f"Current English, too long for the textbox:\n{cur}\n\n"
        f"Rewrite it naturally in English so it fits {max_lines} lines of "
        f"{width} characters each. Prefer concise wording over literal wording. "
        "Do not add facts. Preserve character names and honorifics."
    )


def apply_group(pointers: list[dict], ids: list[int], wrapped: str, note: str) -> None:
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
        pointer["Note"] = note


def process_file(
    path: Path,
    api_url: str,
    model: str,
    width: int,
    max_lines: int,
    limit: int | None,
    dry_run: bool,
    use_model: bool,
    timeout: int,
) -> tuple[int, int, int]:
    with path.open(encoding=ENCODING) as f:
        data = json.load(f)
    pointers = data["pointers"]
    changed = failed = seen = 0

    for ids in dialog_display_groups(pointers):
        if not needs_fit(pointers, ids, width, max_lines):
            continue
        if limit is not None and seen >= limit:
            break
        seen += 1

        cur = current_display_text(pointers, ids)
        ok, wrapped = wrap_ok(cur, width, max_lines)
        if ok:
            if not dry_run:
                apply_group(pointers, ids, wrapped, "auto-fit rewrap")
            changed += 1
            continue

        if not use_model:
            failed += 1
            print(f"NEEDS SHORTENING {path.name} {','.join(map(str, ids))}: {cur!r}")
            continue

        jp = original_text(pointers, ids)
        try:
            answer = chat(api_url, model, prompt_for(jp, cur, width, max_lines), timeout)
            answer = clean_answer(answer)
            validate_answer(answer)
            ok, wrapped = wrap_ok(answer, width, max_lines)
            if not ok:
                raise ValueError(f"still over limit: {wrapped!r}")
        except (ValueError, urllib.error.URLError, TimeoutError) as exc:
            failed += 1
            print(f"FAILED {path.name} {','.join(map(str, ids))}: {exc}")
            continue

        if not dry_run:
            apply_group(pointers, ids, wrapped, "auto-fit local model shortening")
        changed += 1
        print(f"FIT {path.name} {','.join(map(str, ids))}: {cur!r} -> {wrapped!r}")

    if changed and not dry_run:
        with path.open("w", encoding=ENCODING) as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    return seen, changed, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_dir")
    parser.add_argument("--file", help="only process one JSON file name")
    parser.add_argument("--api-url", default="http://localhost:11434/v1")
    parser.add_argument("--model", default="sugoi-14b")
    parser.add_argument("--width", type=int, default=WIDTH)
    parser.add_argument("--max-lines", type=int, default=MAX_LINES)
    parser.add_argument("--limit", type=int, help="max flagged groups per file")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--use-model",
        action="store_true",
        help="allow local model rewrites for lines that cannot be fixed by rewrapping",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.file:
        paths = [Path(args.json_dir) / args.file]
    else:
        paths = [Path(p) for p in sorted(glob(os.path.join(args.json_dir, "*.json")))]

    total_seen = total_changed = total_failed = 0
    started = time.time()
    for path in paths:
        if ".corrupt-" in path.name or path.name.startswith(".tmp-"):
            continue
        seen, changed, failed = process_file(
            path,
            args.api_url,
            args.model,
            args.width,
            args.max_lines,
            args.limit,
            args.dry_run,
            args.use_model,
            args.timeout,
        )
        total_seen += seen
        total_changed += changed
        total_failed += failed
        print(f"{path.name}: seen={seen} changed={changed} failed={failed}")

    elapsed = time.time() - started
    print(
        f"total seen={total_seen} changed={total_changed} "
        f"failed={total_failed} dry_run={args.dry_run} elapsed={elapsed:.1f}s"
    )
    return 1 if total_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
