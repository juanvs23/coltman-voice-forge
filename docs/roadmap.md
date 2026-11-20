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

Sweep of the Hugging Face TTS catalogue on 2026-11-20: 2,698 models seen,
942 Apache-2.0/MIT, 188 of those tagged Spanish or multilingual. Shortlist
after discarding by licence, language and VRAM:

| Model | Licence | On disk | ES | Clone | Create by prompt | Emotion | Integration |
|---|---|---|---|---|---|---|---|
| **ZONOS3-Mini** | Apache-2.0 | ~9 GB weights | 43 langs | ✅ | attributes only | ✅ **numeric, per word** | own runtime |
| **Fun-CosyVoice3-0.5B** | Apache-2.0 | 9.75 GB | 9 langs | ✅ | ❌ | ✅ instruct (text) | pip |
| **Ming-3.0-TTS-0.5B** | MIT | 4.74 GB | ✅ | ✅ | ✅ instruct | ✅ structured attributes | GGUF/CLI |
| **Chatterbox Multilingual V3** | MIT | ~5.3 GB | 23 langs | ✅ | ❌ | ⚠️ scalar `exaggeration` | pip |
| **VoxCPM2** | Apache-2.0 | 4.96 GB | 30 langs | ✅ | ✅ prompt | ⚠️ prompt only | pip, ~8 GB VRAM |

Excluded by the sweep:
- **VibeVoice-1.5B / Realtime** — MIT tag, but the card restricts it to
  "research purpose use"; not a production licence.
- **IndexTTS-2.5** — bilibili licence.
- **Libra-TTS, Kokoro, MeloTTS, Soprano, VieNeu** — no emotion control.

Order of preference: **ZONOS3-Mini** for the numeric axes (maps 1:1 to
`Emotion`), then **CosyVoice3** as the pragmatic pip fallback, then
**Ming-3.0** if GGUF/llama.cpp is preferred. Chatterbox V3 only if a single
scalar turns out to be enough.

Acceptance: rendering the same line with `afraid:0.1` and `afraid:0.9` produces
audibly different takes, and `/health` stops reporting `unsupported`.

### P3 — Delivery polish
- Batch narration (one script → chaptered files) with per-scene loudness.
- Optional SSML-ish pauses inside a line.
- Voice versioning: allow `slug@2` without breaking old scripts.

## Debt schedule
_(none yet — every marker would be listed here with its resolution steps)_
