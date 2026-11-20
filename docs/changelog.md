# Changelog

## [0.7.0] - 2026-11-20

### Added
- **Server transport** (`VOICEFORGE_TRANSPORT=server`, the default): the model
  lives in `audiocpp_server` and answers `/v1/audio/speech`, so narration stops
  paying a model load per line. `AudiocppServerControl` gives a real
  on/warm/use/off cycle again.
- Server request contract verified by hand before implementing: `voice_ref`
  (path string, or `{type,path|base64}`), `options` carrying `language`,
  `template_name`, `instruct`, `seed`.

### Fixed
- **`reference_text` was sabotaging every line.** It enables the acoustic
  prefix (ICL) mode: measured 22 s per line and 5.1 s of audio for a 2.6 s
  sentence — the model continues the reference. Speaker-only conditioning is
  9.5 s with the right length. Both adapters now omit it; identity comes from
  the speaker embedding, performance from the instruction.
- The server control was receiving the CLI binary and failing with
  "missing required --model argument".

### Measured (same two-line script, CPU, Q8_0)
| Path | Wall time | Audio |
|---|---|---|
| CLI, per call | 40.2 s | 11.5 s |
| Server + `reference_text` | 46.4 s | 11.5 s |
| **Server, speaker-only** | **25.6 s** | **6.4 s** |


## [0.6.0] - 2026-11-20

### Added
- **audiocpp adapter** (`adapters/secondary/audiocpp_cli.py`): implements
  `VoiceDesigner` and `SpeechSynthesizer` over `audiocpp_cli`, so the system
  speaks Ming-3.0 GGUF with no Python model stack, no torch and no venv.
  - `vdes` for voice design, one process per candidate.
  - `clon` for every line, with `template_name=freeform` composing emotion and
    pace from the domain's axes into one short Spanish instruction.
  - Language and instruction composition are pure functions with tests.
- Adapter selection: `VOICEFORGE_ADAPTER=audiocpp|qwen`; device backend:
  `VOICEFORGE_DEVICE=cpu|cuda|vulkan`. The Qwen host remains as the other
  adapter, per the hexagonal contract.
- `AudiocppControl`: the lifecycle reports `cli` instead of faking a warm host,
  because in this mode the model loads per call.

### Verified end to end (CPU, Q8_0)
- `voice-forge design "…" --slug narradora-ming --candidates 1` → 9.7 s,
  registered at 44.1 kHz with the full recipe.
- `voice-forge render examples/dialogo.yaml` → 11.5 s of audio for 2 lines in
  40.2 s wall time (RTF ≈ 3.5, two model loads included).

## [0.5.0] - 2026-11-20

### Added
- **Reference-clip integrity.** `voice.json` now records the SHA-256 of
  `ref.wav`, and `voice-forge verify` reports every voice whose clip no longer
  matches what was registered (exit code 1 on mismatch). A voice registered
  before this change reports `unverifiable`, never a false `ok`.
- `voice-forge add` accepts `--instruct`, `--seed`, `--recipe key=value` and
  `--origin designed|imported`, so a generated voice keeps its provenance.
- `add` reads the real sample rate from the file instead of assuming 24 kHz
  (Ming emits 44.1 kHz).

### Changed
- Documented the rule behind all of this: the prompt is a recipe, the clip is
  the voice. Re-running a prompt does not reproduce a voice; cloning its
  reference does.

## [0.4.0] - 2026-11-20

### Added
- The runtime build now strips binaries: `dist/bin` went from **2.2 GB to
  93 MB** without changing behaviour (`audiocpp_cli --version` still reports
  commit `a282e4e`).

### Verified (first end-to-end run, CPU backend)
- `runtime build` compiled audio.cpp `a282e4e` and produced
  `audiocpp_cli` + `audiocpp_server`.
- First Spanish synthesis: "La casa llevaba veinte años vacía…" → 3.9 s of
  44.1 kHz mono, mean −20.4 dB, peak −4.5 dB in ~12 s of session time on CPU
  (RTF ≈ 3.1).
- `template_name=emotion` works and changes the take: `中性` (neutral) vs
  `恐惧` (fear) on the same sentence produced different duration, hashes and
  peak level (−1.4 dB vs −4.8 dB).
- Exact control vocabulary (must be passed verbatim, in Chinese):
  `emotion` = `高兴` `悲伤` `愤怒` `恐惧` `厌恶` `惊讶` `中性`;
  `speed` = `慢速` `中速` `快速`; `pitch` and `volume` = `低` `中` `高`.
  This maps 1:1 onto our `EmotionAxis`, with `MELANCHOLIC → 悲伤`.

## [0.3.1] - 2026-11-20

### Fixed
- Hardware detection reported `cuda` when only `nvcc` was installed. It now
  requires a real toolkit: `nvcc` **and** `libcufft` on disk. On this machine
  that changed the verdict from `cuda` to `cpu`, which is the truth — the first
  build died at CMake's `CUDA::cufft` link target.
- Vulkan is only reported as available when the build can actually use it:
  runtime library **and** `vulkan/vulkan.h` **and** `glslc`/`glslangValidator`.
- CUDA builds now pass `CUDAToolkit_ROOT` and `CMAKE_CUDA_COMPILER` when a
  toolkit root is found, as the runtime's docs require (a distro CUDA earlier
  in `PATH` otherwise wins and links the wrong runtime).

## [0.3.0] - 2026-11-20

### Added
- `voice-forge runtime` — hardware detection and reproducible build of the
  model runtime into `dist/`. `auto` picks CUDA when an NVIDIA GPU *and* a CUDA
  toolkit are present, Vulkan when only Vulkan is available, CPU otherwise.
- `dist/BUILD.json` records backend, reason, detected hardware, cmake flags and
  the resolved git SHA; a matching manifest makes `build` a no-op.
- `GET /api/runtime` and `GET /api/runtime/plan`.
- Tests for the detection matrix, flag mapping, idempotency and failure
  reporting — all without a GPU or a compiler.

## [0.2.0] - 2026-11-20

### Added
- **Admission control.** One host instance only: `up` refuses when a host is
  alive, and the host holds an OS `flock` so two racing CLIs cannot both win.
- **Serial work queue.** Every model job goes through a FIFO with one worker;
  extra requests wait in order instead of contending for the GPU.
- `voice-forge queue` and `GET /api/queue` expose depth and recent jobs; the
  web UI shows the queue state in the header.
- `down --force` to discard work in flight; without it, `down` refuses (409).

### Changed
- Project policy: **Apache-2.0 / MIT only**. IndexTTS-2.5 is excluded by
  license and removed from the roadmap as a target.
- Design and render now return a job id (API) and run through the queue.

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
