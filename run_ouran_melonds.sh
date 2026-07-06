#!/usr/bin/env bash
set -euo pipefail

ROOT="/media/joe/m.2/amanda"
ROM="$ROOT/build/ouran-sergio/ouran-sergio.nds"
MELONDS="/home/joe/Downloads/melonDS"
LIBS="$ROOT/tools/melonds-libs"

LD_LIBRARY_PATH="$LIBS${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" "$MELONDS" "$ROM"
