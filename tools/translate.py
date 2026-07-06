#!/usr/bin/env python3
"""Free, offline first-pass translation (Argos JA->EN) for extracted Ouran JSON.

Fills each pointer's "New Text" using a local Argos model -- no API cost, no rate
limits, reproducible. Designed as a *first pass*: a separate model-agnostic
review step (review.py, Claude/Gemini/Codex) polishes the output afterward.

Glossary anchoring
  Argos doesn't know 環 is "Tamaki" or that ホスト部 is the "Host Club", so we
  pre-substitute every glossary term (JP->EN, longest match first) into the
  source *before* translating. Argos preserves embedded English tokens, so names
  and key terms come through intact and consistent across all 62 files.

Layout preservation
  * In-text format codes (#Color[7], #Scale[1.8]) are preserved by Argos as-is.
  * Leading/trailing whitespace incl. full-width space U+3000 (used to center
    text) is stripped before MT and reattached after -- Argos drops it otherwise.
  * Speaker labels that exactly match the glossary skip MT entirely.

Output is Shift-JIS-sanitized so it can be inserted directly.

Resumable: pointers that already have non-empty "New Text" are skipped.
"""

import argparse
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sanitize import sanitize  # noqa: E402

ENCODING = "shiftjis"
GLOSSARY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.json")

# leading / trailing whitespace including full-width space (centering)
_WS = re.compile(r"^([\s　]*)(.*?)([\s　]*)$", re.DOTALL)


def save_json_atomic(data, path):
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=ENCODING) as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def has_japanese(s):
    return any(0x3040 <= ord(c) <= 0x30FF or 0x4E00 <= ord(c) <= 0x9FFF
               or 0xFF00 <= ord(c) <= 0xFFEF for c in s)


def already_done_with_backend(pointer, backend_id=None, model_id=None):
    if not pointer.get("New Text", "").strip():
        return False
    if backend_id and pointer.get("Backend") != backend_id:
        return False
    if model_id and pointer.get("Model") != model_id:
        return False
    return True


def load_glossary(path=GLOSSARY_PATH):
    """Return (speaker_map, substitutions).

    speaker_map: exact JP speaker label -> EN (skips MT entirely).
    substitutions: list of (jp, en) for in-text pre-substitution, longest first
    so 光＆馨 / 光邦 are replaced before bare 光."""
    g = json.load(open(path, encoding="utf-8"))
    speaker_map = {}
    subs = {}
    for entry in g.get("characters", []) + g.get("generic_labels", []):
        speaker_map[entry["jp"]] = entry["en"]
        subs[entry["jp"]] = entry["en"]
    for entry in g.get("terms", []):
        subs[entry["jp"]] = entry["en"]
    subs_sorted = sorted(subs.items(), key=lambda kv: len(kv[0]), reverse=True)
    return speaker_map, subs_sorted


def apply_subs(text, subs):
    for jp, en in subs:
        if jp in text:
            text = text.replace(jp, en)
    return text


class ArgosEngine:
    """Lazy wrapper so importing this module doesn't require the model loaded."""
    def __init__(self):
        import argostranslate.translate as tr
        self._tr = tr

    def __call__(self, text):
        return self._tr.translate(text, "ja", "en")


