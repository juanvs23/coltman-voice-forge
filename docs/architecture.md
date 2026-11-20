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
Closing that gap is roadmap phase P2 (add an emotion-capable host behind the
same contract).
