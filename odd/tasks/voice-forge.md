# Feature: voice-forge — local voice catalog and narrator

## Objective
A local-first system with exactly three verbs — create a voice from a prompt,
clone a voice from any clip, narrate a dialogue with graded emotion — with an
API, a CLI, a practical UI and an explicit on/warm/use/off lifecycle.

## Why
VoiceStudio was 10 GB of platform paying rent for one or two occasional
functions, and its TTS engine (OmniVoice) could not steer emotion. The
operator needs an owned system whose core outlives whichever model is in
fashion.

## Scope (authorized)
- New repository `voice-forge` (greenfield, no migration of old audio).
- Hexagonal architecture; domain independent of models.
- Design-then-clone invariant: a generated voice enters the catalog through
  the same door as an imported clip.
- CLI + REST API + single-file UI.
- ffmpeg assembly with optional LUFS mastering.

Out of scope: audio translation (removed at the operator's request), ASR,
video generation.

## Constraints
- GPU: RTX 4060 Laptop, 7.67 GB VRAM → one model loaded at a time.
- Core venv must not contain torch.
- Canonical artifacts in English; operator conversation in Spanish.
- **License: Apache-2.0 / MIT only.** IndexTTS-2.5 (bilibili) is excluded.
- **Admission control:** one host instance, one job at a time, rest queued;
  `up` on a live host is rejected, `down` refuses while a job runs.

## Tasks
| # | Task | Route | Evidence |
|---|---|---|---|
| 1 | Domain entities and rules — done | inline (fully specified, no research) | `tests/unit/test_domain.py` |
| 2 | Ports and use cases — done | inline | `tests/unit/test_catalog.py`, `test_dialogue.py` |
| 3 | Filesystem catalog adapter — done | inline | 6 tests incl. atomic staging |
| 4 | Engine HTTP client + supervisor — done | inline | exercised by API tests with fakes |
| 5 | ffmpeg assembler — done | inline | real ffmpeg run (`tests/integration/test_ffmpeg_assembler.py`) |
| 6 | CLI + API + UI — done | inline | API contract tests |
| 7 | Model runtime (audio.cpp) + optional qwen host — done | inline | `runtime status`; real `up`/`warm`/`render`; `engines/qwen_host.py` kept for `VOICEFORGE_ADAPTER=qwen` |
| 8 | Docs, AGENTS, roadmap — done | inline | this folder |

**Route declaration:** inline was chosen deliberately. The design was fully
resolved before the first write (ports, contracts, file layout), the work is
mechanical once specified, and inter-file coherence dominated the handoff
cost of a writer sub-agent. No exploration trigger fired: the model APIs were
already read from the installed package.

## Delivered since the first draft
- **Ming-3.0-TTS-0.5B GGUF (MIT) over `audio.cpp`** replaced Qwen3-TTS as the
  default backend, through the `audiocpp` adapter (`cli` and `server` transports).
  Eight emotion axes compose into one freeform Spanish instruction.
- **CUDA runtime** built against a local cuFFT prefix under `dist/cuda/`, one
  resident server, 2.5 s for a two-line render.
- **`preview`** with three rotating slots (`slot-0..2.wav` + `slot-N.json`).
- **`derive`** by pitch/formants via ffmpeg, registered with `derived_from` and
  both hashes.
- **Neutral reference** enforced at storage (Spanish stems + English whole
  words), audition always allowed.

## Acceptance criteria
- [x] `uv run pytest -q` green without GPU or models (95 passing).
- [x] `grep -E "qwen|torch|indextts" src/voiceforge/{domain,application}` empty.
- [x] CLI lists, designs, registers and renders through the same ports.
- [x] A voice created by prompt is indistinguishable downstream from an
      imported clip.
- [x] A second `up` is rejected; concurrent work waits in a FIFO.
- [x] First real render with the engine host.
- [x] Emotion audible on a real line, confirmed by the operator.

## Known gap
Qwen3-TTS Base cloned but ignored emotion instructions — the historical reason
for the change. Ming-3.0 closed it: the adapter applies the eight axes, and the
remaining limit is that intensity is expressed in words, not on a numeric dial.

## Runtime built
- `dist/bin` — audio.cpp `a282e4e`; CPU build 93 MB after stripping (2.2 GB
  unstripped), plus a CUDA build made by hand against `dist/cuda/usr`,
  reported by `runtime status` as backend `cuda`.
- `models/ming3/ming-3.0-tts-0.5b-q8_0.gguf` — 1.74 GB.
- First Spanish line on CPU: 3.9 s of audio in ~12 s session (RTF ≈ 3.1);
  resident CUDA server: 2.5 s for two lines.
- `template_name=emotion` verified: `中性` vs `恐惧` produce different takes.
- Vulkan is still not buildable on this box (no headers, no `glslc`), and
  `runtime build` cannot reproduce the CUDA binary yet — tracked as
  `[DEBT] builder-cuda-prefix`.

## Current work unit (2026-11-23)

### (a) Docs reconciliation
- [x] README, `docs/context.md`, `docs/architecture.md` rewritten against the
  shipped stack (Ming/audio.cpp default, qwen host optional, six ports,
  emotion as a per-line instruction).
- [x] P4 UI stack recorded as pinned Gradio 6.x mounted at `/ui` (reverses the
  0.13.0 React decision, which was rejected on measurement).
- [x] Roadmap snapshot and test count corrected; changelog entry `0.13.3`.
- Evidence: `git diff --stat` on `docs/`, `README.md`, `odd/tasks/`; `uv run
  pytest -q` → 95 passed.

### (b) P3 de-risk — three silent failures
- [ ] **Builder CUDA prefix** — teach `RuntimeBuilder` about
  `dist/cuda/usr/{lib64,include}` and both `-I` flags, then prove it by
  rebuilding through the builder (`backends: cpu,cuda`).
- [ ] **Targeted `down`** — persist the pid from `up()` (today only the qwen
  supervisor writes it) and signal that pid group instead of `pkill -x`.
- [ ] **Non-blocking API** — stop running the blocking `queue.wait(...)` on the
  event loop so `GET /api/queue` answers `busy: true` during a render.
- Evidence: pending. Expected: one fake-runner test per builder flag, a
  two-server `down` test, and an API test that reads the queue while a render
  is in flight.

## Next step
P3 — close the three silent failures before building the console.