class SugoiApiEngine:
    """Translation engine using a local OpenAI-compatible API server (e.g. Ollama, llama.cpp, KoboldCPP, LM Studio)."""
    def __init__(self, api_url, model_name, api_key="sk-dummy", system_prompt=None):
        self.api_url = api_url.rstrip('/')
        self.model_name = model_name
        self.api_key = api_key
        self.system_prompt = system_prompt or (
            "You are a professional localizer whose primary goal is to translate Japanese to English. "
            "You should use colloquial or slang or nsfw vocabulary if it makes the translation more accurate. "
            "Always respond in English. Return only the translation, with no notes, explanations, romanization, "
            "or alternate translations. Preserve any formatting codes like #Color[7] exactly."
        )

    def __call__(self, text):
        import urllib.request
        import urllib.error
        import json

        url = f"{self.api_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text}
            ],
            "temperature": 0.1,
            "top_p": 0.95,
            "max_tokens": 512,
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                res = json.loads(response.read().decode("utf-8"))
                choices = res.get("choices", [])
                if choices:
                    translated = choices[0].get("message", {}).get("content", "").strip()
                    # Clean up markdown code block wrappers if model outputted them
                    if translated.startswith("```"):
                        lines = translated.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].startswith("```"):
                            lines = lines[:-1]
                        translated = "\n".join(lines).strip()
                    # Sometimes LLMs wrap the output in quotes
                    if (translated.startswith('"') and translated.endswith('"')) or (translated.startswith("'") and translated.endswith("'")):
                        if translated.count(translated[0]) == 2:
                            translated = translated[1:-1].strip()
                    return translated
                raise ValueError("No choices returned from the API.")
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                raise RuntimeError(f"API request failed with HTTP status {e.code}: {err_body}")
            except Exception:
                raise RuntimeError(f"API request failed with HTTP status {e.code}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"API request failed: {e}")


class SugoiLocalEngine:
    """Translation engine using llama-cpp-python with a local GGUF file or HF download."""
    def __init__(self, model_path=None, repo_id=None, filename=None, n_gpu_layers=-1, system_prompt=None):
        self.model_path = model_path
        self.repo_id = repo_id
        self.filename = filename
        self.n_gpu_layers = n_gpu_layers
        self.system_prompt = system_prompt or (
            "You are a professional localizer whose primary goal is to translate Japanese to English. "
            "You should use colloquial or slang or nsfw vocabulary if it makes the translation more accurate. "
            "Always respond in English. Return only the translation, with no notes, explanations, romanization, "
            "or alternate translations. Preserve any formatting codes like #Color[7] exactly."
        )
        self.llm = None

    def _lazy_init(self):
        if self.llm is None:
            try:
                from llama_cpp import Llama
            except ImportError:
                print("Error: llama-cpp-python is not installed. Please install it using:")
                print("  pip install llama-cpp-python")
                print("Or run llama.cpp server / Ollama and use the 'sugoi-api' backend instead.")
                sys.exit(1)
            
            if self.repo_id and self.filename:
                print(f"Downloading/loading local GGUF model from HF hub: {self.repo_id}/{self.filename}...")
                self.llm = Llama.from_pretrained(
                    repo_id=self.repo_id,
                    filename=self.filename,
                    n_gpu_layers=self.n_gpu_layers,
                    n_ctx=2048,
                    verbose=False
                )
            else:
                print(f"Loading local GGUF model from {self.model_path}...")
                self.llm = Llama(
                    model_path=self.model_path,
                    n_gpu_layers=self.n_gpu_layers,
                    n_ctx=2048,
                    verbose=False
                )

    def __call__(self, text):
        self._lazy_init()
        
        response = self.llm.create_chat_completion(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": text}
            ],
            max_tokens=256,
            temperature=0.1,
            top_p=0.95,
            repeat_penalty=1.1
        )
        
        translated = response["choices"][0]["message"]["content"].strip()
        # Clean up code blocks and quotes
        if translated.startswith("```"):
            lines = translated.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            translated = "\n".join(lines).strip()
        if (translated.startswith('"') and translated.endswith('"')) or (translated.startswith("'") and translated.endswith("'")):
            if translated.count(translated[0]) == 2:
                translated = translated[1:-1].strip()
        return translated


def translate_string(text, engine, speaker_map, subs, is_speaker=False):
    """Translate one source string, preserving layout and glossary terms."""
    # exact speaker label -> canonical, no MT
    if is_speaker and text.strip() in speaker_map:
        return speaker_map[text.strip()]
    if not has_japanese(text):
        return text  # already latin / pure codes -- leave as-is

    lead, core, trail = _WS.match(text).groups()
    if not core:
        return text
    if subs:
        core = apply_subs(core, subs)
    out = engine(core).strip()
    return f"{lead}{out}{trail}"


