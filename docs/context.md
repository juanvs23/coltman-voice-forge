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
| **Recipe** | The provenance of a voice: brief, language, seed, model, picked candidate. Without it a voice cannot be reproduced. |
| **Brief** | The text description the operator writes to create a voice. |
| **Candidate** | One generated voice that is not yet registered. |
| **Emotion** | Eight normalised axes (`happy, angry, sad, afraid, disgusted, melancholic, surprised, calm`), a global `intensity`, and an optional free-text `hint`. |
| **Dialogue** | An ordered list of lines; each line names a voice, text, emotion, speed and trailing pause. |
| **Engine host** | A separate process, in a separate virtualenv, that owns the models and speaks JSON over HTTP. |
| **Warm** | Load weights and run a canary generation, so the first real line is not the slow one. |

## Structure

```
domain/       pure entities and rules; no I/O, no model names
application/  ports (contracts) + use cases (catalog, dialogue)
adapters/
  primary/    CLI, HTTP API, web UI
  secondary/  catalog on disk, engine HTTP client, engine supervisor, ffmpeg
engines/      the model host (runs in the model venv)
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

## Environment

- Host: RTX 4060 Laptop, 7.67 GB VRAM. **One model loaded at a time**; the host
  unloads the other mode before loading a new one.
- Model venv: `/path/to/qwen-tts/.venv` (torch 2.14 + cu130, `qwen_tts` 0.1.1).
- Shared weights: `/path/to/huggingface-cache` (`HF_HOME`).
- `ffmpeg` and `ffprobe` from the system.
