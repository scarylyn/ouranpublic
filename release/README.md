# Ouran High School Host Club (DS) — English Translation

A fan translation of *桜蘭高校ホスト部* for the Nintendo DS, translated
Japanese → English. This release has two purposes: let people **play** the
translated game, and let people **review the translation text** without
needing an emulator.

## How this was translated (full disclosure)

This translation used machine translation and AI assistance throughout, with
human review on top. Being upfront about that up front, since we know that's
a dealbreaker for some people and a "did a human actually check this"
question for everyone else:

1. **First pass**: every line of Japanese script got a raw machine
   translation (a local, offline model — Sugoi-14B), just to have a
   starting draft. Machine translation on isolated text boxes badly mangles
   pronouns, gender, and character names, because the original game splits
   single sentences across multiple text boxes and each box was translated
   in isolation.
2. **Quality pass**: the actual sentences (rejoined across their text boxes)
   were re-translated — a mix of AI-assisted rewriting and manual human
   correction — with a maintained glossary of character names/honorifics
   pulled from the game's own furigana, and a fixed voice guide per
   character (kept in `TRANSLATION_GUIDE.md` if you want to see the exact
   rules that were followed).
3. **QA pass**: every line was scanned for known machine-translation failure
   patterns (garbled names, textbox overflow, leftover non-English
   characters, leaked model commentary) and those were manually fixed.

None of that makes it studio-quality localization. It means: don't expect
zero mistakes, and please report anything that reads wrong — see
"Reporting issues" below.

## How to test it

You need your own legally-dumped copy of the original Japanese ROM
(`Ouran Koukou Host Club DS (Japan).nds`) — **this release does not include
the ROM**, only a patch, since the ROM itself is Nintendo's copyrighted
work.

1. Choose a patch from this release and get your own copy of the original
   Japanese `.nds` file.

   - `ouran_en_patch.bsdiff` - recommended current patch. Uses the readable
     narrow dialogue font and final layout fixes so text stays inside boxes.
   - `ouran_en_patch_stockfont_pre_narrow4.bsdiff` - optional legacy patch
     from before the narrow-font/layout-fitting pass. This keeps the older
     stock-font look, but some text may overflow.
2. Apply the patch:
   ```
   pip install bsdiff4
   python3 -c "import bsdiff4; bsdiff4.file_patch('Ouran Koukou Host Club DS (Japan).nds', 'ouran_en.nds', 'ouran_en_patch.bsdiff')"
   ```
3. Run `ouran_en.nds` in any DS emulator (melonDS, DeSmuME, etc.) or on
   real hardware via flashcart.

## How to review the translation without playing

- **Start here if you are not technical: `START_HERE_REVIEWERS.txt`**.
  It explains the three easy review options.
- **`reviewer_editor.html`** — open this in a normal web browser. It lets you
  search/filter lines, type suggested edits, and download a small feedback CSV
  to send back. No install needed.
- **`reviewer_feedback_template.csv`** — spreadsheet version for Excel,
  LibreOffice, or Google Sheets. Type fixes in `suggested_english` and notes
  in `notes`.
- **`reviewer_chapter_csvs/`** — smaller spreadsheet files split by chapter,
  for reviewers who only want to handle one route or chapter at a time.
- **`full_translation_review.csv`** — every dialogue line, choice, and
  chapter title in the game, in story order, one row per line, with the
  Japanese original and the current English translation side by side.
  Open it in a spreadsheet (Excel/Google Sheets/LibreOffice), filter/sort
  by file, and leave comments inline.
- **`review_transcripts/`** — the same content as readable per-chapter
  Markdown files, if you'd rather read it like a script than a spreadsheet.

## Reporting issues

If something reads wrong, unnatural, or out-of-character: note the `file`
and `id` from the CSV (or just quote the line) and say what's wrong. Actual
native-speaker correction is worth more than another AI pass, and specific
line-level feedback is the most useful form it can take.
