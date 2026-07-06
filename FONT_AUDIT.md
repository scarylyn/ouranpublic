# Font / Renderer Audit — Normal Dialogue Text Width

Date: 2026-07-02. Goal: can normal dialogue be made narrower globally instead of
shortening every overflowing line?

## TL;DR

- Normal dialogue uses **`data/fonts/LD937714LD937742.NFTR`** (font ID 8). It is the
  only font in the game containing ASCII glyphs (95 chars). The M_10/M_16/M_20 fonts
  are tiny Shift-JIS-only sets (30/90/307 glyphs) used for special screens — a font
  swap is impossible and pointless.
- The dialogue renderer (arm9 `0x203bc18`) is **custom, not the stock NNS text canvas**.
  Per character it advances the pen by `CWDH glyph_w + letter_spacing`, where
  `letter_spacing` is a per-textbox runtime value (field +0xA0, set at `0x208cb84`
  from caller params). It **ignores the CWDH advance byte and the left-bearing byte**.
- Consequence: dialogue is **already proportional by ink width** — `i`, `l`, `1`,
  `.`, `,` already take ~2–4px vs 5px for wide letters. The QA "32 chars" limit is a
  char-count approximation of a pixel budget.
- **No control codes for size/scale exist in the dialogue path.** Handled specials:
  `\n` (0x0A), `~` (0x7E) = fixed 12px blank, space (0x20) and fullwidth space
  (0x8140) = `letter_spacing` px only, and `,` `.` `，` `。` get **+4px pause spacing**.
  Everything else prints literally — which is why `#Scale` shows as text.
- The viable global hack is **reducing the `glyph_w` metric byte** for ASCII (that is
  the byte the renderer actually adds). Test ROM built. Whether the right edge of
  glyphs clips depends on the blit callback (runtime function pointer — not resolved
  statically), so it needs one in-game look.

## Fonts inventory

| file | glyphs | cell | bpp | mapped range | ASCII? | role |
|---|---|---|---|---|---|---|
| LD937714LD937742.NFTR | 7111 | 11×11 | 1 | SJIS 0x20–0xEAA4 | 95 chars, glyph_w 2–5, CWDH advance 6 | main script font (ID 8) |
| M_10_090106.NFTR | 30 | 10×10 | 2 | SJIS only | none | special (ID 0xC) |
| M_16_090106.NFTR | 90 | 15×16 | 2 | SJIS only | none | special (ID 0xE) |
| M_20_090106.NFTR | 307 | 20×20 | 3 | SJIS only | none | title-card-ish (ID 0x12) |

Font ID → slot mapping recovered from the loader at `0x2093814ff` (load order LD,
M_10, M_16, M_20 → struct slots +0x84/+0x88/+0x8C/+0x90) and the getter at
`0x2093ec0`.

## Renderer findings (arm9, ARM, base 0x02000000)

- `0x20997d0` — glyph lookup (CMAP walk); returns 0xFFFF sentinel → falls back to
  FINF alternate char.
- `0x2099818/0x2099844` — CWDH walk; returns pointer to 3-byte entry
  `(left, glyph_w, advance)`.
- `0x203bc18` — **dialogue draw-one-char**:
  - draws glyph bitmap at pen (no left-bearing offset), via callback `blx r4`
    (runtime pointer from textbox+0x18);
  - `pen += glyph_w` (`ldrb r0,[entry,#1]` at 0x203bd38) — *not* the advance byte;
  - `pen += letter_spacing` (+0xA0) unless font ID == 0x12;
  - space/fullwidth-space skip the glyph entirely → width = `letter_spacing`;
  - `,` `.` 0x8141 0x8142 → extra +4px; `~` (0x7E) → fixed +12px, no draw.
- `0x203babc` — line measure loop (font ID 0x12 hardcoded = M_20; used by the
  20px-font screens, same advance formula).
- SDK `NNS_G2dTextCanvas`-style code (`0x209a664`, `0x20998a8`) exists too and *does*
  use the advance byte — that's the formatted/overlay path that understands
  `#Scale/#Color/#Pos`. Two renderers confirmed.

