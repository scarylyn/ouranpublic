# Legal And Packaging Notes

This project is a fan translation workflow and patch. Do not publish original game files, unpacked ROM directories, or prebuilt `.nds` ROMs.

Safe community package contents:

- Translation JSON files.
- Review CSV and Markdown transcripts.
- Python tooling created for extraction, insertion, QA, wrapping, and font analysis.
- Documentation.
- Binary patch files such as `.bsdiff`, as long as the patch is distributed without the original ROM.

Do not include in public source archives:

- `Game Files/`
- `build/`
- `patched_bins*/`
- Any `.nds`, `.srl`, `.sav`, `.dsv`, or emulator state files.
- Original NFTR fonts extracted from the game.

The narrow dialogue font should be generated locally from the user's own extracted files using `tools/make_narrow_font.py`. Do not publish the generated NFTR as a standalone game asset.
