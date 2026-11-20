# Changelog

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
