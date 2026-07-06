# Art Localization Workflow

The game art is stored as Nintendo DS tiled graphics, mostly `NCGR` image data plus matching `NCLR` palettes. Some screens also use `NSCR` screen maps to arrange those tiles. ComfyUI can help generate or inpaint translated art, but it cannot directly edit DS assets. The reliable pipeline is:

1. Render composed `NSCR` screens to PNG where possible.
2. Export raw tile sheets only when you need the underlying editable `NCGR`.
3. Identify which screens/sheets contain Japanese text or logos.
3. Create/edit translated PNGs with ComfyUI or manual art tools.
4. Quantize the edited PNG back to the original DS palette and tile order.
5. Replace the matching `NCGR` in the local build and rebuild the ROM.
6. Test in emulator.

## Render Composed Screens

Start here for UI/background art. These PNGs look like the actual player-facing
screens instead of scrambled tile storage.

```bash
.venv/bin/python tools/nitro_render.py render-all-nscr "Game Files/data" art_work/composed_nscr
```

This creates:

- `art_work/composed_nscr/**.png`
- `art_work/composed_nscr/manifest.csv`

Use these composed PNGs as ComfyUI/reference inputs. The manifest tells you
which `NCGR`, `NCLR`, and `NSCR` created each image.

## Export Raw Art Sheets

```bash
.venv/bin/python tools/art_sheet_tool.py export-all "Game Files/data" art_work/exported_sheets
```

This creates:

- `art_work/exported_sheets/**.png`
- `art_work/exported_sheets/manifest.csv`

The PNGs are tile sheets, not always the exact final on-screen composition. They
are useful for low-level round trips, but they are not good ComfyUI inputs for
screen-map UI. Use `tools/nitro_render.py` first when an `NSCR` exists.

## Edit With ComfyUI

Use ComfyUI for the creative part:

- Put the exported PNG or a cropped source image into `/media/joe/m.2/ComfyUI/input/`.
- Use an image-edit/inpaint workflow.
- Preserve the original canvas size.
- Replace only the Japanese text/logo area.
- Keep the background, borders, colors, and DS-era pixel-art feel.
- Export a PNG.

Recommended prompt shape:

```text
Translate the Japanese game UI/art text into English while preserving the original Nintendo DS visual style.
Keep the same canvas size, layout, colors, background, border, lighting, and pixel-art/anime-game texture.
Replace the Japanese text with: "<ENGLISH TEXT>"
Do not add extra decorations. Do not change characters or background art.
Make the English text readable at Nintendo DS resolution.
```

ComfyUI is best for logos, title art, signs, and larger decorative text. For tiny 8x8-tile UI labels, manual pixel editing may be cleaner than AI.

### Optional ComfyUI API Bridge

If you have a workflow that already reproduces images well, export it from ComfyUI in API format and replace the key fields with placeholders:

- input image filename: `__IMAGE__`
- positive prompt: `__PROMPT__`
- negative prompt, if present: `__NEGATIVE__`
- seed: `__SEED__`
- save prefix: `__PREFIX__`

Then queue it from this project:

```bash
.venv/bin/python tools/comfy_art_queue.py path/to/workflow_api.json \
  art_work/composed_nscr/bg/BG_SUB/movie_back.png \
  --prompt 'Translate the Japanese game button text into English: "Touch Start". Preserve the original Nintendo DS UI style, colors, layout, and pixel texture.' \
  --prefix ouran_movie_back \
  --out-dir art_work/comfy_outputs
```

This keeps the game-specific workflow here while letting ComfyUI handle the image recreation.

## Import An Edited Sheet

After producing an edited PNG, convert it back to an NCGR using the original palette:

```bash
.venv/bin/python tools/art_sheet_tool.py import \
  "Game Files/data/bg/BG_SUB/TouchStartBG.NCGR" \
  art_work/edited/TouchStartBG.png \
  art_work/patched_assets/bg/BG_SUB/TouchStartBG.NCGR \
  --nclr "Game Files/data/bg/BG_SUB/TouchStartBG.NCLR"
```

Then copy the patched `NCGR` into the matching path under `build/ouran-sergio-wrapped/data/` and rebuild the ROM.

## Constraints

- The importer keeps the original palette. AI output will be reduced to the game's existing colors unless we also edit the `NCLR`.
- The edited image must keep the same size and tile layout as the asset you import back.
- Composed screen PNGs are currently render/reference outputs. Importing back still needs the matching raw `NCGR` workflow for that asset.
- Imported art should be tested in-game, because sprite and background layers can be arranged differently from the raw files.
- Do not include original extracted art assets in the public community package.

## Practical Order

1. Start with obvious UI/title assets in `bg/BG_SUB` and `bg/BG_MAIN`.
2. Export and review ending graphics with `tools/export_ed_images.py` or `tools/art_sheet_tool.py`.
3. Patch one asset end-to-end before batching more.
4. Once one round-trip looks good in emulator, batch the remaining text art.