## What this means for each option in the brief

1. **NFTR metrics hack — YES, but on `glyph_w`, not the advance byte.**
   Shrinking the CWDH *advance* byte (classic NFTR trick) does nothing to dialogue.
   Reducing `glyph_w` by 1 on wide ASCII tightens every letter pair by 1px
   (~15–17% narrower text) *if* the blitter doesn't use `glyph_w` as blit width
   (else the right pixel column of glyphs clips → then we'd redraw bitmaps 1px
   narrower, still feasible: 1bpp, trivial to edit with tools/nftr_tool.py).
2. **Font swap — NOT viable.** No other font has ASCII; M_* fonts are the wrong
   sizes and JP-only.
3. **Renderer — no size/scale code exists for dialogue.** Adding one would be an
   arm9 code patch; the cleaner arm9 patch target would be the per-textbox
   `letter_spacing` init (`0x208cb84` region), but spacing also defines the width
   of spaces, so lowering it makes word gaps vanish. Not recommended.
4. **Safe spacing option — this is effectively what the glyph_w hack is.** Bitmap
   shapes and text height stay identical; only inter-letter advance changes.
5. **Risks**: LD is used wherever font ID 8 is used (dialogue, likely choices/name
   labels/menus using the small font) — a narrower ASCII affects all of them
   uniformly; JP glyphs are untouched (only 0x21–0x7E edited). Overlay/formatted
   text (`#Scale` path) reads the *advance* byte, which we leave at 6, so overlays
   are unaffected by the glyph_w variant. Cursor/next-arrow placement keys off pen
   position, so it follows the text naturally. Line-height untouched.

## Space / punctuation advances (asked in the brief)

- Space is **not a glyph** — its width is the textbox's `letter_spacing` value
  (runtime; not readable statically; measure once in-game).
- `,` and `.` advance = glyph_w (2) + spacing + **4 extra**.
- All other ASCII: glyph_w (2–5) + spacing. Full per-char table (left/glyph_w/CWDH
  advance) exported to **`tools/ascii_width_table.json`** for pixel-aware wrapping.

## Pixel-aware wrapping / QA

Effective line width in px = `Σ glyph_w(c) + N·spacing + 4·(count of , .) + 12·(count of ~)`.
Two unknowns remain: `spacing` (probably 1–2) and the textbox pixel budget
(32 × (5 + spacing) suggests ~192–224px). **Calibrate with one in-game test** (below),
then update `tools/layout_qa_report.py` `limits()` to use the formula above with
`tools/ascii_width_table.json` instead of `len() > 32`. Not changed yet on purpose —
wrong constants would silently re-flag/unflag hundreds of rows.

## Test artifacts built (originals backed up, md5-verified)

- Backup: `backups/fonts_20260702/*.NFTR` (originals; game files untouched).
- `build/testfonts/LD_proportional.NFTR` — CWDH *advance* byte made proportional +
  `@` glyph replaced by a solid block (sentinel).
- `build/testfonts/LD_glyphw_minus1.NFTR` — `glyph_w` −1 on the 75 wide ASCII glyphs
  + same `@` sentinel.
- ROMs in `build/ouran-layout-test/`, all show the test line
  `iiiii lllll WWWWW @ I'll fit! 123` in the first prologue textbox:
  - `ouran-layout-test.nds` — stock font (baseline)
  - `ouran-layout-test-font.nds` — advance-byte variant
  - `ouran-layout-test-glyphw.nds` — glyph_w variant  ← the important one
- New tool: `tools/nftr_tool.py` (`info` / `widths` / `render` / `narrow`).

### Manual test procedure (2 min each, melonDS)

```
LD_LIBRARY_PATH=tools/melonds-libs ~/Downloads/melonDS build/ouran-layout-test/ouran-layout-test-glyphw.nds
```

Start a new game, reach the first textbox. Check:
1. Is `@` a solid block? (yes → LD font confirmed as dialogue font)
2. vs baseline ROM: are letters ~1px tighter? Is the last pixel column of `W`/`M` clipped?
3. How wide is the space between words (count pixels vs letter gaps)?
4. Quick side trip: menu, save screen, choice — any misalignment.

