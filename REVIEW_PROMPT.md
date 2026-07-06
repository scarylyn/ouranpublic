# AI Translation Review — Instructions

You are reviewing a Japanese→English fan translation of the Nintendo DS visual
novel *Ouran High School Host Club* (桜蘭高校ホスト部). A free offline machine
translator (Argos) produced a rough first-pass English draft. Your job is to
correct it into natural, in-character English.

## Input
A JSONL file. Each line is one piece of text:
```json
{"id": 42, "type": "Dialog", "speaker": "Haruhi", "jp": "「２人とも、どうしたの？」",
 "mt": "What did you do with two people?", "context": ["...", "...", "..."]}
```
- `jp` — the original Japanese (the source of truth)
- `mt` — the machine draft (often wrong; fix or rewrite it)
- `speaker` — who is talking (use for voice/tone)
- `context` — nearby Japanese lines, for disambiguation only (don't translate them)
- `type` — `Dialog`, `Speaker`, `Choice`, or `Chapter name`

## Output
Return JSONL, one object per input line, in the same order:
```json
{"id": 42, "en": "“What's going on with you two?”", "note": "optional"}
```
- `en` — your corrected English. Translate from `jp`, not from `mt`.
- `note` — optional; flag anything uncertain (a pun, an honorific choice, an unknown name).

## Rules (important — these keep the ROM working)
1. **Preserve in-text format codes verbatim.** If `jp` contains tokens like
   `#Color[7]` or `#Scale[1.8]`, copy them into `en` unchanged, in the same place.
2. **Preserve leading/trailing spacing**, including full-width spaces `　` (U+3000)
   at the start of a line — the game uses them to center text. Keep them.
3. **Shift-JIS safe only.** Do NOT use em dashes (—), ellipsis char (…), or
   accented letters (é, ï, ñ). Use `--`, `...`, and plain ASCII instead. Curly
   quotes `' ' " "` are fine.
4. **Keep names consistent with the glossary** (see `tools/glossary.json`):
   Haruhi, Tamaki, Kyoya, Hikaru, Kaoru, Honey, Mori, Renge, Nekozawa, Ranka.
   Honorifics: keep `-senpai` / `-kun` / `-chan` (the club's dynamic relies on them).
5. **Match register and brevity.** Visual-novel text boxes are short; don't pad.
   Keep `Speaker` labels to the character's name only.
6. If `jp` is onomatopoeia or a sound effect, render it as a natural English
   equivalent (e.g. a bell chime → "Ding-dong").

Return only the JSONL. Then it gets merged back with:
`python3 tools/ai_review.py merge <file>.json reviewed.jsonl`
