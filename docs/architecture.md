# Architecture — hexagonal

## Why the core is model-free

The operator's rule: *the system is the owner; it depends on models, but it is
independent of what is outside.* That translates to one mechanical test:

```bash
grep -rn "qwen\|torch\|indextts\|zonos" src/voiceforge/domain src/voiceforge/application
```

It must return nothing. If it returns a hit, the dependency rule is broken and
swapping a model would mean editing the core — which is exactly what this
architecture exists to prevent.

## Layers

```
        ┌────────────────────────────────────────────┐
        │ adapters/primary    CLI · HTTP · Web UI     │
        └───────────────────┬────────────────────────┘
                            │ calls use cases
        ┌───────────────────▼────────────────────────┐
        │ application         ports + services       │
        │  CatalogService · DialogueService          │
        └───────────────────┬────────────────────────┘
                            │ depends only on ports
        ┌───────────────────▼────────────────────────┐
        │ domain              entities + rules       │
        └────────────────────────────────────────────┘
                            ▲
        ┌───────────────────┴────────────────────────┐
        │ adapters/secondary  catalog · http · ffmpeg│
        └────────────────────────────────────────────┘
```

Dependencies point inwards only. `adapters` may import `application` and
`domain`; `application` may import `domain`; `domain` imports nothing.

## The five ports

| Port | Contract | Today's adapter |
|---|---|---|
| `CatalogRepository` | save / list / get / remove | `fs_catalog.FileCatalog` (one directory per voice) |
| `VoiceDesigner` | brief → candidates | `HttpEngine.design` → qwen host (`VoiceDesign`) |
| `SpeechSynthesizer` | text + voice + emotion → wav | `HttpEngine.synthesize` → qwen host (`Base`) |
| `AudioAssembler` | segments → one mastered file | `FfmpegAssembler` |
| `EngineControl` | up / warm / status / down | `EngineSupervisor` (process + health) |

## Swapping a model

Replace `engines/qwen_host.py` with a host that speaks the same five JSON
endpoints, point `VOICEFORGE_ENGINE_SCRIPT` and `VOICEFORGE_ENGINE_PYTHON` at
it, and change nothing else. The catalog, the CLI, the API, the UI and the
tests keep working.

That is the whole point: IndexTTS or ZONOS3 are adapter work, not a rewrite.

## The design-then-clone invariant

A generated voice does **not** get a privileged path. `CatalogService.design`
registers the chosen candidate through the same `CatalogRepository.save` that
an uploaded clip uses, and every later line is cloned from `ref.wav`. This is
what makes a voice "created once, used a thousand times" — and it means a
designed voice and a third-party clip are indistinguishable downstream.

## Known limitation (deliberate, tracked)

Qwen3-TTS **Base** clones but does not accept style instructions, so the
current speech adapter cannot apply the emotion axes. The host reports this in
`/health` as `"emotion": "unsupported-by-speech-backend"` instead of pretending.
Closing that gap is roadmap phase P2: an emotion-capable host behind this same
contract.

Because the stack is Apache/MIT only, **IndexTTS-2.5 is excluded** (bilibili
license), even though it has the best measured Spanish cloning. Its emotion
interface is the reference design for the port, not an implementation target.

## Runtime bootstrap

The only compiled piece is the model runtime (`audio.cpp`). It is never built
by hand: `voice-forge runtime` decides from evidence and records the decision.

```
runtime plan ──> HardwareProbe ──> choose_backend ──> BuildPlan
runtime build ─> (fetch pinned source) → cmake configure → cmake build → dist/bin
                 └─> dist/BUILD.json  (backend, reason, hardware, flags, revision)
```

Decision order (`auto`):

| Evidence | Backend |
|---|---|
| NVIDIA GPU **and** a CUDA toolkit | `cuda` (`-DENGINE_ENABLE_CUDA=ON`, arch from `nvidia-smi`) |
| otherwise, Vulkan driver/tooling | `vulkan` (`-DENGINE_ENABLE_VULKAN=ON`) |
| otherwise | `cpu` (portable kernels) |

`--backend cuda|vulkan|cpu` overrides, and fails loudly when the machine cannot
honour it — never silently downgrades.

Properties that matter:
- **Idempotent.** A manifest matching backend + binaries returns
  `already-built` without invoking cmake.
- **Reproducible.** The manifest stores the resolved git SHA, not "main".
- **Auditable.** `dist/BUILD.json` is the record; `dist/` is gitignored.
- **Testable without a GPU.** Probe and command runner are injected, so the
  whole matrix runs in unit tests.

## Admission control

Two hard rules, enforced by the system rather than by documentation:

| Rule | Mechanism | Failure mode |
|---|---|---|
| One host instance | `up` checks health first and raises; the host itself takes `flock` on `out/engine.lock` and exits with code 3 if taken | HTTP 409, CLI exit 2 |
| One job at a time | `application/queue.py` — a FIFO with a single worker thread; submissions beyond 32 pending are refused | extra requests wait in order; `409` only for stop-while-busy |
| No killing work | `down` consults the queue's `busy` flag | `EngineBusy`; `--force` overrides |

Why a queue instead of parallel calls: one GPU, one model in VRAM. Running two
syntheses concurrently makes both slower and can abort with OOM. The queue is
the concurrency policy, and it is observable (`GET /api/queue`,
`voice-forge queue`).