Predictions: `-glyphw` ROM = tighter text; `-font` (advance) ROM = no spacing change
at all in dialogue (proves the advance byte is ignored).

### Exact commands used

```
python3 tools/nftr_tool.py info  "Game Files/data/fonts/LD937714LD937742.NFTR"
python3 tools/nftr_tool.py widths "Game Files/data/fonts/LD937714LD937742.NFTR"
python3 tools/nftr_tool.py render "Game Files/data/fonts/LD937714LD937742.NFTR" out.png
python3 tools/make_layout_test_rom.py --file 101_1_1.json --id 67,68 --text "iiiii lllll WWWWW @ I'll fit! 123"
cd build/ouran-layout-test && cp ../testfonts/LD_glyphw_minus1.NFTR data/fonts/LD937714LD937742.NFTR && \
  ../../tools/bin/ndstool -c ouran-layout-test-glyphw.nds -9 arm9.bin -7 arm7.bin -y9 y9.bin -y7 y7.bin \
  -d data -y overlay -t banner.bin -h header.bin
```

(Disassembly done with capstone in `.venv`; renderer analysis notes above.)

## Round 2 (after in-game test of the glyph_w variant)

Joe's screenshot of `-glyphw` showed the bad branch: the blitter blits exactly
`glyph_w` columns, so metric-only narrowing clips the right pixel column of every
letter. Two extra facts extracted from the screenshot by pixel measurement:

- **letter_spacing = 2px** (predicted line widths at s=2 match the screenshot
  exactly at its true 2.5× scale). So stock pitch = 7px/wide char, space = 2px,
  word gap = 4px, and the 32-char limit ≙ **224px textbox budget**.
- Screenshot scale was 2.5×, not window-size/256.

**Variant C — `build/testfonts/LD_narrow4.NFTR`** (built by `tools/make_narrow_font.py`):
57 wide ASCII glyphs redrawn at 4px ink (least-informative-column merge), and
`m w M W @ # $ % & 0 8 D` kept at 5px — the renderer is proportional, so shape-critical
glyphs simply keep their width (this also keeps 8≠B and 0/D≠O). Offline simulator
previews (same blit/advance rules as the game) read cleanly. Effective pitch drops
7→6px for most letters ≈ **+16% capacity (~37 wide chars/line)**.

Test ROM: `build/ouran-layout-test/ouran-layout-test-narrow4.nds` — same manual check
as before (no `@`-sentinel this time; just confirm no clipping and general readability).

`tools/layout_qa_report.py` now has an opt-in pixel mode using these constants:

```
python3 tools/layout_qa_report.py translated_sergio_playable_wrapped \
    --font build/testfonts/LD_narrow4.NFTR --out-prefix transcripts/layout_qa_pixel_narrow4
```

Overflow rows: 68 (old char-count) → 54 (pixel-accurate, stock font — 14 were false
positives) → **46 with the narrow font**. Without `--font` the tool behaves exactly
as before. After the narrow font is confirmed in-game, the right next step is
re-wrapping (`wrap_playable_text.py`) against the pixel budget instead of 32 chars —
that should clear most of the remaining 46 and may let previously shortened lines be
restored.

## Recommendation

1. Run the two test ROMs (5 min). If `glyph_w −1` renders cleanly → adopt it as the
   global fix (~15% more text per line), recalibrate QA to pixel widths, and only
   shorten the lines that still overflow.
2. If the blitter clips: redraw the 75 wide ASCII bitmaps 1px narrower (mechanical,
   scriptable in nftr_tool) and keep the same metric change.
3. Do **not** pursue renderer patches or font swaps; do not bother with the CWDH
   advance byte for dialogue.

## In-game test result

The `glyph_w −1` test ROM was inspected in melonDS. It technically tightened the
dialogue, but the text became hard to read in normal play. The metric-only font
hack should **not** be adopted for the main patch. Continue using the restored
stock dialogue font and fix remaining overflows by shortening/rephrasing text.
