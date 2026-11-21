# P4 — Derive by timbre (voice conversion)

## Goal
Today `derive` moves pitch and formants (±6 semitones, ffmpeg, instant). The
missing half is moving a voice **toward another voice's timbre**: keep the
performance, change who it sounds like.

## Design
A second backend for the existing `VoiceTransformer` port. The domain, the CLI
shape and the catalog do not change.

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
| Size | 65.6 MB (F32: 131 MB) |
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
