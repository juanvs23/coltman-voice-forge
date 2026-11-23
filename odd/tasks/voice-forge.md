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
- [x] `uv run pytest -q` green without GPU or models (114 passing).
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
- `dist/bin` — audio.cpp `a282e4e`; built by `voice-forge runtime build`, CUDA
  against the local prefix under `dist/cuda/usr`, recorded in `dist/BUILD.json`
  as backend `cuda` with arch 89 and eight flags. `audiocpp_cli` 99 MB and
  `audiocpp_server` 107 MB (stripped); both report `backends: cpu,cuda`.
- `models/ming3/ming-3.0-tts-0.5b-q8_0.gguf` — 1.74 GB.
- First Spanish line on CPU: 3.9 s of audio in ~12 s session (RTF ≈ 3.1);
  resident CUDA server: 2.5 s for two lines.
- `template_name=emotion` verified: `中性` vs `恐惧` produce different takes.
- Vulkan is still not buildable on this box (no headers, no `glslc`); `runtime
  plan` therefore never selects it here, and the builder fails loudly instead of
  downgrading.

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
- [x] **Builder CUDA prefix** — `RuntimeBuilder` detects
  `dist/cuda/usr/{lib64,include}` and emits both `-I` flags; proven by an
  unattended `runtime build --backend cuda --force` (`EXIT=0`, `action: built`,
  ~21 min) whose binaries report `backends: cpu,cuda`.
- [x] **Targeted `down`** — `up()` persists `out/server.pid` and `down()` signals
  that pid group only (SIGTERM, then SIGKILL after 15 s), raising `EngineBusy`
  while a job runs unless `--force`. Covered by a unit test; no live
  two-server run was performed.
- [x] **Non-blocking API** — blocking handlers are plain `def`, so Starlette runs
  them in its threadpool and `GET /api/queue` answers during a render. The
  concurrency test was verified red against the old `async def` handler.
- Evidence: `dist/BUILD.json` (`cuda_prefix`, `cuda_compiler`, `cuda_arch: 89`,
  eight flags); E2E `up` → pid 41376 · `warm` 0.6 s · `render
  examples/dialogo.yaml` → 6.4 s / 2 lines · `down` → `{"status":"down",
  "pid":41376}`; `uv run pytest -q` → 108 passed.

### (c) Cross-process admission
- [x] **`down` sees work started by another process.** New `JobState` port and
  `FileJobState` adapter: `out/active-job.lock` is held with
  `flock(LOCK_EX | LOCK_NB)` for the whole job (the kernel releases it if the
  process dies) and `out/active-job.json` is written atomically with `{job_id,
  kind, pid, started_at}`. `SerialQueue.busy()` and `snapshot()["active"]` read
  it, and a second concurrent job is refused with `EngineBusy`.
- Evidence: a ten-line render in one terminal; at 5 s `voice-forge queue` from
  another process → `busy: true`, `active: {kind: render, pid: 72528}`;
  `voice-forge down` from that process → **exit 2**, "a job is running; wait for
  it or use `down --force` to discard it"; the render finished **exit 0** in
  32.0 s / 10 lines; the final `down` exited 0 and removed `out/server.pid` and
  `out/active-job.json`; `uv run pytest -q` → 114 passed.

### (d) Ownership-verified shutdown
- [x] **`down` proves the pid is ours before touching it.** `up` writes a random
  boot token into the server's environment (`VOICEFORGE_SERVER_TOKEN`) and into
  `out/server.pid`; `down` opens a pidfd, verifies the token in
  `/proc/<pid>/environ`, and signals through the same descriptor (TERM →
  `wait(15)` → KILL → `wait(5)`, wait via `select` on the pidfd). A pidfd alone
  proves continuity, not ownership — a recycled pid with a live owner is
  rejected without a signal. No token, no kill.
- [x] **The five-second stop is gone.** `audio.cpp` has no `/shutdown` (404) and
  the old path waited out its grace period anyway. `down` now only waits when the
  endpoint answers below 400: a real stop went from 5.33 s to 0.217 s with
  `via: "signal"`.
- Evidence: a foreign live `sleep` placed in the pid file with a fake token →
  `down` exit 0, `via: "garbage"`, the `sleep` still alive; a real server →
  `down` exit 0 in 0.2 s with the pid file removed; `uv run pytest -q` → 143
  passed (128 before).

## Next step
P4 — build the operator console on a stack whose four silent failures are now
tested, not assumed.
