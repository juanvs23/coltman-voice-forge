# Changelog

## [0.1.0] - 2026-11-20

### Added
- Hexagonal core with five ports (catalog, designer, synthesizer, assembler,
  engine control) and no model dependency in `domain/` or `application/`.
- Voice catalog on disk: one directory per voice with `voice.json` (recipe),
  `ref.wav` (immutable reference) and `GUIDE.md` (human guide).
- Design-then-clone flow: a generated voice is registered through the same
  path as an imported clip, so every later line clones from `ref.wav`.
- Dialogue rendering with per-line emotion (eight graded axes), intensity,
  speed and trailing pause, plus optional loudness mastering to -14 LUFS.
- CLI: `up`, `warm`, `down`, `status`, `design`, `add`, `voices`, `show`,
  `remove`, `render`, `serve`.
- REST API with OpenAPI docs and a single-file web UI (no build step).
- Model host (`engines/qwen_host.py`) over plain JSON/HTTP, stdlib only, so a
  rebuilt model venv cannot break it.
- Tests: domain rules, catalog, dialogue orchestration and the HTTP contract,
  all with fakes — no GPU required.

### Known limitations
- The Qwen3-TTS **Base** speech backend clones but ignores emotion
  instructions; `/health` reports `emotion: unsupported-by-speech-backend`.
  Tracked as roadmap phase P2.
- Single-engine host: one model loaded at a time (8 GB VRAM budget).
