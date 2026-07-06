#!/usr/bin/env python3
"""Insert all translated JSON script files back into patched .bin files."""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ouran_tool import insert  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Batch insert translated Ouran scripts")
    parser.add_argument("--json-dir", default="translated")
    parser.add_argument("--bin-dir", default="Game Files/data/scr/bin")
    parser.add_argument("--out-dir", default="patched_bins/data/scr/bin")
    args = parser.parse_args(argv)

    os.makedirs(args.out_dir, exist_ok=True)
    done = skipped = failed = 0
    for json_path in sorted(glob.glob(os.path.join(args.json_dir, "*.json"))):
        name = os.path.splitext(os.path.basename(json_path))[0]
        bin_path = os.path.join(args.bin_dir, name + ".bin")
        out_path = os.path.join(args.out_dir, name + ".bin")
        if not os.path.exists(bin_path):
            skipped += 1
            print(f"skip {name}: missing {bin_path}")
            continue
        try:
            insert(bin_path, json_path, out_path)
            done += 1
            print(f"patched {name}.bin")
        except Exception as exc:
            failed += 1
            print(f"FAILED {name}: {exc}")
    print(f"\nDone: {done} patched, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
