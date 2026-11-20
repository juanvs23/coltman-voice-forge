# Roadmap

## Next step
Run the first real voice end to end: `up` → `warm` → `design` → `render`.

## Phases

### P1 — Skeleton that runs (current)
- [x] Hexagonal layout: `domain` / `application` / `adapters`.
- [x] Ports: catalog, designer, synthesizer, assembler, engine control.
- [x] `CatalogService` with design-then-register and imported clips.
- [x] `DialogueService` with per-line emotion, speed and pauses.
- [x] Filesystem catalog with `voice.json` recipe and `GUIDE.md`.
- [x] Model host over HTTP (stdlib server, zero extra deps in the model venv).
- [x] CLI (`up/warm/down/status/design/add/voices/show/remove/render/serve`).
- [x] REST API + single-file web UI.
- [x] ffmpeg assembler with optional loudness normalisation.
- [x] Unit + integration tests with fakes (no GPU).
- [ ] First end-to-end render with the real engine (blocked on P2 decision).

### P2 — Emotion that actually lands
The speech backend must accept the eight axes. Two acceptable adapters behind
the existing port:
- **IndexTTS-2.5** (bilibili license, ~12 GB on disk): `emo_vector` + `emo_alpha`
  map 1:1 to our `Emotion`. Best measured Spanish cloning (SS 76.68).
- **ZONOS3-Mini** (Apache-2.0, ~9 GB): per-word steering; finer, newer, unproven.

Acceptance: rendering the same line with `afraid:0.1` and `afraid:0.9` produces
audibly different takes, and `/health` stops reporting `unsupported`.

### P3 — Delivery polish
- Batch narration (one script → chaptered files) with per-scene loudness.
- Optional SSML-ish pauses inside a line.
- Voice versioning: allow `slug@2` without breaking old scripts.

## Debt schedule
_(none yet — every marker would be listed here with its resolution steps)_
