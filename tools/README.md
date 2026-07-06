# Tools README

These tools are for maintainers of the Ouran DS English patch. Reviewers do not need them; reviewers should start with `release/START_HERE_REVIEWERS.txt`.

Most scripts assume they are run from the project root:

```bash
cd /media/joe/m.2/amanda
```

## Reviewer Packet

### `make_reviewer_packet.py`

Builds the no-install reviewer files in `release/`:

- `START_HERE_REVIEWERS.txt`
- `reviewer_editor.html`
- `reviewer_feedback_template.csv`
- `reviewer_chapter_csvs/`

Run after updating `release/full_translation_review.csv`:

```bash
.venv/bin/python tools/make_reviewer_packet.py
```

## Current Layout And Text QA

### `layout_qa_report.py`

Scans translated JSON for textbox risks: too many lines, text too wide, leftover Japanese, likely name problems, blank translated rows, and model-output artifacts.

Use the narrow font for the current accurate pixel-aware report:

```bash
.venv/bin/python tools/layout_qa_report.py translated_sergio_playable_wrapped \
  --font build/testfonts/LD_narrow4.NFTR \
  --out-prefix transcripts/layout_qa_current_narrow4
```

### `auto_fit_text.py`

Automatically shortens or rewrites overlong dialogue groups. Default mode only does conservative rewrapping. `--use-model` calls a local OpenAI-compatible endpoint such as Ollama/Sugoi.

Use with review. It can improve fitting, but model output still needs checking for names, tone, and meaning.

```bash
.venv/bin/python tools/auto_fit_text.py translated_sergio_playable_wrapped --file 101_1_1.json --limit 25 --use-model
```

### `apply_layout_fixes.py`

Applies manually reviewed layout fixes from JSONL.

Input format:

```json
{"file":"101_1_1.json","ids":[658,659,660],"en":"Short English line."}
```

It wraps text, writes the displayed text into the first pointer, blanks continuation pointers with `_force_empty`, and refuses fixes that still do not fit.

### `wrap_playable_text.py`

Conservative word-boundary wrapping pass for playable JSON. It handles the game's habit of joining consecutive dialog fragments into one displayed textbox, and blanks continuation fragments to prevent combined words.

### `scale_layout_fails.py`

Maintainer-only and rarely useful. Applies `#Scale[...]` only to formatted overlay rows.

Do not use this for normal dialogue. Normal dialogue prints `#Scale[...]` literally.

## Translation And Review Workflow

### `group_review.py`

Exports and merges sentence groups for proper review. The game often splits one Japanese sentence across several script pointers; this tool joins those fragments so a reviewer sees the whole sentence.

Common flow:

```bash
.venv/bin/python tools/group_review.py export translated_sergio_playable_wrapped/FILE.json /tmp/FILE_groups.jsonl
.venv/bin/python tools/group_review.py merge translated_sergio_playable_wrapped/FILE.json /tmp/FILE_reviewed.jsonl --note "review pass"
```

### `retranslate_next.py`

Automates the repeatable parts of the group retranslation workflow: draft, local machine translation, merge, QA, and rebuild helpers. This is a maintainer convenience tool, not a reviewer tool.

### `ai_review.py`

Exports compact JSONL records for an external AI or another review pass, then merges corrected English back into a JSON file. It does not call any AI service by itself.

### `review_server.py`

Local Flask web workbench for editing translation JSON directly in the browser. It is for maintainers who are comfortable running a local server.

```bash
.venv/bin/python tools/review_server.py --dir translated_sergio_playable_wrapped --port 5000
```

Then open `http://127.0.0.1:5000`.

### `translate.py`

Original offline first-pass translation tool using Argos JA-to-EN. This is mostly historical now; the current script set is already translated and reviewed further.

### `translation_progress.py`

Reports translation progress/status counts for a JSON folder.

```bash
.venv/bin/python tools/translation_progress.py translated_sergio_playable_wrapped
```

### `status_model.py`

Shared helper for translation status fields. Imported by other tools.

### `sanitize.py`

Shared Shift-JIS safety helper. Imported by insertion/review tools to replace unsafe characters such as em dashes and ellipsis glyphs with game-safe equivalents.

## Script Extraction And ROM Rebuild

### `ouran_tool.py`

Core extractor/inserter for Ouran script `.bin` files. It is a refactor of the original community extraction logic. Most maintainers should call it through `insert_all_scripts.py`.

