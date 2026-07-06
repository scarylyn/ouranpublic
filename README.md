# Ouran DS English Translation Project

Community working files for an English fan translation of *Ouran High School Host Club* for Nintendo DS.

This repository is intended to share the translation text, review materials, and tooling. It should not include original game files, unpacked ROM data, or built `.nds` ROMs.

## Current Status

- Playable English patch exists in `release/ouran_en_patch.bsdiff`.
- Current translated script source is `translated_sergio_playable_wrapped/`.
- Current player-facing release notes are in `release/README.md`.
- Review CSV and chapter transcripts are in `release/full_translation_review.csv` and `release/review_transcripts/`.
- Low-tech reviewer files are in `release/START_HERE_REVIEWERS.txt`, `release/reviewer_editor.html`, `release/reviewer_feedback_template.csv`, and `release/reviewer_chapter_csvs/`.
- Dialogue uses the readable narrow font workflow documented in `FONT_AUDIT.md`.
- Latest pixel-aware layout QA with the narrow font found 65 rows still worth checking: `transcripts/layout_qa_current_narrow4.html`.

## What To Share

For players and testers, share the contents of `release/` except any `.nds` or save files. The patch file is safe to distribute; the ROM is not.

For translators, editors, and tool contributors, share the generated source bundle under `release/community_source_YYYYMMDD/` or the matching `.zip` archive. It contains the translation JSON, tools, docs, and review material without ROMs or original game assets.

## Important Legal Boundary

This project does not grant permission to distribute Nintendo DS ROMs or original game assets. Anyone applying the patch needs their own legally dumped Japanese copy of the game.

See `LEGAL.md` for the project packaging rule.

## Common Commands

Run layout QA against the current translated script using the narrow font:

```bash
.venv/bin/python tools/layout_qa_report.py translated_sergio_playable_wrapped \
  --font build/testfonts/LD_narrow4.NFTR \
  --out-prefix transcripts/layout_qa_current_narrow4
```

Insert translated JSON back into script binaries from a local unpacked copy:

```bash
.venv/bin/python tools/insert_all_scripts.py \
  --json-dir translated_sergio_playable_wrapped \
  --bin-dir "Game Files/data/scr/bin" \
  --out-dir patched_bins_sergio_wrapped/data/scr/bin
```

Build the readable narrow dialogue font from your own extracted font backup:

```bash
.venv/bin/python tools/make_narrow_font.py \
  --src "Game Files/data/fonts/LD937714LD937742.NFTR" \
  --out build/testfonts/LD_narrow4.NFTR
```

## Documentation

- `BUILDING.md` - local build notes for maintainers.
- `TRANSLATION_GUIDE.md` - naming, voice, and style rules.
- `FONT_AUDIT.md` - how the dialogue renderer and narrow font work.
- `WORKFLOW.md` - translation/review workflow notes.
- `ACKNOWLEDGEMENTS.md` - project credits and original extraction note.
