# Package Manifest

Community source package generated on 2026-07-02 (v3).

Included:

- `translated_sergio_playable_wrapped/` - current translated script JSON.
- `tools/` - Python source tools and small JSON support files.
- `tools/nitro_render.py` - composed Nitro `NCGR`/`NCLR`/`NSCR` screen renderer plus `NCER` cell/sprite (UI button) renderer, for art-localization reference PNGs.
- `tools/patch_ncer_text.py` - redraws translated English text into `NCER` sprite cells (UI buttons/labels) and repacks it into a patched `NCGR`.
- `tools/translate_ui_strings.py` - translates short UI/menu label strings via the local Sugoi-14B API (separate prompt from dialogue translation).
- `tools/ui_text_cells.json`, `tools/ui_strings_source.json`, `tools/ui_strings_translated.json`, `tools/ui_names_translated.json` - the UI text extraction/translation manifest and glossary produced by the above tools.
- `art_work/ui_translated/` - **exception to the art_work/ exclusion below.** Contains patched `.NCGR` files and before/after PNGs for the translated UI buttons/menus under `Game Files/data/ui/`. These patched files are structurally the original Japanese game's graphics files with specific button-label pixels redrawn to English (not a diff) - unlike the general `art_work/` exclusion, this was a deliberate inclusion decision for this release. Anyone re-packaging from this source should be aware these files embed original game art, not just original tooling.
- `release/ouran_en_patch.bsdiff` - recommended current player patch with narrow font/layout fixes.
- `release/ouran_en_patch_stockfont_pre_narrow4.bsdiff` - optional legacy stock-font patch from before the final fitting pass.
- `release/full_translation_review.csv` - review spreadsheet.
- `release/review_transcripts/` - per-file Markdown review transcripts.
- `transcripts/layout_qa_current_narrow4.*` - latest narrow-font layout QA report.
- Project documentation.

Excluded:

- Original game files.
- Built `.nds` ROMs.
- Save files and emulator states.
- Generated build folders.
- Extracted/generated art assets under `art_work/`, except `art_work/ui_translated/` (see above).
- Local Python environments and local model files.
- Generated NFTR font assets.

Use `release/README.md` for player patch instructions and `BUILDING.md` for maintainer build notes.
