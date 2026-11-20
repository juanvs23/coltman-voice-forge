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

### P2 — Emotion that actually lands (Apache/MIT only)
The speech backend must accept the eight axes. Candidate adapters behind the
existing port, in order:
- **ZONOS3-Mini** (Apache-2.0 weights, MIT code, ~9 GB): per-word steering
  (`scared+8`, `whisper+4`), 43 languages including Spanish. Finest control,
  newest and least proven.
- **VoxCPM2** (Apache-2.0, 2B, ~8 GB VRAM): emotion in the prompt plus
  controllable cloning; the VRAM figure sits exactly at this machine's limit.

**Excluded:** IndexTTS-2.5 (bilibili license) — the system is Apache/MIT only.
It stays as the reference for how the emotion interface should look, never as
an implementation target.

Acceptance: rendering the same line with `afraid:0.1` and `afraid:0.9` produces
audibly different takes, and `/health` stops reporting `unsupported`.

### P3 — Delivery polish
- Batch narration (one script → chaptered files) with per-scene loudness.
- Optional SSML-ish pauses inside a line.
- Voice versioning: allow `slug@2` without breaking old scripts.

## Debt schedule
_(none yet — every marker would be listed here with its resolution steps)_
