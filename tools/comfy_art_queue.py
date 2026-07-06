#!/usr/bin/env python3
"""Queue art-localization images through a ComfyUI API workflow.

Export an API-format workflow from ComfyUI and use placeholders in string fields:

  __IMAGE__   uploaded input image filename
  __PROMPT__  positive prompt text
  __SEED__    random seed integer
  __PREFIX__  output filename prefix

Then run:

  .venv/bin/python tools/comfy_art_queue.py workflow_api.json input.png \
    --prompt "Replace the Japanese text with: Start" \
    --out-dir art_work/comfy_outputs

This script intentionally does not assume one specific model/workflow. It uses
whatever workflow already works in your ComfyUI setup.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def request_json(url: str, data: dict | None = None) -> dict:
    body = None
    headers = {}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as res:
        return json.loads(res.read().decode("utf-8"))


def upload_image(comfy_url: str, image_path: Path) -> str:
    boundary = f"----ouran{random.randrange(1 << 32):08x}"
    data = image_path.read_bytes()
    parts = [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode(),
        data,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
        f"--{boundary}--\r\n".encode(),
    ]
    req = urllib.request.Request(
        f"{comfy_url}/upload/image",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=120) as res:
        payload = json.loads(res.read().decode("utf-8"))
    return payload["name"]


def replace_placeholders(value, replacements: dict[str, object]):
    if isinstance(value, str):
        out = value
        for key, replacement in replacements.items():
            if out == key:
                return replacement
            out = out.replace(key, str(replacement))
        return out
    if isinstance(value, list):
        return [replace_placeholders(v, replacements) for v in value]
    if isinstance(value, dict):
        return {k: replace_placeholders(v, replacements) for k, v in value.items()}
    return value


def queue_prompt(comfy_url: str, workflow: dict) -> str:
    payload = request_json(f"{comfy_url}/prompt", {"prompt": workflow})
    return payload["prompt_id"]


def wait_for_images(comfy_url: str, prompt_id: str, timeout: int) -> list[dict]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(2)
        try:
            history = request_json(f"{comfy_url}/history/{prompt_id}")
        except (urllib.error.URLError, TimeoutError):
            continue
        entry = history.get(prompt_id)
        if not entry:
            continue
        if entry.get("status", {}).get("completed"):
            images = []
            for output in entry.get("outputs", {}).values():
                images.extend(output.get("images", []))
            if not images:
                raise RuntimeError("ComfyUI completed but did not report output images")
            return images
    raise TimeoutError(f"timed out waiting for ComfyUI prompt {prompt_id}")


def download_image(comfy_url: str, image_info: dict, out_dir: Path) -> Path:
    params = urllib.parse.urlencode({
        "filename": image_info["filename"],
        "subfolder": image_info.get("subfolder", ""),
        "type": image_info.get("type", "output"),
    })
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / image_info["filename"]
    with urllib.request.urlopen(f"{comfy_url}/view?{params}", timeout=120) as res:
        out_path.write_bytes(res.read())
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workflow_json", help="ComfyUI API-format workflow JSON")
    parser.add_argument("input_png")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--negative", default="")
    parser.add_argument("--comfy-url", default="http://127.0.0.1:8188")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--prefix", default="ouran_art")
    parser.add_argument("--out-dir", default="art_work/comfy_outputs")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args(argv)

    workflow_path = Path(args.workflow_json)
    input_path = Path(args.input_png)
    seed = args.seed if args.seed is not None else random.randrange(1 << 32)

    uploaded = upload_image(args.comfy_url.rstrip("/"), input_path)
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    workflow = replace_placeholders(workflow, {
        "__IMAGE__": uploaded,
        "__PROMPT__": args.prompt,
        "__NEGATIVE__": args.negative,
        "__SEED__": seed,
        "__PREFIX__": args.prefix,
    })
    prompt_id = queue_prompt(args.comfy_url.rstrip("/"), workflow)
    print(f"queued prompt_id={prompt_id} seed={seed} input={uploaded}")
    images = wait_for_images(args.comfy_url.rstrip("/"), prompt_id, args.timeout)
    for image in images:
        out = download_image(args.comfy_url.rstrip("/"), image, Path(args.out_dir))
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
