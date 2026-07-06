#!/usr/bin/env python3
"""Translate short UI/menu label strings via the local Sugoi-14B API.

Unlike dialogue, these are button/menu labels: short, imperative, and must
stay short enough to redraw into a fixed pixel-tile budget. Uses a dedicated
system prompt instead of translate.py's narrative-dialogue one.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from translate import SugoiApiEngine  # noqa: E402

UI_SYSTEM_PROMPT = (
    "You are localizing UI button and menu labels for a Nintendo DS visual novel. "
    "Translate the given Japanese UI label to English. Keep it as SHORT as possible "
    "(these are small buttons with tight pixel space) — prefer 1-2 words. "
    "Use standard visual-novel/game UI terminology (e.g. Save, Load, Auto, Skip, Back, Menu, History, Confirm). "
    "Return ONLY the translated label text, nothing else: no notes, quotes, or romanization."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", help="JSON list of Japanese UI strings")
    ap.add_argument("out", help="Output JSON glossary path")
    ap.add_argument("--api-url", default="http://127.0.0.1:11434/v1")
    ap.add_argument("--api-model", default="sugoi-14b")
    args = ap.parse_args()

    strings = json.loads(Path(args.source).read_text(encoding="utf-8"))
    engine = SugoiApiEngine(args.api_url, args.api_model, system_prompt=UI_SYSTEM_PROMPT)

    results = []
    for jp in strings:
        try:
            en = engine(jp)
        except Exception as exc:
            en = None
            print(f"FAILED {jp!r}: {exc}")
        results.append({"jp": jp, "en": en})
        print(f"{jp!r} -> {en!r}")

    Path(args.out).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"wrote {args.out} ({len(results)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
