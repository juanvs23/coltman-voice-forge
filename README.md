# voice-forge

Local-first voice factory. Design a voice from a text prompt, clone it from
any reference clip, and narrate scripts with graded emotional direction —
all on your own GPU, with a CLI, an HTTP API and an operator console.

The core is hexagonal: the domain does not know which model speaks. Swapping
Ming-3.0-TTS for ZONOS3 or anything else is an adapter change, not a rewrite.

Two rules are enforced by the code, not by convention: **one instance only**
(a second `up` fails, the host holds an OS lock) and **one job at a time**
(every model call goes through a FIFO; extra requests wait in order).

Everything is **Apache-2.0 / MIT**: custom-licensed weights are out of scope.

## Why this exists

The workflow that actually produces good narration is:

1. **Design** the voice once from a description (`Ming-3.0-TTS` VoiceDesign
   over `audio.cpp`).
2. **Register** the resulting clip as a catalog voice — the same path an
   imported/third-party clip takes.
3. **Narrate** any number of lines with emotional direction, reusing the same
   reference for every sentence.

A voice is created once and used a thousand times. The catalog stores the
*recipe* (prompt, seed, model) next to the clip, so a voice is reproducible.

## Quick start

```bash
uv sync --extra dev

uv run voice-forge up          # start the model host
uv run voice-forge warm        # load weights + canary synthesis
uv run voice-forge design "hombre de 60, voz grave y rasposa, susurrante, español neutro" \
    --slug narrador-terror --candidates 4
uv run voice-forge voices
uv run voice-forge queue        # what is running and what is waiting
uv run voice-forge render examples/dialogo.yaml --out out/demo.wav
uv run voice-forge down
```

Console and OpenAPI: `uv run voice-forge serve` → http://127.0.0.1:8720/ui
(API docs at http://127.0.0.1:8720/docs; `GET /` redirects to the console)

## Requirements

- Python ≥ 3.12 (`uv` recommended).
- `ffmpeg` in `PATH`.
- The compiled runtime in `dist/bin` (`audiocpp_cli` / `audiocpp_server`), built
  with `uv run voice-forge runtime build`. The builder detects a CUDA toolkit
  under `dist/cuda/usr` and links against it; on this machine the binaries
  report `backends: cpu,cuda`.
- The weights: a Ming-3.0 GGUF under `models/ming3/`.
- Only for the alternative `qwen` adapter (`VOICEFORGE_ADAPTER=qwen`): the
  `qwen-tts` virtualenv with torch and `qwen_tts`. Point elsewhere with
  `VOICEFORGE_ENGINE_PYTHON`.

The core environment has **no torch**. That is deliberate: a 200 MB install
must not become a 9 GB one.

## Project layout

```
src/voiceforge/
├── domain/          entities and rules (pure Python)
├── application/     ports + use cases
├── adapters/
│   ├── primary/     CLI, HTTP API, Gradio console (webui/)
│   └── secondary/   catalog on disk, engine HTTP client, ffmpeg assembler
├── config.py        settings from environment
└── container.py     wiring
engines/qwen_host.py model host (optional qwen adapter)
```

Docs: [`docs/context.md`](docs/context.md) ·
[`docs/architecture.md`](docs/architecture.md) ·
[`docs/roadmap.md`](docs/roadmap.md)

## License

Your code, your voices. The models keep their own licenses; the catalog
records which model produced each voice so provenance is never lost.