Useful direct commands:

```bash
.venv/bin/python tools/ouran_tool.py extract "Game Files/data/scr/bin/101_1_1.bin" /tmp/101_1_1.json
.venv/bin/python tools/ouran_tool.py insert "Game Files/data/scr/bin/101_1_1.bin" translated_sergio_playable_wrapped/101_1_1.json /tmp/101_1_1.bin
```

### `insert_all_scripts.py`

Batch-inserts every translated JSON file into matching script binaries.

```bash
.venv/bin/python tools/insert_all_scripts.py \
  --json-dir translated_sergio_playable_wrapped \
  --bin-dir "Game Files/data/scr/bin" \
  --out-dir patched_bins_sergio_wrapped/data/scr/bin
```

After this, copy the patched `.bin` files into the build directory and repack the ROM as described in `BUILDING.md`.

### `make_layout_test_rom.py`

Builds a temporary test ROM that injects one target layout line near the start of the game. Useful when a tester needs to jump straight to a specific textbox without playing through the route.

Output:

```text
build/ouran-layout-test/ouran-layout-test.nds
```

## Font Tools

### `make_narrow_font.py`

Builds the current readable narrow ASCII dialogue font from the user's own extracted `LD937714LD937742.NFTR`.

```bash
.venv/bin/python tools/make_narrow_font.py \
  --src "Game Files/data/fonts/LD937714LD937742.NFTR" \
  --out build/testfonts/LD_narrow4.NFTR
```

This is the current recommended font/layout fix.

### `nftr_tool.py`

Low-level NFTR inspector/editor. Can dump font info, dump ASCII widths, render a glyph sheet, or create older metric-only narrow font experiments.

For the current patch, prefer `make_narrow_font.py`. The old metric-only narrowing made text hard to read because the dialogue blitter clipped columns.

### `ascii_width_table.json`

Exported ASCII width data used during font/layout analysis. It is reference data, not a script.

## Graphics Helpers

### `nitro_render.py`

Renders composed Nitro `NCGR` + `NCLR` + `NSCR` background screens to PNG.
Use this before ComfyUI for screen-map assets; these are actual player-facing
screens, unlike raw tile sheets.

```bash
.venv/bin/python tools/nitro_render.py render-all-nscr "Game Files/data" art_work/composed_nscr
```

Single-screen example:

```bash
.venv/bin/python tools/nitro_render.py render-nscr \
  "Game Files/data/bg/BG_SUB/movie_back.NSCR" \
  art_work/composed_nscr/bg/BG_SUB/movie_back.png
```

The generated `art_work/composed_nscr/manifest.csv` records which `NCGR`,
`NCLR`, and `NSCR` files were combined. This renderer is currently for
background screen maps, not NCER/NANR sprite buttons.

### `art_sheet_tool.py`

Exports and imports simple Nintendo DS `NCGR`/`NCLR` 4bpp tile sheets as PNGs.

Use it for raw tile-sheet round trips after you know which underlying `NCGR`
needs editing:

```bash
.venv/bin/python tools/art_sheet_tool.py export-all "Game Files/data" art_work/exported_sheets
```

Do not feed these raw sheets to ComfyUI as the first pass for UI screens. Many
of them are tile storage, not the final on-screen layout.

Use the `import` subcommand to quantize an edited PNG back into the original tile/palette format. See `ART_LOCALIZATION.md`.

### `comfy_art_queue.py`

Generic ComfyUI API bridge for art-localization images. It uploads an exported PNG to ComfyUI, applies placeholders in an API-format workflow, queues the prompt, waits for output, and downloads the result.

It expects a workflow you exported from ComfyUI with placeholders such as `__IMAGE__`, `__PROMPT__`, `__SEED__`, and `__PREFIX__`.

### `export_ed_images.py`

Renders ending graphics from `ED_*.NCGR` and matching `NCLR` palettes into PNG contact sheets for visual review. Requires Pillow.

```bash
.venv/bin/pip install pillow
.venv/bin/python tools/export_ed_images.py
```

## Data Files

### `glossary.json`

Shared name/term glossary used by translation and review tools.

### `bin/ndstool`

Local Nintendo DS packing/unpacking binary used by maintainer build commands. The community source zip excludes this binary, so contributors may need their own `ndstool` depending on their platform.

### `melonds-libs/`

Local emulator runtime libraries. These are local-only and excluded from the community source zip.