def translate_file(json_path, engine, speaker_map, subs, limit=None, verbose=True,
                   overwrite=False, autosave_every=10, backend_id=None,
                   model_id=None, resume_backend=False):
    d = json.load(open(json_path, encoding=ENCODING))
    pts = d["pointers"]
    todo = [p for p in pts
            if has_japanese(p["Original Text"])
            and (overwrite or not p.get("New Text", "").strip())
            and not (resume_backend and already_done_with_backend(p, backend_id, model_id))]
    if limit:
        todo = todo[:limit]
    total = len(todo)
    done = skipped = 0
    for i, p in enumerate(todo):
        is_spk = p["Type"] == "Speaker"
        orig = p["Original Text"].strip().replace('\n', ' ')
        if verbose:
            print(f"[{i+1}/{total}] Translating {p['Type']}: {orig}")
        try:
            new = translate_string(p["Original Text"], engine, speaker_map, subs, is_spk)
            clean = sanitize(new)
            if has_japanese(clean):
                raise ValueError("model output still contains Japanese text")
            p["MT Text"] = clean          # raw machine output, kept for reference
            p["New Text"] = clean         # current best (== MT until reviewed)
            p["Status"] = "mt"
            if backend_id:
                p["Backend"] = backend_id
            if model_id:
                p["Model"] = model_id
            done += 1
            if verbose:
                clean_disp = clean.strip().replace('\n', ' ')
                print(f"  -> {clean_disp}")
            if autosave_every and done % autosave_every == 0:
                save_json_atomic(d, json_path)
        except ValueError as e:
            # un-encodable result -- leave blank, flag for human
            p["New Text"] = ""
            p["Status"] = "untranslated"
            if backend_id:
                p["Backend"] = backend_id
            if model_id:
                p["Model"] = model_id
            p["_flag"] = f"sanitize: {str(e).encode('ascii', 'backslashreplace').decode('ascii')}"
            skipped += 1
            if verbose:
                print(f"  -> FLAGGED (Shift-JIS unsafety): {e}")
            if autosave_every and (done + skipped) % autosave_every == 0:
                save_json_atomic(d, json_path)
        except KeyboardInterrupt:
            print("\nInterrupted; saving progress before aborting...")
            save_json_atomic(d, json_path)
            raise
        except Exception as e:
            print(f"\nError translating string '{p['Original Text']}' in {os.path.basename(json_path)} pointer #{i}: {e}")
            print("Saving already translated lines to file and aborting...")
            save_json_atomic(d, json_path)
            raise e
    save_json_atomic(d, json_path)
    return done, skipped, len(pts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="JA->EN translation first-pass script")
    ap.add_argument("json", nargs="+", help="json file(s) to translate in place")
    ap.add_argument("--limit", type=int, help="translate at most N pointers per file (testing)")
    ap.add_argument("--glossary", default=GLOSSARY_PATH)
    ap.add_argument("--no-glossary", action="store_true",
                    help="Do not pre-substitute glossary terms in the prompt (recommended for smart LLMs like Sugoi)")
    ap.add_argument("--quiet", action="store_true",
                    help="Do not print each translation dynamically to stdout")
    ap.add_argument("--overwrite", action="store_true",
                    help="Retranslate lines even when New Text is already filled")
    ap.add_argument("--resume-backend", action="store_true",
                    help="With --overwrite, skip lines already tagged with this backend/model")
    ap.add_argument("--autosave-every", type=int, default=10,
                    help="Save progress after this many translated lines per file (0 disables)")
    ap.add_argument("--backend", default="argos", choices=["argos", "sugoi-api", "sugoi-local"],
                    help="Translation backend to use: 'argos' (default Argos Translate), "
                         "'sugoi-api' (Sugoi 14B or generic LLM via local API like Ollama/llama.cpp/LM Studio), "
                         "or 'sugoi-local' (local .gguf file via llama-cpp-python)")
    ap.add_argument("--api-url", default="http://localhost:11434/v1",
                    help="API URL for 'sugoi-api' backend (default: http://localhost:11434/v1 for Ollama)")
    ap.add_argument("--api-model", default="sugoi-14b",
                    help="Model name for 'sugoi-api' backend (default: sugoi-14b)")
    ap.add_argument("--api-key", default="sk-dummy",
                    help="API key for 'sugoi-api' backend (optional)")
    ap.add_argument("--model-path", help="Path to the .gguf model file for 'sugoi-local' backend")
    ap.add_argument("--repo-id", help="HuggingFace repository ID for 'sugoi-local' backend (e.g. sugoitoolkit/Sugoi-14B-Ultra-GGUF)")
    ap.add_argument("--model-filename", help="Model filename on HuggingFace for 'sugoi-local' backend (e.g. Sugoi-14B-Ultra-F16.gguf)")
    ap.add_argument("--n-gpu-layers", type=int, default=-1,
                    help="Number of GPU layers to offload for 'sugoi-local' backend (-1 for all, 0 for CPU)")
    ap.add_argument("--system-prompt", help="Custom system prompt to override the default localizer prompt")
    args = ap.parse_args(argv)

    speaker_map, subs = load_glossary(args.glossary)
    if args.no_glossary:
        subs = []

    print(f"glossary: {len(speaker_map)} speaker labels, {len(subs)} substitutions")

    if args.backend == "argos":
        engine = ArgosEngine()
        backend_id = "argos"
        model_id = "argos-ja-en"
    elif args.backend == "sugoi-api":
        engine = SugoiApiEngine(args.api_url, args.api_model, args.api_key, args.system_prompt)
        backend_id = "sugoi-api"
        model_id = args.api_model
    elif args.backend == "sugoi-local":
        if not args.model_path and not (args.repo_id and args.model_filename):
            ap.error("Either --model-path or both --repo-id and --model-filename must be specified when using the 'sugoi-local' backend.")
        engine = SugoiLocalEngine(
            model_path=args.model_path,
            repo_id=args.repo_id,
            filename=args.model_filename,
            n_gpu_layers=args.n_gpu_layers,
            system_prompt=args.system_prompt
        )
        backend_id = "sugoi-local"
        model_id = args.model_path or f"{args.repo_id}/{args.model_filename}"
    else:
        ap.error(f"Unknown backend: {args.backend}")

    grand_done = grand_skip = 0
    for jp in args.json:
        done, skipped, total = translate_file(
            jp,
            engine,
            speaker_map,
            subs,
            args.limit,
            verbose=not args.quiet,
            overwrite=args.overwrite,
            autosave_every=args.autosave_every,
            backend_id=backend_id,
            model_id=model_id,
            resume_backend=args.resume_backend,
        )
        grand_done += done
        grand_skip += skipped
        print(f"{os.path.basename(jp)}: translated {done}, flagged {skipped} (of {total} pointers)")
    print(f"\nTOTAL: translated {grand_done}, flagged {grand_skip}")


if __name__ == "__main__":
    main()
