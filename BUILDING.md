# Building Locally

These notes are for maintainers rebuilding the patch from a legally dumped Japanese ROM. The public community source package intentionally does not contain original game assets or rebuilt ROMs.

## Requirements

- Python 3.11 or newer.
- Python packages from `requirements.txt`.
- A legally dumped Japanese copy of *Ouran High School Host Club* for Nintendo DS.
- Local extraction/repacking setup. This workspace uses `tools/bin/ndstool`.

## Expected Local Paths

The scripts in this workspace expect these local-only folders:

- `Game Files/` - unpacked original game files.
- `Game Files/data/scr/bin/` - original script binaries.
- `Game Files/data/fonts/LD937714LD937742.NFTR` - original dialogue font.
- `translated_sergio_playable_wrapped/` - current English script JSON.
- `patched_bins_sergio_wrapped/` - generated patched script binaries.
- `build/` - local ROM build output.

These paths are ignored by git where they contain game data or generated output.

## Insert The Current English Scripts

```bash
.venv/bin/python tools/insert_all_scripts.py \
  --json-dir translated_sergio_playable_wrapped \
  --bin-dir "Game Files/data/scr/bin" \
  --out-dir patched_bins_sergio_wrapped/data/scr/bin
```

The insertion tool preserves intentionally blank continuation pointers through the `_force_empty` marker in the JSON.

## Build The Narrow Dialogue Font

Normal dialogue does not parse `#Scale[...]`. The adopted fix is a readable narrow variant of the game's dialogue font, generated locally from the extracted font file:

```bash
.venv/bin/python tools/make_narrow_font.py \
  --src "Game Files/data/fonts/LD937714LD937742.NFTR" \
  --out build/testfonts/LD_narrow4.NFTR
```

The font renderer details are documented in `FONT_AUDIT.md`.

## Layout QA

Run the pixel-aware layout report with the narrow font:

```bash
.venv/bin/python tools/layout_qa_report.py translated_sergio_playable_wrapped \
  --font build/testfonts/LD_narrow4.NFTR \
  --out-prefix transcripts/layout_qa_current_narrow4
```

As of July 2, 2026, this report flags 65 rows for review with the current narrow-font setup.

## Player Patch

For public testing, distribute a binary patch such as `release/ouran_en_patch.bsdiff`, not a ROM. The player-facing instructions are in `release/README.md`.
