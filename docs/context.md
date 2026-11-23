# Context — voice-forge

## Purpose

A local voice factory for narrated video. It does three things and refuses to
become a platform:

1. **Create** a voice from a text description (prompt → audio).
2. **Clone** any reference clip into the catalog (a generated voice is just
   another reference).
3. **Narrate** a script with per-line emotional direction, reusing catalog
   voices, and deliver a mastered file.

## Domain vocabulary

| Term | Meaning |
|---|---|
| **Voice** | An immutable catalog entry: a reference clip plus the recipe that produced it. Identified by `slug`. |
| **Derived voice** | A voice created by transforming another voice's reference. `origin: derived`, with `derived_from` in the recipe. The source is never modified. |
| **Recipe** | The provenance of a voice: brief, language, seed, model, picked candidate. Without it a voice cannot be reproduced. |
| **Brief** | The text description the operator writes to create a voice. |
| **Candidate** | One generated voice that is not yet registered. |
| **Emotion** | Eight normalised axes (`happy, angry, sad, afraid, disgusted, melancholic, surprised, calm`), a global `intensity`, and an optional free-text `hint`. |
| **Dialogue** | An ordered list of lines; each line names a voice, text, emotion, speed and trailing pause. |
| **Engine host** | The process that owns the model: the `audio.cpp` server by default; the optional Python host (`engines/qwen_host.py`) used only by the `qwen` adapter. |
| **Runtime** | The compiled C++ binary that executes GGUF models (`audiocpp_cli` / `audiocpp_server`). Lives in `dist/`; the builder is meant to produce it, and today's CUDA binary is a hand build. |
| **Warm** | Load weights and run a canary generation, so the first real line is not the slow one. |

## Structure

```
domain/       pure entities and rules; no I/O, no model names
application/  ports (contracts) + use cases (catalog, dialogue)
adapters/
  primary/    CLI, HTTP API, web UI
  secondary/  catalog on disk, engine HTTP client, engine supervisor, ffmpeg
engines/      qwen_host.py (optional adapter host; not the default path)
dist/         compiled runtime + BUILD.json (gitignored)
```

## Invariants

- The domain never learns which model speaks. A model name in `domain/` is a bug.
- A voice is immutable. Changing one means a new slug; that keeps old renders
  reproducible.
- The reference clip is the voice. Delete `ref.wav` and the voice is gone.
- The engine is optional at import time: the API and CLI start even with the
  engine down, and fail only when a model is actually needed.
- **One instance, one job.** Starting a second host is an error; extra work
  waits in a FIFO instead of running in parallel.
- **Apache-2.0 / MIT only.** Custom-licensed weights are out of scope.

## Ownership

The repository is the **tool**; the catalog is the **instance's data**.

| The tool owns | The operator owns |
|---|---|
| The `voice.json` schema and directory layout | The voices themselves |
| Reading, validating, verifying integrity | Backups, retention, deletion |
| `out/`, `dist/`, code, docs | `catalog/` and where it lives |

Consequences that are deliberate, not oversights:

- `catalog/` is gitignored and no catalog is ever shipped with the repo.
- The path is configurable (`VOICEFORGE_CATALOG`); it belongs to the instance,
  not to the installation.
- There is **no** backup, restore, migrate, prune or "catalog manager" command.
  If an operator wants a backup, it is their `tar` and their cron.
- `voice-forge verify` is read-only: it reports, it never repairs or moves
  anything.

## Environment

- Host: RTX 4060 Laptop, 7.67 GB VRAM. **One model loaded at a time**; the host
  unloads the other mode before loading a new one.
- Core venv: created by `uv sync`, **no torch**.
- Runtime: `dist/bin/audiocpp_server` (and `audiocpp_cli`), a CUDA build linked
  against a local cuFFT prefix unpacked under `dist/cuda/`. Built by hand today;
  see `[DEBT] builder-cuda-prefix` in the roadmap.
- Weights: `models/ming3/*.gguf` (Ming-3.0-TTS-0.5B, MIT).
- Alternative adapter only: the model venv at `/path/to/qwen-tts/.venv`
  (torch + `qwen_tts`), used when `VOICEFORGE_ADAPTER=qwen`.
- Shared weights cache: `/path/to/huggingface-cache` (`HF_HOME`).
- `ffmpeg` and `ffprobe` from the system.
