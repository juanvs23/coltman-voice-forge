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
- CLI + REST API + Gradio operator console at `/ui`.
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
- [x] `uv run pytest -q` green without GPU or models (226 passing).
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

### (e) P4 console — parity and closure
- [x] **Console screens at `/ui`.** Gradio 6.32.0 mounted on the same FastAPI
  app with `gr.mount_gradio_app` (no Node, no build step): Voices (cards with
  origin badge and `derived_from`, derive, remove), Preview (text, eight axes,
  intensity, speed, three rotating slots), Design (audition candidates, play
  them, register the chosen one), Engine (up / warm / down, real status, queue).
- [x] **Narrate screen.** YAML editor seeded from `examples/dialogo.yaml`,
  "Validate + estimate" (lines, `SECONDS_PER_LINE = 3.2`, summed
  `pause_after_ms`), output path defaulting to `out/narrate.wav`, optional LUFS
  master, a generator that re-reads the queue every 0.2 s, and a `gr.Audio`
  result. Gradio's own queue is never enabled.
- [x] **Audition API.** `POST /api/voices/design/candidates` writes
  `out/candidates/<token>-<n>.wav`; `POST /api/voices/design/register` stores one
  candidate by token and index; both players are served from `/candidates/`.
- [x] **Parity.** `adapters/primary/ui.py` deleted; `GET /` → **308** to `/ui/`,
  `GET /ui` → 200 entry with meta-refresh, `GET /ui/` → the console. No template
  remains that duplicates the API.
- [x] **Closing docs.** Roadmap P4 done + outcome, proposal implemented (API
  additions, Gradio 6.32.0), task list P4-1..P4-11 with per-task evidence,
  changelog `0.15.0`, `context.md`, README, `AGENTS.md` and this sheet.
- Evidence: `uv run pytest -q` → **226 passed** (215 before). Live check:
  `voice-forge serve --port 8793` with `VOICEFORGE_CATALOG=/tmp/opencode/catalog-p4b`
  → `GET /` without following redirects **308** with `location: /ui/`;
  `GET /ui` **200**; `GET /ui/` **200**; `GET /ui/config` **200** and contains
  `Narrate`, `Render`, `Validate`; `GET /ui/assets/index-C5ocWp53.js` **200**
  (`application/javascript`, 139,485 bytes). The engine was down and this check
  does not need it; the server was stopped by pid and the temporary catalog
  removed.

### (f) P5 — Derive by timbre
- [x] **A second transformer port.** `TimbreTransformer.timbre(source,
  target_ref, out)` sits beside `VoiceTransformer.pitch`; `AudiocppTimbre`
  shells out to `audiocpp_cli --task vc --family tone_color_vc` with the same
  runtime environment as the TTS adapter.
- [x] **`derive --timbre SLUG`.** The service rejects pitch + timbre together
  and a timbre request with no converter; the recipe records `transform:
  timbre`, `timbre_from`, both `*_sha256` and `model: tone-color-vc-f16`; the
  default name is `"{source} como {target}"`; the derived voice keeps the
  source's language and neutrality because the performance is the source's.
- [x] **Queued, not a side path.** API, CLI and console submit `derive` to the
  `SerialQueue`; the console gains a "Timbre source (optional)" dropdown and the
  card recipe shows `timbre_from`; the MCP tool sends timbre and omits pitch.
- [x] **Admission.** The engine was stopped with `down` (VRAM freed) for the
  conversion, then `up` + `warm` brought it back for the previews.
- Evidence: `derive alex --timbre narrador-terror --slug alex-hibrido` exit 0 in
  **1.0 s**; `show` → 22,050 Hz, 10.170 s (source 10.176 s), recipe
  `timbre_from=narrador-terror`, `source_sha256=dae1f4d5…`,
  `timbre_sha256=5d0f75c2…`; `verify` → `alex-hibrido ok`; same-sentence previews
  centroid **2,006 / 2,364 / 2,310 Hz**, RMS **-20.78 / -18.81 / -22.27 dB**
  (alex / narrador-terror / hybrid); `uv run pytest -q` → **300 passed**.

### (g) P6 — Long-form delivery: chapters and acted lines
- [x] **A — chapters**: raw-text split on `## chapter:`, per-chapter assembly and
  **measured** loudness. Evidence: `examples/guion-3-capitulos.yaml` →
  **−14.89 / −13.82 / −14.13 LUFS** at 6.00 / 5.00 / 5.55 s.
- [x] **B — acted lines**: `source:` replaces `text`, the take is converted to
  the line's voice and keeps its timing. Evidence: synthetic 2.300 s + acted
  10.170 s (take 10.176 s) + 400 ms → **12.870 s**; E2E in
  `tests/e2e/acted-lines/`.
- [x] **C — versioning** moved to the backlog: a bare name must not change
  meaning. **D — duration guard** deferred. Decision recorded in the roadmap.
- Evidence: `uv run pytest -q` → **324 passed**.

## Next step
P7 — operational polish: an auditable `dist/` prune command and CI.
