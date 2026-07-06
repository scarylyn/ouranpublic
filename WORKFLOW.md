# Ouran Translation Workflow

Groundwork for translating the Nintendo DS visual novel *Ouran High School Host
Club* (桜蘭高校ホスト部) — built to generalize to other pointer-table NDS scripts.

## What's here

```
Game Files/            original extracted ROM filesystem (DS: arm9/arm7/y9/y7/header/banner + data/)
  data/scr/bin/*.bin   62 script files (the text we translate)
jsons/*.json           original extractions (Japanese text + empty "New Text" fields)
extraction_script.py   original community tool (jaga8285 et al.) — kept for reference
tools/
  ouran_tool.py        refactored extract/insert toolkit (verified lossless round-trip)
  translate.py         offline Argos JA->EN first pass, glossary-anchored
  review_server.py     local web workbench: progress tracking + manual review
  ai_review.py         export/merge bridge so any AI can check the translation
  status_model.py      shared status model (untranslated/mt/ai/approved)
  sanitize.py          Shift-JIS safety for inserted text
  glossary.json        authoritative name/term map for consistency
REVIEW_PROMPT.md       instructions handed to an AI reviewer alongside an export
translated/            working JSON (edited here) + patched .bin output
```

## The pipeline

```
  .bin  --extract-->  .json  --translate-->  .json (New Text filled)  --insert-->  patched .bin  -->  into .nds
```

### 1. Extract (already done for all 62 files, but reproducible)
```
python3 tools/ouran_tool.py extract "Game Files/data/scr/bin/118_4_2.bin" out.json
```

### 2. Translate (offline, free)

You can choose between the default lightweight **Argos** engine or the higher-quality **Sugoi-14B-Ultra** LLM.

#### Option A: Argos Translate (Lightweight, ~300MB)
First-time setup:
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "import argostranslate.package as p; p.update_package_index(); \
  pkg=[x for x in p.get_available_packages() if x.from_code=='ja' and x.to_code=='en'][0]; \
  p.install_from_path(pkg.download())"
