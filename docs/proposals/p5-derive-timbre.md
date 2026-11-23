# P5 — Derive by timbre (voice conversion)

> Task breakdown: [tasks/p5-derive-timbre.md](../tasks/p5-derive-timbre.md)

## Goal
Today `derive` moves pitch and formants (±6 semitones, ffmpeg, instant). The
missing half is moving a voice **toward another voice's timbre**: keep the
performance, change who it sounds like.

## Design
A second port, `TimbreTransformer`, next to the existing pitch `VoiceTransformer`.
Pitch moves one identity up or down; timbre borrows a second clip's identity,
so the two operations do not share a contract. The domain, the CLI shape and the
catalog do not change.

```bash
voice-forge derive alex --timbre narrador-terror --slug alex-hibrido
```

Adapter call:

```bash
audiocpp_cli --task vc --family tone_color_vc --backend cuda \
  --model models/tone-color-vc-f16.gguf \
  --audio catalog/alex/ref.wav \
  --voice-ref catalog/narrador-terror/ref.wav \
  --out out/derived.wav
```

## Model

| Fact | Value |
|---|---|
| Package | `tone-color-vc-f16.gguf` (OpenVoiceV2) from `audio-cpp/audio.cpp-gguf` |
| Licence | **MIT** |
| Size | 65.6 MB / 63 MiB (F32: 131 MB) |
| Output | mono 22,050 Hz — the assembler normalises mixed rates |
| Needs | no transcript, no TTS model, offline |

Excluded by licence: `seed_vc` (GPL-3.0), `vevo2` (CC-BY-NC-ND), `meanvc2` is
Apache but 342 MB (q4) for no stated advantage here.

## Recipe
```json
{
  "derived_from": "alex",
  "transform": "timbre",
  "timbre_from": "narrador-terror",
  "source_sha256": "…",
  "timbre_sha256": "…"
}
```
Both parents are recorded by hash, so the lineage is verifiable, not a note.

## Acceptance
- The derived voice keeps the source performance (timing, emphasis) and the
  target timbre.
- It previews distinctly from both parents.
- `voice-forge verify` passes on it (the derived clip is hashed like any other).
- Removing either parent does not break the derived voice (it owns its clip).

## Risks
- Two parents, one voice: without both hashes in the recipe it becomes
  impossible to say what it came from.
- 22.05 kHz output is the lowest rate in the system; the assembler now handles
  it, but a future encoder must not assume 44.1 kHz.

## Outcome (2026-11-23)

Implemented as **P5-1..P5-10** in [tasks/p5-derive-timbre.md](../tasks/p5-derive-timbre.md).

- **Measured.** `derive alex --timbre narrador-terror --slug alex-hibrido`
  exited 0 in **1.0 s**: a **22,050 Hz mono, 10.170 s** clip from a **10.176 s**
  source, i.e. the performance is preserved. The recipe carries
  `transform=timbre`, `timbre_from=narrador-terror`, `source_sha256`,
  `timbre_sha256` and `model=tone-color-vc-f16`.
- **Verified.** `voice-forge verify` reports `alex-hibrido` `ok`; deleting either
  parent does not break it (unit test), because it owns its `ref.wav`.
- **Distinct, with numbers.** Same sentence, same neutral direction: mean
  spectral centroid **2,006 Hz** (`alex`), **2,364 Hz** (`narrador-terror`),
  **2,310 Hz** (`alex-hibrido`); RMS **-20.78 / -18.81 / -22.27 dB**; duration
  **5.2 / 4.8 / 5.1 s**. The hybrid lands beside the timbre target, not beside
  the source.
- **Licence verified.** `models/tone-color-vc/LICENSE` is MIT (MyShell.ai,
  2024); the 63 MB GGUF (`tone-color-vc-f16.gguf`, SHA-256 `7dcaff08…`) is
  **not committed**: `models/` is gitignored, and the path is configurable with
  `VOICEFORGE_TIMBRE_MODEL`.
- **Admission.** Conversion runs as a one-shot process outside the resident TTS
  host, through the same `SerialQueue`; the API, CLI and console all enqueue it.
  The engine was stopped with `voice-forge down` before the real conversion to
  free VRAM, then brought back up for the previews.
