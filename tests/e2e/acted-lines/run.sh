#!/usr/bin/env bash
# E2E for P6 slice B (acted lines). Real engine, real converter, real catalog.
# Run from anywhere; the script moves to the repository root first so the
# default catalog/out settings apply. Artifacts go to evidence/ (gitignored).
set -euo pipefail

root=$(git rev-parse --show-toplevel)
cd "$root"
here=tests/e2e/acted-lines
out="$here/evidence"
mkdir -p "$out"

# One run per piece, so the evidence shows each segment next to the mix.
uv run voice-forge render "$here/guion-sintetico.yaml" --out "$out/01-synthetic.wav"
uv run voice-forge render "$here/guion-actuado.yaml" --out "$out/02-acted-converted.wav"
uv run voice-forge render "$here/guion-mixto.yaml" --out "$out/03-mixed.wav"

uv run voice-forge verify | tee "$out/verify.txt"

{
  for file in "$out"/*.wav; do
    printf '%s\t%s\n' "$(basename "$file")" \
      "$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$file")"
  done
} | tee "$out/durations.tsv"
