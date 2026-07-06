#!/usr/bin/env python3
"""Conservative helper for the group retranslation workflow.

This script automates the repeatable parts of the human-quality pass:

  draft FILE.json
      backup, export groups, and prefill /tmp/FILE_reviewed.jsonl from exact
      Japanese matches already reviewed elsewhere in the wrapped JSON folder.
      Unknown groups are written to /tmp/FILE_todo.jsonl for human/AI review.

  auto FILE.json
      draft (if needed), then translate every remaining todo group for free by
      calling a local Sugoi-14B (or compatible) server on the *joined sentence*
      per group -- the whole reason MT was bad originally is it translated
      isolated textbox fragments; this sends full sentences instead. Writes
      results into /tmp/FILE_reviewed.jsonl. Costs no API usage. Quality is
      still machine translation -- run `finish` after, and use Claude/Codex
      only to patch whatever the QA/artifact scan flags, not to retranslate
      everything.

  finish FILE.json
      merge /tmp/FILE_reviewed.jsonl, fix known non-dialog name labels, run
      layout QA, scan for common MT artifacts, rebuild bins/NDS, and print CRC.

  run FILE.json
      draft, then finish only if there are no unknown Dialog/Choice groups.

It deliberately does not invent translations for new Japanese text. Exact JP
matches and known graph-label name fixes are safe automation; new prose still
needs review.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import group_review  # noqa: E402
import translate as translate_mod  # noqa: E402
from sanitize import sanitize  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
JSON_DIR = ROOT / "translated_sergio_playable_wrapped"
BIN_DIR = ROOT / "Game Files/data/scr/bin"
PATCHED_BIN_DIR = ROOT / "patched_bins_sergio_wrapped/data/scr/bin"
BUILD_DIR = ROOT / "build/ouran-sergio-wrapped"
BUILD_BIN_DIR = BUILD_DIR / "data/scr/bin"
NDSTOOL = ROOT / "tools/bin/ndstool"
ENCODING = "shiftjis"

NAME_MAP = {
    "鏡夜": "Kyoya",
    "光邦": "Honey",
    "崇": "Mori",
    "光": "Hikaru",
    "馨": "Kaoru",
    "環": "Tamaki",
    "小百合": "Sayuri",
    "真嶋": "Majima",
    "倉賀野": "Kurakano",
    "桜塚": "Sakurazuka",
    "上賀茂": "Kamikamo",
}

ARTIFACT_RE = re.compile(
    r"fuck|\bshit\b|\bpiss\b|ass off|pervert|zipper|"
    r"Honeysuckle|Honya|Kobayashi|Shim|Mashima|Morii|Hikokuni|Chong|"
    r"Ring-senpai|Rinko|Koyuri|Koharu|Himegami|Mirror Night|"
    r"Headed for|relaxed as hell|starter|Haruhiko|Shinjima|Kaguya|"
    r"Kuraoka|Light's|Left Blue|Blue's place|I'm so horny|Uwajima|"
    r"Kouta|Koutou|Kukano|Kazuyuki|Koyuki|KAMIGamo|Masataka|"
    r"Senpai Kan|Kan's|Mochu|Ussy|Yamazaka|Miki-senpai|MORIZUMI",
    re.I,
)


def run(cmd: list[str], cwd: Path = ROOT, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, text=True, check=check)


def load_json(path: Path) -> dict:
    with path.open(encoding=ENCODING) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with path.open("w", encoding=ENCODING) as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def normalize_en(text: str) -> str:
    return " ".join((text or "").split())


def group_records(json_path: Path) -> list[dict]:
    data = load_json(json_path)
    pts = data["pointers"]
    out = []
    for gid, ids in enumerate(group_review.build_groups(pts)):
        first = pts[ids[0]]
        out.append(
            {
                "gid": gid,
                "ids": ids,
                "type": first.get("Type"),
                "jp": "".join(pts[i].get("Original Text", "") for i in ids),
                "en": normalize_en(" ".join(pts[i].get("New Text", "") for i in ids)),
                "status": {pts[i].get("Status") for i in ids},
                "note": {pts[i].get("Note") for i in ids},
            }
        )
    return out


def reviewed_memory(exclude: Path | None = None) -> dict[str, str]:
    """Return exact JP -> English memory from already reviewed Dialog/Choice groups."""
    memory: dict[str, str] = {}
    conflicts: set[str] = set()
    for path in sorted(JSON_DIR.glob("*.json")):
        if exclude and path.resolve() == exclude.resolve():
            continue
        for rec in group_records(path):
            if rec["type"] not in ("Dialog", "Choice"):
                continue
            if not rec["en"]:
                continue
            if not (rec["status"] & {"ai", "approved"}):
                continue
            jp = rec["jp"]
            en = rec["en"]
            if jp in memory and memory[jp] != en:
                conflicts.add(jp)
                memory.pop(jp, None)
            elif jp not in conflicts:
                memory[jp] = en
    return memory


def paths_for(file_name: str) -> tuple[Path, Path, Path, Path]:
    stem = Path(file_name).stem
    json_path = JSON_DIR / file_name
    return (
        json_path,
        Path("/tmp") / f"{stem}_backup.json",
        Path("/tmp") / f"{stem}_groups.jsonl",
        Path("/tmp") / f"{stem}_reviewed.jsonl",
    )


def draft(file_name: str) -> int:
    json_path, backup_path, groups_path, reviewed_path = paths_for(file_name)
    if not json_path.exists():
        raise SystemExit(f"missing JSON: {json_path}")

    shutil.copy2(json_path, backup_path)
    group_review.export(str(json_path), str(groups_path))

    memory = reviewed_memory(exclude=json_path)
    todo_path = Path("/tmp") / f"{json_path.stem}_todo.jsonl"
    reviewed = []
    todo = []
    for rec in group_records(json_path):
        if rec["type"] not in ("Dialog", "Choice"):
            continue
        en = memory.get(rec["jp"], "")
        out = {"gid": rec["gid"], "en": en}
        reviewed.append(out)
        if not en:
            todo.append(
                {
                    "gid": rec["gid"],
                    "type": rec["type"],
                    "boxes": len(rec["ids"]),
                    "jp": rec["jp"],
                    "cur": rec["en"],
                }
            )

    with reviewed_path.open("w", encoding="utf-8") as f:
        for rec in reviewed:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    with todo_path.open("w", encoding="utf-8") as f:
        for rec in todo:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    filled = len(reviewed) - len(todo)
    print(f"backup: {backup_path}")
    print(f"groups:  {groups_path}")
    print(f"review:  {reviewed_path}")
    print(f"todo:    {todo_path}")
    print(f"prefilled {filled}/{len(reviewed)} Dialog/Choice groups; todo {len(todo)}")
    return len(todo)


GROUP_SYSTEM_PROMPT = (
    "You are a professional localizer translating dialogue from the Nintendo DS "
    "visual novel Ouran High School Host Club (Japanese to English). You will be "
    "given one full Japanese sentence (already joined across textboxes) and must "
    "return only its natural English translation, nothing else -- no notes, no "
    "romanization, no alternate translations.\n\n"
    "Rules:\n"
    "- No quote brackets around spoken lines.\n"
    "- Keep honorifics: -senpai, -kun, -chan, -san, -sama.\n"
    "- Character name glossary -- use these exact romanizations, never invent "
    "alternates: 環=Tamaki, 鏡夜=Kyoya, 光=Hikaru, 馨=Kaoru, 光邦=Honey (Mitsukuni), "
    "崇=Mori (Takashi), 小百合=Sayuri (Sayuri Himemiya), 真嶋=Majima (Junichi Majima), "
    "倉賀野=Kurakano, 上賀茂=Kamikamo, ハルヒ=Haruhi.\n"
    "- Match character voice: Haruhi is deadpan/casual first-person narration; "
    "Tamaki is theatrical and princely, calls Haruhi 'my princess' or refers to "
    "her as his daughter; Kyoya is polished and faintly menacing; Hikaru/Kaoru "
    "are snarky and teasing; Honey is childlike with exclamation marks and can "
    "use musical note symbols; Mori speaks in terse fragments; Renge is a haughty otaku.\n"
    "- Preserve in-text format codes like #Color[7] or #Scale[1.4] verbatim, in "
    "the same position in the sentence.\n"
    "- Output must be Shift-JIS safe: use -- instead of an em dash, no accented "
    "Latin letters, no curly ellipsis character (use ...).\n"
    "- If the source is a short menu choice, keep the translation under 30 "
    "characters, imperative mood.\n"
)


def auto(file_name: str, api_url: str, api_model: str, api_key: str, limit: int | None = None) -> None:
    json_path, _, _, reviewed_path = paths_for(file_name)
    stem = Path(file_name).stem
    todo_path = Path("/tmp") / f"{stem}_todo.jsonl"
    # Always redraft: a stale /tmp/*_todo.jsonl from an earlier session has gid
    # numbers keyed to whatever grouping logic existed back then. If grouping
    # ever changes (or the file was touched since), stale gids silently
    # misalign and merge() splices the wrong English into the wrong textboxes.
    # draft() is cheap (just re-exports from the current file), so always run it.
    draft(file_name)
    recs = [json.loads(line) for line in todo_path.open(encoding="utf-8") if line.strip()]
    if limit:
        recs = recs[:limit]
    if not recs:
        print("todo is empty; nothing to translate")
        return

    existing = [json.loads(line) for line in reviewed_path.open(encoding="utf-8") if line.strip()]
    by_gid = {rec["gid"]: rec for rec in existing}

    engine = translate_mod.SugoiApiEngine(api_url, api_model, api_key, system_prompt=GROUP_SYSTEM_PROMPT)

    filled = 0
    failed = []
    for i, rec in enumerate(recs):
        jp = rec["jp"]
        try:
            out = sanitize(engine(jp).strip())
            if translate_mod.has_japanese(out) or not out:
                raise ValueError("empty or still contains Japanese")
        except Exception as e:  # noqa: BLE001 - keep going, report at the end
            print(f"[{i+1}/{len(recs)}] gid {rec['gid']} FAILED: {e}")
            failed.append(rec["gid"])
            continue
        by_gid[rec["gid"]] = {"gid": rec["gid"], "en": normalize_en(out)}
        filled += 1
        if (i + 1) % 25 == 0 or i + 1 == len(recs):
            print(f"[{i+1}/{len(recs)}] translated (gid {rec['gid']})")

    merged = [by_gid[gid] for gid in sorted(by_gid)]
    with reviewed_path.open("w", encoding="utf-8") as f:
        for rec in merged:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"auto: {filled}/{len(recs)} translated via {api_model}, {len(failed)} failed")
    if failed:
        print("FAILED gids (left blank, need manual/AI fill):", failed[:40])
    else:
        print(f"ready: .venv/bin/python tools/retranslate_next.py finish {file_name}")


def fix_labels(json_path: Path) -> int:
    data = load_json(json_path)
    changed = 0
    for p in data["pointers"]:
        if p.get("Type") in ("Dialog", "Choice", "Speaker"):
            continue
        orig = p.get("Original Text")
        if orig in NAME_MAP and p.get("New Text") != NAME_MAP[orig]:
            p["New Text"] = NAME_MAP[orig]
            p["Status"] = "ai"
            p["Note"] = "retranslation pass label fix"
            changed += 1
    if changed:
        save_json(json_path, data)
    print(f"label fixes: {changed}")
    return changed


def scan_artifacts(json_path: Path) -> list[tuple[int, object, str, str]]:
    data = load_json(json_path)
    hits = []
    for idx, p in enumerate(data["pointers"]):
        text = p.get("New Text") or ""
        if ARTIFACT_RE.search(text):
            hits.append((idx, p.get("Type"), p.get("Original Text", ""), text))
    if hits:
        print(f"artifact hits: {len(hits)}")
        for idx, typ, orig, text in hits[:80]:
            print(f"--- {idx} {typ}\nORIG {orig}\nEN {text}")
    else:
        print("artifact hits: 0")
    return hits


def layout_qa() -> None:
    run(
        [
            sys.executable,
            "tools/layout_qa_report.py",
            str(JSON_DIR.relative_to(ROOT)),
            "--out-prefix",
            "transcripts/layout_qa_check",
        ]
    )


def rebuild() -> None:
    run(
        [
            sys.executable,
            "tools/insert_all_scripts.py",
            "--json-dir",
            str(JSON_DIR.relative_to(ROOT)),
            "--bin-dir",
            str(BIN_DIR.relative_to(ROOT)),
            "--out-dir",
            str(PATCHED_BIN_DIR.relative_to(ROOT)),
        ]
    )
    BUILD_BIN_DIR.mkdir(parents=True, exist_ok=True)
    for path in PATCHED_BIN_DIR.glob("*.bin"):
        shutil.copy2(path, BUILD_BIN_DIR / path.name)
    run(
        [
            str(NDSTOOL),
            "-c",
            "ouran-sergio-wrapped.nds",
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
        cwd=BUILD_DIR,
    )
    info = subprocess.check_output(
        [str(NDSTOOL), "-i", "ouran-sergio-wrapped.nds"], cwd=BUILD_DIR, text=True
    )
    for line in info.splitlines():
        if "Header CRC" in line or "Banner CRC 0" in line:
            print(line)


def finish(file_name: str, allow_artifacts: bool = False) -> None:
    json_path, _, _, reviewed_path = paths_for(file_name)
    if not reviewed_path.exists():
        raise SystemExit(f"missing reviewed JSONL: {reviewed_path}")
    group_review.merge(str(json_path), str(reviewed_path), note="retranslation pass")
    fix_labels(json_path)
    layout_qa()
    hits = scan_artifacts(json_path)
    if hits and not allow_artifacts:
        raise SystemExit("artifact scan has hits; fix them or rerun with --allow-artifacts")
    rebuild()


CHUNK_LETTERS = "abcdefghij"


def split(file_name: str, chunks: int) -> None:
    stem = Path(file_name).stem
    todo_path = Path("/tmp") / f"{stem}_todo.jsonl"
    if not todo_path.exists():
        raise SystemExit(f"missing todo JSONL (run draft first): {todo_path}")
    recs = [json.loads(line) for line in todo_path.open(encoding="utf-8") if line.strip()]
    if not recs:
        print("todo is empty; nothing to split")
        return
    if chunks > len(CHUNK_LETTERS):
        raise SystemExit(f"too many chunks (max {len(CHUNK_LETTERS)})")
    n = min(chunks, len(recs))
    size = -(-len(recs) // n)  # ceil
    paths = []
    for i in range(n):
        part = recs[i * size : (i + 1) * size]
        if not part:
            continue
        letter = CHUNK_LETTERS[i]
        out_path = Path("/tmp") / f"{stem}_todo_{letter}.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for rec in part:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        paths.append((letter, out_path, part[0]["gid"], part[-1]["gid"], len(part)))

    print(f"split {len(recs)} todo groups into {len(paths)} chunk(s):")
    for letter, out_path, first_gid, last_gid, count in paths:
        out_jsonl = Path("/tmp") / f"{stem}_chunk_{letter}.jsonl"
        print(f"  {letter}: {out_path}  ({count} groups, gid {first_gid}-{last_gid})")
        print(f"     -> worker must write {out_jsonl}")
    print()
    print("Each worker prompt should say: read <todo chunk>, translate per")
    print("TRANSLATION_GUIDE.md, write ONE JSONL line per record to <output path>")
    print('as {"gid": N, "en": "..."} in the SAME gid order, and touch no other files.')


def integrate(file_name: str, chunks: int) -> None:
    _, _, _, reviewed_path = paths_for(file_name)
    stem = Path(file_name).stem
    todo_path = Path("/tmp") / f"{stem}_todo.jsonl"
    if not reviewed_path.exists():
        raise SystemExit(f"missing prefilled reviewed JSONL (run draft first): {reviewed_path}")
    if not todo_path.exists():
        raise SystemExit(f"missing todo JSONL: {todo_path}")

    todo_gids = {json.loads(line)["gid"] for line in todo_path.open(encoding="utf-8") if line.strip()}

    collected: dict[int, str] = {}
    dups: set[int] = set()
    for i in range(min(chunks, len(CHUNK_LETTERS))):
        letter = CHUNK_LETTERS[i]
        chunk_path = Path("/tmp") / f"{stem}_chunk_{letter}.jsonl"
        if not chunk_path.exists():
            continue
        for line in chunk_path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            gid = rec["gid"]
            en = normalize_en(rec.get("en", ""))
            if gid in collected:
                dups.add(gid)
            collected[gid] = en

    missing = sorted(todo_gids - collected.keys())
    blank = sorted(gid for gid in todo_gids & collected.keys() if not collected[gid])
    extra = sorted(collected.keys() - todo_gids)

    print(f"todo {len(todo_gids)}  collected {len(collected)}  missing {len(missing)}  "
          f"blank {len(blank)}  dups {len(dups)}  extra {len(extra)}")
    if missing:
        print("MISSING gids:", missing[:40], "..." if len(missing) > 40 else "")
    if blank:
        print("BLANK gids:", blank[:40], "..." if len(blank) > 40 else "")
    if dups:
        print("DUP gids:", sorted(dups)[:40])
    if extra:
        print("EXTRA gids (not in todo, ignored):", extra[:40])

    if missing or blank:
        raise SystemExit("integration incomplete; fix the chunk file(s) above and rerun")

    # Merge collected translations into the reviewed JSONL (which already has
    # prefilled exact matches from draft) without disturbing other rows.
    existing = [json.loads(line) for line in reviewed_path.open(encoding="utf-8") if line.strip()]
    by_gid = {rec["gid"]: rec for rec in existing}
    for gid, en in collected.items():
        by_gid[gid] = {"gid": gid, "en": en}
    merged = [by_gid[gid] for gid in sorted(by_gid)]
    with reviewed_path.open("w", encoding="utf-8") as f:
        for rec in merged:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    still_blank = sorted(rec["gid"] for rec in merged if not rec.get("en"))
    print(f"reviewed.jsonl updated: {len(merged)} rows, {len(still_blank)} still blank")
    if still_blank:
        print("STILL BLANK:", still_blank[:40])
    else:
        print(f"ready: .venv/bin/python tools/retranslate_next.py finish {file_name}")


def remaining_from(file_name: str) -> None:
    files = sorted(p.name for p in JSON_DIR.glob("*.json"))
    remaining = [name for name in files if name >= file_name]
    print(f"remaining from {file_name} inclusive: {len(remaining)}")
    for name in remaining:
        print(name)


def batch(file_name: str, api_url: str, api_model: str, api_key: str) -> None:
    """Run auto+finish over every file from file_name onward, in order.

    Stops (without losing any completed work) the moment a file's finish step
    flags something -- that file is left half-merged in /tmp for a human/AI to
    patch and resume with `finish <file> --allow-artifacts` or by editing the
    reviewed JSONL and rerunning `finish`.
    """
    files = sorted(p.name for p in JSON_DIR.glob("*.json"))
    remaining = [name for name in files if name >= file_name]
    print(f"batch: {len(remaining)} file(s) starting at {file_name}")
    for i, name in enumerate(remaining):
        print(f"\n=== [{i+1}/{len(remaining)}] {name} ===")
        auto(name, api_url, api_model, api_key)
        try:
            finish(name)
        except SystemExit as e:
            print(f"\nSTOPPED at {name}: {e}")
            print(f"Fix flagged lines, then: .venv/bin/python tools/retranslate_next.py finish {name}")
            print(f"...then resume with: .venv/bin/python tools/retranslate_next.py batch {name}")
            return
    print(f"\nbatch complete: {len(remaining)} file(s) processed through {remaining[-1]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("draft", "run", "remaining"):
        p = sub.add_parser(name)
        p.add_argument("file")
    pf = sub.add_parser("finish")
    pf.add_argument("file")
    pf.add_argument("--allow-artifacts", action="store_true")
    ps = sub.add_parser("split")
    ps.add_argument("file")
    ps.add_argument("--chunks", type=int, default=5)
    pi = sub.add_parser("integrate")
    pi.add_argument("file")
    pi.add_argument("--chunks", type=int, default=5)
    pa = sub.add_parser("auto")
    pa.add_argument("file")
    pa.add_argument("--api-url", default="http://localhost:11434/v1")
    pa.add_argument("--api-model", default="sugoi-14b")
    pa.add_argument("--api-key", default="sk-dummy")
    pa.add_argument("--limit", type=int, default=None, help="translate at most N groups (testing)")
    pb = sub.add_parser("batch")
    pb.add_argument("file", help="first file to process (inclusive); use ls order, e.g. 112_3_2.json")
    pb.add_argument("--api-url", default="http://localhost:11434/v1")
    pb.add_argument("--api-model", default="sugoi-14b")
    pb.add_argument("--api-key", default="sk-dummy")
    args = ap.parse_args(argv)

    if args.cmd == "draft":
        return 1 if draft(args.file) else 0
    if args.cmd == "auto":
        auto(args.file, args.api_url, args.api_model, args.api_key, limit=args.limit)
        return 0
    if args.cmd == "batch":
        batch(args.file, args.api_url, args.api_model, args.api_key)
        return 0
    if args.cmd == "finish":
        finish(args.file, allow_artifacts=args.allow_artifacts)
        return 0
    if args.cmd == "run":
        todo = draft(args.file)
        if todo:
            print("stopping before merge because todo groups remain")
            return 1
        finish(args.file)
        return 0
    if args.cmd == "remaining":
        remaining_from(args.file)
        return 0
    if args.cmd == "split":
        split(args.file, args.chunks)
        return 0
    if args.cmd == "integrate":
        integrate(args.file, args.chunks)
        return 0
    raise AssertionError(args.cmd)


if __name__ == "__main__":
    raise SystemExit(main())
