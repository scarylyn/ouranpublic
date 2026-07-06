# Ouran Retranslation Guide (group workflow)

How to continue the human-quality retranslation pass. Benchmark: `translated_sergio_playable_wrapped/101_1_1.json` (fully done — read a few hundred lines of its New Text first to absorb the voice). Progress: 101 done; continue with 102_1_2.json, then in numeric order.

## Per-file loop

```bash
cd /media/joe/m.2/amanda
# 1. Backup first (see encoding warning below)
cp translated_sergio_playable_wrapped/FILE.json /tmp/FILE_backup.json

# 2. Export sentence groups
.venv/bin/python tools/group_review.py export \
  translated_sergio_playable_wrapped/FILE.json /tmp/FILE_groups.jsonl

# 3. Translate (see rules below) -> write /tmp/FILE_reviewed.jsonl
#    one line per group: {"gid": N, "en": "..."}

# 4. Merge (wraps displayed dialog at 32 chars x 3 lines)
.venv/bin/python tools/group_review.py merge \
  translated_sergio_playable_wrapped/FILE.json /tmp/FILE_reviewed.jsonl \
  --note "retranslation pass"

# 5. QA with the current narrow-font layout model.
.venv/bin/python tools/layout_qa_report.py translated_sergio_playable_wrapped \
  --font build/testfonts/LD_narrow4.NFTR \
  --out-prefix transcripts/layout_qa_check

# Optional no-usage layout cleanup:
# - default mode only rewraps/rejoins text that already fits; it does not
#   rewrite prose or call any API/model.
# - --use-model calls the local Ollama/Sugoi endpoint for overlong lines, but
#   those outputs must be spot-checked for names and voice before release.
.venv/bin/python tools/auto_fit_text.py translated_sergio_playable_wrapped
.venv/bin/python tools/auto_fit_text.py translated_sergio_playable_wrapped \
  --file FILE.json --limit 25 --use-model

# 6. Rebuild
.venv/bin/python tools/make_narrow_font.py \
  --src 'Game Files/data/fonts/LD937714LD937742.NFTR' \
  --out build/testfonts/LD_narrow4.NFTR
.venv/bin/python tools/insert_all_scripts.py --json-dir translated_sergio_playable_wrapped \
  --bin-dir 'Game Files/data/scr/bin' --out-dir patched_bins_sergio_wrapped/data/scr/bin
cp patched_bins_sergio_wrapped/data/scr/bin/*.bin build/ouran-sergio-wrapped/data/scr/bin/
cp build/testfonts/LD_narrow4.NFTR build/ouran-sergio-wrapped/data/fonts/LD937714LD937742.NFTR
cd build/ouran-sergio-wrapped && /media/joe/m.2/amanda/tools/bin/ndstool -c ouran-sergio-wrapped.nds \
  -9 arm9.bin -7 arm7.bin -y9 y9.bin -y7 y7.bin -d data -y overlay -t banner.bin -h header.bin
/media/joe/m.2/amanda/tools/bin/ndstool -i ouran-sergio-wrapped.nds | grep -E 'Header CRC|Banner CRC 0'
```

## Export format

Each JSONL group: `gid`, `ids` (pointer indices), `type`, `boxes` (how many
textboxes the sentence spans), `speaker` (nearest label — often wrong for
narration; the narrator is always Haruhi), `jp` (the JOINED full sentence),
`cur` (current MT text, ` | `-separated per box — often wrong, translate from
`jp`, not from `cur`).

Return `{"gid": N, "en": "full English sentence"}` — do NOT split it yourself;
merge wraps the displayed textbox at word boundaries. Length guide: one dialog
box safely fits about 80-90 English characters (32×3), and consecutive Japanese
Dialog fragments are often one displayed textbox, not separate boxes. Translate
ALL Dialog and Choice groups; skip Speaker groups (glossary already covers the
labels) and skip title-card groups (JP starts with 　) only if their current EN
is fine.

## Translation rules

- Translate from the Japanese. The MT (`cur`) is unreliable — wrong genders,
  invented subjects, literal name readings ("Mirror Night" = Kyoya).
- **Names**: use `tools/glossary.json`. Confirmed in-script furigana beat the
  glossary; update the glossary when you confirm one (Leo, Ou, Gotokuji still
  unconfirmed). Established: Kurakano (not Kuragano), Kamikamo (not Kamigamo),
  Sayuri Himemiya, Junichi Majima.
- **Honorifics**: keep (-senpai, -kun, -chan, -san, -sama). Honey calls Haruhi
  "Haru-chan", Sayuri "Sayu-chan", Tamaki "Tama-chan"; Mori is "Takashi" to
  Honey. Twins call Tamaki "milord"/"our lord" (殿).
- **No quote brackets**: spoken lines get no surrounding quotes (matches the
  rest of the game). Inner quotes may use \" ... \".
- **Voice**: Haruhi — deadpan, casual first-person narration ("...What a
  high-maintenance guy."); Tamaki — theatrical, princely, "my princess";
  Kyoya — polished, faintly menacing; Hikaru/Kaoru — snarky, teasing, often
  finish each other's sentences (their split lines really are split — keep the
  relay structure natural across groups); Honey — childlike, exclamation
  marks, ♪; Mori — terse fragments; Renge — haughty otaku, "ta-ta for now~".
- **Format codes** like `#Color[7]`, `#Scale[1.4]`, `#Pos[0,20]` must be
  copied verbatim at the same position. Lines whose text starts with a format
  code are overlays (32 chars × 2 lines, merge keeps your `en` verbatim —
  insert your own \n). Sound-effect overlays: ガーン → `*GONNNNNNNNG!*`.
- Choices: ≤30 chars, one line, imperative/short ("Entertain guests",
  "Help Kyoya-senpai").
- Shift-JIS only: no em dash (use --), no curly apostrophes needed (straight '
  is fine), no é etc. `sanitize.py` catches most, but avoid them.

## Encoding warning (data loss risk)

The JSONs are Shift-JIS. Read AND write with Python codec `shiftjis` exactly
like the tools do. Reading with `cp932` yields U+FF5E ～ which `shiftjis`
cannot re-encode → `json.dump` fails MID-WRITE and truncates the file. Always
back up the JSON before any bulk write. A `.corrupt-*` file in the directory
is a scar from exactly this.

## After each file

Regenerate the transcript exports if desired, and note progress (which files
are done) in the session summary so the next session can pick up cleanly.
