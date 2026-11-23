# E2E — acted lines (`source:`)

Run: 2026-11-23 · base commit `c29cd0e` (slice A) · engine up on CUDA · VC model
`models/tone-color-vc/tone-color-vc-f16.gguf` (MIT) · catalog has `alex` and
`narrador-terror`.

## Why this run exists

P6 slice B lets one script mix synthesised lines with the operator's own acted
performances. This run proves three things with the real engine and the real
converter, not fakes:

1. A `source:` line is converted to the selected voice's timbre and **keeps the
   take's duration** (the performance).
2. A mixed script renders as one mastered file whose duration is the sum of the
   synthetic segment, its pause, and the converted take.
3. Every catalog voice still passes `verify` afterward.

## How to reproduce

```bash
# from anywhere; the script moves to the repository root
tests/e2e/acted-lines/run.sh
```

`run.sh` renders three scripts (`guion-sintetico.yaml`, `guion-actuado.yaml`,
`guion-mixto.yaml`) into `evidence/`, then writes `verify.txt` and
`durations.tsv`. The scripts use a **relative** `source:`
(`../../../catalog/alex/ref.wav`), which resolves against the script's own
folder, not the current directory.

## Results

| File | What it is | Duration |
|---|---|---|
| `01-synthetic.wav` | `text:` line, `narrador-terror`, `afraid: 0.6` | **2.300 s** |
| `02-acted-converted.wav` | `source:` take (`alex`) converted to `narrador-terror` | **10.170 s** |
| `03-mixed.wav` | both lines in one mastered file (400 ms pause after the first) | **12.870 s** |

Source take: `catalog/alex/ref.wav` = **10.176 s**. The converted segment keeps
that timing (10.170 s); the 6 ms difference is the converter's output length,
not a re-read.

Mixed duration: **2.300 + 0.400 + 10.170354 = 12.870354 s**, exact.

`voice-forge verify` → all six catalog voices `ok` (`verify.txt`).

## Files

| Path | Committed? | Purpose |
|---|---|---|
| `guion-sintetico.yaml` | yes | one synthetic line |
| `guion-actuado.yaml` | yes | one acted line with a relative `source:` |
| `guion-mixto.yaml` | yes | the mixed script this slice exists for |
| `run.sh` | yes | runs the three renders and records the measurements |
| `evidence/` | **no** (gitignored) | wavs, `verify.txt`, `durations.tsv`, `summary.txt` |