```
Run translation:
```
.venv/bin/python tools/translate.py translated/*.json
```

#### Option B: Sugoi-14B-Ultra-GGUF via Local API Server (Recommended for speed/GPU acceleration)
If you run the model locally using an OpenAI-compatible API server like **Ollama**, **llama.cpp server**, **LM Studio**, or **KoboldCPP**, you can connect to it directly.

For example, using **Ollama** (requires importing the GGUF model):
1. Create a `Modelfile`:
   ```dockerfile
   FROM /path/to/Sugoi-14B-Ultra-Q4_K_M.gguf
   PARAMETER temperature 0.1
   PARAMETER top_p 0.95
   PARAMETER top_k 40
   SYSTEM "You are a professional localizer whose primary goal is to translate Japanese to English. You should use colloquial or slang or nsfw vocabulary if it makes the translation more accurate. Always respond in English."
   ```
2. Build and run: `ollama create sugoi-14b -f Modelfile && ollama run sugoi-14b`
3. Translate using the script (API default endpoint is `http://localhost:11434/v1` with model `sugoi-14b`):
   ```
   .venv/bin/python tools/translate.py translated/*.json --backend sugoi-api --no-glossary
   ```
   *(Note: `--no-glossary` is recommended for LLMs to prevent pre-substitution from confusing the model's contextual understanding, allowing it to translate naturally)*

If running **llama-server** or **LM Studio**:
```
.venv/bin/python tools/translate.py translated/*.json --backend sugoi-api --api-url http://localhost:8080/v1 --api-model <model-name> --no-glossary
```

#### Option C: Sugoi-14B-Ultra-GGUF via llama-cpp-python (Local in-process execution)
If you want to run the model directly in Python without setting up an external API server:
1. Install the llama-cpp-python package (optionally with GPU acceleration, e.g. CUDA):
   ```
   .venv/bin/pip install llama-cpp-python
   ```
2. Run translation using one of the following methods:
   *   **Method 1: Auto-download and cache directly from Hugging Face Hub** (highly convenient; downloaded files are cached automatically in `~/.cache/huggingface/`):
       ```
       .venv/bin/python tools/translate.py translated/*.json --backend sugoi-local --repo-id sugoitoolkit/Sugoi-14B-Ultra-GGUF --model-filename Sugoi-14B-Ultra-F16.gguf --no-glossary
       ```
   *   **Method 2: Use an already-downloaded GGUF file**:
       ```
       .venv/bin/python tools/translate.py translated/*.json --backend sugoi-local --model-path /path/to/Sugoi-14B-Ultra-Q4_K_M.gguf --no-glossary
       ```

Work on copies in `translated/` (`cp jsons/*.json translated/`) so the original extractions stay pristine.

### 2b. Track progress & review (web workbench)
```
.venv/bin/python tools/review_server.py        # serves translated/ at http://127.0.0.1:5000
```
*   **Dashboard** — overall + per-file progress bars, broken down by status (approved / AI-reviewed / machine / untranslated).
*   **File view** — Japanese | machine draft | your English (editable) | status, with filtering and pagination. Edits save straight into the JSON; English is Shift-JIS-sanitized on save.
*   **Compare view** — click `compare` from the dashboard or file view to compare two JSON folders side-by-side, then copy either version into the working translation.
*   **Auto-Translation Controls**:
    *   **Single-line**: Click the `🤖 auto` button next to any line's text area to translate it using the configured backend.
    *   **Select Area (Page Batch)**: Click the `🤖 Auto-translate Page Untranslated` button at the top of the line list to translate all untranslated lines on the current page sequentially. *(Tip: Filter by "untranslated" first to translate specific batches!)*
    *   **Checked/range batch**: Check rows or enter a pointer ID range, then translate only that selected section.

The web server supports the same backend options as `translate.py`. For example, to run the workbench with the Hugging Face GGUF model:
```bash
.venv/bin/python tools/review_server.py --backend sugoi-local --repo-id sugoitoolkit/Sugoi-14B-Ultra-GGUF --model-filename Sugoi-14B-Ultra-F16.gguf --no-glossary
```

To compare multiple translation folders, pass each extra folder with `--compare-dir`:
```bash
.venv/bin/python tools/review_server.py --dir translated --compare-dir translated_sugoi --compare-dir jsons
```

Every translatable line tracks a **Status**: `untranslated → mt → ai → approved`
(see `tools/status_model.py`). Only `New Text` is inserted into the ROM; status
is purely for tracking.

### 2c. Let another AI check the work
Model-agnostic — works with Claude, Gemini, Codex, or a later session:
```
.venv/bin/python tools/ai_review.py export translated/118_4_2.json review.jsonl
#   -> hand review.jsonl + REVIEW_PROMPT.md to any AI; it returns reviewed.jsonl
.venv/bin/python tools/ai_review.py merge  translated/118_4_2.json reviewed.jsonl
```
Export carries the Japanese, the machine draft, the speaker, and surrounding
context. Merge writes corrections into `New Text`, sets status `ai`, and never
touches `Original Text` / `MT Text`, so every change is auditable. The exact
rules the AI must follow (preserve format codes, Shift-JIS safety, glossary
names) live in `REVIEW_PROMPT.md`.

### 3. Insert (verified)
```
python3 tools/ouran_tool.py insert \
    "Game Files/data/scr/bin/118_4_2.bin" out.json translated/118_4_2.bin
```
Inserted text is auto-sanitized to Shift-JIS; an un-encodable string aborts the
file (naming the pointer) instead of corrupting it.

### 4. Build the ROM
Swap the patched `data/scr/bin/*.bin` files into **your original `.nds`** with a
DS ROM tool (e.g. `ndstool -x` to unpack, replace files, `ndstool -c` to repack),
then test in melonDS / DeSmuME. We rebuild from the original ROM rather than the
loose `Game Files/` because the extraction is missing the `overlay/` directory.

## Verify your setup any time
```
python3 tools/ouran_tool.py selftest "Game Files/data/scr/bin/101_1_1.bin"
# -> selftest: 3888 matched, 0 mismatched -> PASS
```

## Verified facts (don't relearn these the hard way)

- **Round-trip is lossless** including English expansion: a +62% larger text
  block with offsets 5× past the `0x7fff` boundary re-extracts with 0 mismatches.
- **Insertion encodes as Shift-JIS.** `—`, `…`, and accented letters (`é`, `ï`)
  are NOT valid Shift-JIS and will crash insertion. `sanitize.py` maps them to
  safe equivalents. Curly quotes (`'` `"`) and the full-width space `　`
  (U+3000, used by the game to center text — preserve it!) are valid and kept.
- **In-text formatting codes** like `#Color[7]` and `#Scale[1.8]` appear inside
  dialog strings. Translation must preserve them verbatim.
- **Validation drops non-contiguous pointers** (rare). The tools report the count
  so you can watch for unexpected text loss.

## Scale
~30,165 meaningful strings: 20,829 dialog, 9,021 speaker labels, 290 choices,
25 chapter names. ~1% currently translated.

## Credits
Extraction format and original tool by GitHub user **jaga8285** (with thanks to
**JJJewel** and **azerty1**). Project by **Kari / Scarylyn**.
