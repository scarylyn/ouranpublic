# UI Art Translation Workflow

Goal: translate the interface art needed for players to navigate the game.

This is separate from decorative CG/title art. The priority is buttons, save/load screens, options, host-mode buttons, logs, and gallery/viewer controls.

## Current State

- ComfyUI is running at `http://127.0.0.1:8188`.
- DS art has been exported to `art_work/exported_sheets/`.
- Composed NSCR screens are rendered to `art_work/composed_nscr/`.
- A composed screen contact sheet is at `art_work/composed_nscr_contact.png`.
- The UI/navigation candidate list is `art_work/ui_art_todo.csv`.
- 4x zoom inspection copies are in `art_work/ui_zoom/`.

## Recommended Approach

For NSCR background screens, use the composed renders first:

```bash
.venv/bin/python tools/nitro_render.py render-all-nscr "Game Files/data" art_work/composed_nscr
```

Use `art_work/composed_nscr_contact.png` to choose which screen needs English
art. These are good reference/ComfyUI inputs because they match the final
screen layout.

For small sprite/button navigation UI, use manual pixel redraw first:

1. Open the 4x zoom PNG in `art_work/ui_zoom/`.
2. Find the Japanese label in the corresponding original sheet under `art_work/exported_sheets/`.
3. Redraw the label in English while preserving the sheet size and palette.
4. Save the edited sheet to `art_work/edited/...`.
5. Convert it back to NCGR with `tools/art_sheet_tool.py import`.
6. Copy the patched NCGR into `build/ouran-sergio-wrapped/data/...`.
7. Rebuild and test in melonDS.

ComfyUI is useful for larger decorative art and full composed screen
backgrounds, but it is usually not the best first choice for tiny DS UI labels.
Small labels need exact readable pixels and palette control.

## Sprite/Button Warning

The title `TouchStartButton` files are NCER/NANR sprite assets, not an NSCR
background. The earlier direct button test produced scrambled text and then a
black-screen build, so do not patch those files again until we have a reliable
NCER/NANR composed sprite renderer.

## First Sprite Asset To Patch Later

Start with:

```text
ui/Title/TouchStartButton
```

Exported PNG:

```text
art_work/exported_sheets/ui/Title/TouchStartButton.png
```

4x zoom:

```text
art_work/ui_zoom/ui/Title/TouchStartButton.png
```

Import command after editing:

```bash
.venv/bin/python tools/art_sheet_tool.py import \
  "Game Files/data/ui/Title/TouchStartButton.NCGR" \
  art_work/edited/ui/Title/TouchStartButton.png \
  art_work/patched_assets/ui/Title/TouchStartButton.NCGR \
  --nclr "Game Files/data/ui/Title/TouchStartButton.NCLR"
```

Then copy:

```bash
cp art_work/patched_assets/ui/Title/TouchStartButton.NCGR \
  build/ouran-sergio-wrapped/data/ui/Title/TouchStartButton.NCGR
```

Rebuild with the normal ROM rebuild command from `BUILDING.md`.
